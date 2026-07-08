from __future__ import annotations

__all__ = ["Database"]

import logging
import threading
import typing

import shotgun_api3
from qtpy import QtCore, QtGui, QtWidgets
from shotgun_api3.shotgun import Shotgun  # type: ignore[reportPrivateImportUsage]

from javelin import auth
from javelin.ui.promise import Promise
from javelin.ui.utils import invokeInContext

SITE_URL = "https://elephant-goldfish.shotgrid.autodesk.com"


logger = logging.getLogger(__name__)


class _PooledConnection(typing.NamedTuple):
    client: Shotgun
    generation: int


class _NeedsAuth(Exception):
    """Raised internally when no usable credentials are cached yet."""


class _AuthPopup(QtWidgets.QDialog):
    """Blocks the main thread (its own nested event loop) while a worker
    thread waits on browser approval. Closes itself once ``done_event``
    is set, from whichever thread that happens on."""

    def __init__(self, cancel_event: threading.Event, done_event: threading.Event):
        super().__init__()
        self.setWindowTitle("Sign in")
        self.setModal(True)
        self._cancel_event = cancel_event
        self._done_event = done_event
        self.setMinimumWidth(320)

        icon = QtGui.QIcon.fromTheme("web-browser")
        if icon.isNull():
            icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)
        icon_label = QtWidgets.QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))

        text_label = QtWidgets.QLabel("Check your browser to finish signing in...")

        message_layout = QtWidgets.QHBoxLayout()
        message_layout.addWidget(icon_label)
        message_layout.addWidget(text_label, stretch=1)

        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.clicked.connect(self._onCancel)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(message_layout)
        layout.addWidget(cancel_button)

        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self._checkDone)
        self._poll.start(200)

    def _checkDone(self):
        if self._done_event.is_set():
            self._poll.stop()
            self.accept()

    def _onCancel(self):
        self._cancel_event.set()
        self._poll.stop()
        self.reject()


class Database:
    """Owns the one shotgun_api3 connection pool for the app.

    Thread-local clients (shotgun_api3.Shotgun isn't safe to share across
    threads) are created lazily and kept current via a generation counter:
    a successful reauth bumps the generation, and any thread-local client
    found stale on next use gets its session token refreshed in place.
    """

    def __init__(self):
        logger.info("Database initialized.")
        self.__local = threading.local()
        self.__lock = threading.Lock()
        self.__credentials: auth.Credentials | None = None
        self.__generation = 0

    def __call__(self, *args: typing.Any, **kwds: typing.Any) -> typing.Any:
        return self._get_connection()

    def __app(self):
        app = QtCore.QCoreApplication.instance()
        if app is None:
            raise RuntimeError("No QCoreApplication instance available")
        return app

    def get_entity_link(self, entity_type, entity_id):
        if not self.__credentials:
            raise RuntimeError("No credentials available")

        site_url = self.__credentials.site_url
        return f"{site_url}/detail/{entity_type}/{entity_id}"

    def get_connection(self) -> Shotgun:
        try:
            return self._get_connection()
        except _NeedsAuth:
            self.__reauthenticate(self.__generation)
            return self._get_connection()

    def _get_connection(self) -> Shotgun:
        pooled: _PooledConnection | None = getattr(self.__local, "connection", None)
        if pooled is not None and pooled.generation == self.__generation:
            return pooled.client

        with self.__lock:
            generation = self.__generation
            credentials = self.__credentials
            if credentials is None:
                credentials = auth.get_cached_credentials(SITE_URL)
                self.__credentials = credentials

        if credentials is None:
            raise _NeedsAuth()

        if pooled is not None:
            client = pooled.client
            client.config.session_token = credentials.session_token
        else:
            client = Shotgun(SITE_URL, session_token=credentials.session_token)

        self.__local.connection = _PooledConnection(client, generation)
        return client

    def __reauthenticate(self, observed_generation: int) -> None:
        with self.__lock:
            if self.__generation != observed_generation:
                # Another thread already refreshed while we waited for the lock.
                return

            credentials = auth.get_cached_credentials(SITE_URL)
            if credentials is None or not auth.validate(credentials):
                credentials = self.__interactive_authenticate()
                auth.store_credentials(credentials)

            self.__credentials = credentials
            self.__generation += 1

    def __interactive_authenticate(self) -> auth.Credentials:
        cancel_event = threading.Event()
        done_event = threading.Event()

        def _runPopup():
            _AuthPopup(cancel_event, done_event).exec()

        invokeInContext(self.__app(), _runPopup)
        try:
            return auth.authenticate(SITE_URL, cancel_event=cancel_event)
        finally:
            done_event.set()

    # -- call dispatch --------------------------------------------------

    def __invoke(self, method: str, args: tuple, kwargs: dict):
        try:
            client = self._get_connection()
            result = getattr(client, method)(*args, **kwargs)
            return result
        except (shotgun_api3.AuthenticationFault, _NeedsAuth):  # type: ignore[attr-defined]
            pooled: _PooledConnection | None = getattr(self.__local, "connection", None)
            observed_generation = pooled.generation if pooled else self.__generation
            self.__reauthenticate(observed_generation)
            client = self._get_connection()
            return getattr(client, method)(*args, **kwargs)

    def __call(self, context: QtCore.QObject, method: str, *args, **kwargs) -> Promise:
        promise = Promise(context, self.__invoke, method, args, kwargs)
        invokeInContext(context, lambda: QtCore.QThreadPool.globalInstance().start(promise))
        return promise

    # -- public API -------------------------------------------------------
    def user(self) -> dict:
        self._get_connection()
        if not self.__credentials:
            raise RuntimeError("Not authenticated")
        return self.__credentials.user

    def find(
        self,
        context: QtCore.QObject,
        entity_type: str,
        filters: list,
        fields: list[str] | None = None,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "find", entity_type, filters, fields, *args, **kwargs)

    def find_one(
        self,
        context: QtCore.QObject,
        entity_type: str,
        filters: list,
        fields: list[str] | None = None,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "find_one", entity_type, filters, fields, *args, **kwargs)

    def create(
        self,
        context: QtCore.QObject,
        entity_type: str,
        data: dict,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "create", entity_type, data, *args, **kwargs)

    def update(
        self,
        context: QtCore.QObject,
        entity_type: str,
        entity_id: int,
        data: dict,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "update", entity_type, entity_id, data, *args, **kwargs)

    def delete(
        self,
        context: QtCore.QObject,
        entity_type: str,
        entity_id: int,
    ) -> Promise:
        return self.__call(context, "delete", entity_type, entity_id)

    def batch(self, context: QtCore.QObject, requests: list[dict]) -> Promise:
        return self.__call(context, "batch", requests)


__database: Database | None = None
__database_lock = threading.Lock()


def get_database() -> Database:
    global __database
    if __database is None:
        with __database_lock:
            if __database is None:
                __database = Database()
    return __database


if __name__ == "__main__":
    from qtpy import QtWidgets

    from javelin import auth

    # auth.clear_credentials(SITE_URL)

    app = QtWidgets.QApplication([])
    db = get_database()

    view = QtWidgets.QLabel()

    def on_result(row: dict):
        view.setText(row["code"])

    result = db.find_one(app, "Shot", [], ["code"]).then(on_result)
    view.show()

    app.exec()
