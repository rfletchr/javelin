from __future__ import annotations

__all__ = ["LoginController", "LoginView"]

import logging
import threading

from qtpy import QtCore, QtGui, QtWidgets

from javelin import auth
from javelin.ui.controller import BaseController

logger = logging.getLogger(__name__)


class LoginView(QtWidgets.QWidget):
    """Shown in place of real content whenever there's no usable credentials yet."""

    cancelClicked = QtCore.Signal()
    retryClicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        icon = QtGui.QIcon.fromTheme("web-browser")
        if icon.isNull():
            icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)
        icon_label = QtWidgets.QLabel()
        icon_label.setPixmap(icon.pixmap(128, 128))

        self.message_label = QtWidgets.QLabel()

        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancelClicked)

        self.retry_button = QtWidgets.QPushButton("Retry")
        self.retry_button.clicked.connect(self.retryClicked)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.message_label, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        layout.addWidget(icon_label, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        layout.addLayout(button_layout, 0)

        self.setMinimumWidth(320)
        self.setMinimumHeight(320)
        self.setWaiting("Signing in...")

    def setWaiting(self, message: str):
        self.message_label.setText(message)
        self.cancel_button.setVisible(True)
        self.retry_button.setVisible(False)

    def setFailed(self, message: str):
        self.message_label.setText(message)
        self.cancel_button.setVisible(False)
        self.retry_button.setVisible(True)


class LoginController(BaseController):
    """Resolves credentials - cached, then validated, then (only if needed) the
    interactive browser flow - each step dispatched as its own promise, so the view's
    message updates happen as ordinary GUI-thread callbacks rather than by reaching
    across threads to drive the UI mid-flight.

    Knows nothing about Database or where its view gets shown. The owning controller is
    responsible for calling start(), listening for `ready`, and deciding what to do with
    the resulting credentials and with getView() once they arrive.
    """

    ready = QtCore.Signal(object)  # auth.Credentials

    def __init__(self, site_url: str, view: LoginView | None = None, parent=None):
        super().__init__(parent=parent)
        self.site_url = site_url
        self.view = view or LoginView()

        self.__in_progress = False
        self.__cancel_event: threading.Event | None = None

        self.view.cancelClicked.connect(self.__onCancelClicked)
        self.view.retryClicked.connect(self.start)

    def getView(self) -> QtWidgets.QWidget:
        return self.view

    def start(self):
        """Begin (or restart) the sign-in flow. Safe to call any time - e.g. once at
        startup, or from a Retry click after a failure. A no-op if already in progress."""
        if self.__in_progress:
            return
        self.__in_progress = True
        self.__cancel_event = None
        self.view.setWaiting("Checking for a saved sign-in...")
        (
            self.promise(auth.get_cached_credentials, self.site_url)
            .then(self.__onCachedCredentials)
            .catch(self.__onError)
        )

    def __onCachedCredentials(self, credentials: auth.Credentials | None):
        if credentials is None:
            self.__startInteractive()
            return

        self.view.setWaiting("Verifying saved sign-in...")
        (
            self.promise(auth.validate, credentials)
            .then(lambda valid: self.__onValidated(credentials, valid))
            .catch(self.__onError)
        )

    def __onValidated(self, credentials: auth.Credentials, valid: bool):
        if valid:
            self.__onCredentialsReady(credentials)
        else:
            self.__startInteractive()

    def __startInteractive(self):
        self.__cancel_event = threading.Event()
        self.view.setWaiting("Check your browser to finish signing in...")
        (
            self.promise(auth.authenticate, self.site_url, cancel_event=self.__cancel_event)
            .then(self.__onAuthenticated)
            .catch(self.__onError)
        )

    def __onAuthenticated(self, credentials: auth.Credentials):
        auth.store_credentials(credentials)
        self.__onCredentialsReady(credentials)

    def __onCredentialsReady(self, credentials: auth.Credentials):
        self.__in_progress = False
        self.ready.emit(credentials)

    def __onError(self, error: Exception):
        if self.__cancel_event is not None and self.__cancel_event.is_set():
            logger.info("Sign-in cancelled.")
            self.view.setFailed("Sign-in cancelled.")
        else:
            logger.warning("Sign-in failed: %s", error)
            self.view.setFailed(f"Sign-in failed: {error}")

    def __onCancelClicked(self):
        if self.__cancel_event is not None:
            self.__cancel_event.set()


if __name__ == "__main__":
    from javelin.ui.database import SITE_URL

    logging.basicConfig(level=logging.INFO)
    auth.clear_credentials(SITE_URL)

    # app = QtWidgets.QApplication([])

    # login = LoginController(SITE_URL)

    # content = QtWidgets.QLabel()
    # content.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

    # # Stands in for what the owning controller does in the real app: hold the stack,
    # # react to `ready`, decide what's shown.
    # stack = QtWidgets.QStackedWidget()
    # stack.addWidget(content)
    # stack.addWidget(login.getView())
    # stack.setCurrentWidget(login.getView())

    # def on_ready(credentials: auth.Credentials):
    #     content.setText(f"Signed in as {credentials.login}")
    #     stack.setCurrentWidget(content)

    # login.ready.connect(on_ready)
    # login.start()

    # stack.resize(400, 200)
    # stack.show()
    # app.exec()
