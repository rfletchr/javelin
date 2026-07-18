import logging
import os
import signal
import subprocess
import urllib.error
import urllib.request

import qtawesome as qta
from qtpy import QtCore, QtGui, QtNetwork, QtWidgets

from javelin.project import CommandDefinition, Project, list_projects
from javelin.ui import icon_resources
from javelin.ui.controller import BaseController
from javelin.ui.database import Database, get_database
from javelin.ui.login import LoginController, LoginView

ItemDataRole = QtCore.Qt.ItemDataRole

logger = logging.getLogger(__name__)

PROJECTS_DIR_ENV_VAR = "JAVELIN_PROJECTS_DIR"
DEFAULT_PROJECTS_DIR = "/mnt/projects"
USER_IMAGE_SIZE = 32
PROJECT_IMAGE_SIZE = 48


class CommandItem(QtGui.QStandardItem):
    def __init__(self, command: CommandDefinition):
        super().__init__(command.label)
        self.setEditable(False)
        self.setData(command, ItemDataRole.UserRole)
        self.setIcon(_command_icon(command))


class ProjectItem(QtGui.QStandardItem):
    def __init__(self, tank_name: str, display_name: str, commands: tuple[CommandDefinition, ...]):
        super().__init__(display_name)
        self.setEditable(False)
        self.setData(tank_name, ItemDataRole.UserRole)
        for command in commands:
            self.appendRow(CommandItem(command))

    def setImage(self, pixmap: QtGui.QPixmap):
        self.setIcon(QtGui.QIcon(pixmap))


class ProjectModelController(BaseController):
    """Owns a single two-level model - top-level rows are projects, each with its
    CommandDefinitions as child rows. The project list and command list views (and the
    tray's Projects menu) all read from this one shared, eagerly-loaded tree using
    different root indexes, instead of each re-scanning disk / re-running every project's
    init.py independently."""

    populated = QtCore.Signal()

    def __init__(self, projects_dir: str, database: Database, parent=None):
        super().__init__(parent=parent)
        self.projects_dir = projects_dir
        self.database = database
        self.projects: dict[str, Project] = {}
        self.__display_names: dict[str, str] = {}

        self.model = QtGui.QStandardItemModel(self)

    def populate(self):
        """Re-scan projects_dir and reload every project's init.py from scratch, replacing
        the model wholesale. Loading each Project runs off the GUI thread via
        self.promise() - it's fast (milliseconds per project) but this keeps the UI locked
        with a busy cursor while it happens, consistent with the rest of the codebase.
        """
        self.setBusy(True)
        tank_names = list_projects(self.projects_dir)
        (
            self.promise(self._loadProjects, tank_names)
            .then(self._onProjectsLoaded)
            .and_finally(lambda: self.setBusy(False))
        )

    def _loadProjects(self, tank_names: list[str]) -> dict[str, Project]:
        projects = {}
        for tank_name in tank_names:
            try:
                projects[tank_name] = Project.from_name(self.projects_dir, tank_name)
            except Exception:
                logger.exception("Failed to load project: %s", tank_name)
        return projects

    def _onProjectsLoaded(self, projects: dict[str, Project]):
        self.projects = projects

        self.model.clear()
        for tank_name, project in self.projects.items():
            self.model.appendRow(ProjectItem(tank_name, self.getDisplayName(tank_name), project.commands()))
        self.populated.emit()

        # Rows are up immediately with tank_name as a fallback label - display names and
        # images are ShotGrid data, fetched in the background and dropped in once they land.
        self.database.find(
            self, "Project", [["tank_name", "in", list(self.projects)]], ["tank_name", "name", "image"]
        ).then(self._onNamesFetched)

    def _onNamesFetched(self, rows: list[dict]):
        self.__display_names = {row["tank_name"]: row["name"] for row in rows}
        image_urls = {row["tank_name"]: row.get("image") for row in rows}

        for row in range(self.model.rowCount()):
            item = self.model.item(row)
            tank_name = item.data(ItemDataRole.UserRole)

            display_name = self.__display_names.get(tank_name)
            if display_name:
                item.setText(display_name)

            image_url = image_urls.get(tank_name)
            if image_url:
                self.promise(_download_pixmap, image_url).then(
                    lambda pixmap, item=item: self._onImageLoaded(item, pixmap)
                )

    def _onImageLoaded(self, item: QtGui.QStandardItem, pixmap: QtGui.QPixmap | None):
        if pixmap:
            item.setIcon(QtGui.QIcon(pixmap))

    def getDisplayName(self, tank_name: str) -> str:
        return self.__display_names.get(tank_name, tank_name)

    def getProject(self, tank_name: str) -> Project | None:
        return self.projects.get(tank_name)


class LauncherView(QtWidgets.QWidget):
    backClicked = QtCore.Signal()
    reloadRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.title_label = QtWidgets.QLabel()
        self.title_label.setObjectName("title_label")
        self.title_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        heading_font = self.title_label.font()
        heading_font.setPointSize(heading_font.pointSize() + 3)
        heading_font.setWeight(QtGui.QFont.Weight.DemiBold)
        self.title_label.setFont(heading_font)
        self.back_button = QtWidgets.QPushButton(qta.icon("fa5s.arrow-left"), "Back")
        self.back_button.setObjectName("back_button")
        self.back_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        top_bar_layout = QtWidgets.QHBoxLayout()
        top_bar_layout.addWidget(self.title_label)
        top_bar_layout.addWidget(self.back_button)

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("top_bar")
        top_bar.setLayout(top_bar_layout)

        self.command_list = QtWidgets.QListView()
        self.command_list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.project_list = QtWidgets.QListView()
        self.project_list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.project_list.setIconSize(QtCore.QSize(PROJECT_IMAGE_SIZE, PROJECT_IMAGE_SIZE))

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.command_list)
        self.stack.addWidget(self.project_list)

        self.user_image_label = QtWidgets.QLabel()
        self.user_image_label.setObjectName("user_image_label")
        self.user_image_label.setFixedSize(USER_IMAGE_SIZE, USER_IMAGE_SIZE)
        self.user_image_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        bottom_bar_layout = QtWidgets.QHBoxLayout()
        bottom_bar_layout.addStretch(1)
        bottom_bar_layout.addWidget(self.user_image_label)

        bottom_bar = QtWidgets.QWidget()
        bottom_bar.setObjectName("bottom_bar")
        bottom_bar.setLayout(bottom_bar_layout)

        self.content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(top_bar)
        content_layout.addWidget(self.stack, 1)
        content_layout.addWidget(bottom_bar)

        self.login_view = LoginView()
        self.outer_stack = QtWidgets.QStackedWidget()
        self.outer_stack.addWidget(self.content)
        self.outer_stack.addWidget(self.login_view)

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(self.outer_stack)

        self.back_button.clicked.connect(self.backClicked)

        self.setStyleSheet(
            """
            LauncherView QWidget#top_bar,
            LauncherView QWidget#bottom_bar {
                background-color: palette(dark);
            }

            LauncherView QLabel#title_label {
                padding: 8px;
            }

            LauncherView QPushButton#back_button {
                margin: 6px 8px;
                padding: 4px 14px;
                border: 1px solid palette(mid);
                border-radius: 4px;
                background-color: palette(button);
            }

            LauncherView QPushButton#back_button:hover:!disabled {
                background-color: palette(light);
            }

            LauncherView QPushButton#back_button:disabled {
                color: palette(mid);
            }

            LauncherView QLabel#user_image_label {
                margin: 2px 2px;
                border-radius: 4px;
                background-color: palette(base);
            }

            LauncherView QListView {
                border: none;
                outline: 0;
                padding: 4px;
            }

            LauncherView QListView::item {
                padding: 6px 8px;
                border-radius: 4px;
            }

            LauncherView QListView::item:hover {
                background-color: palette(alternate-base);
            }

            LauncherView QListView::item:selected {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
            """
        )

    def showCommandList(self):
        self.stack.setCurrentWidget(self.command_list)

    def showProjectList(self):
        self.stack.setCurrentWidget(self.project_list)

    def getLoginView(self) -> QtWidgets.QWidget:
        return self.login_view

    def showLogin(self):
        self.outer_stack.setCurrentWidget(self.login_view)

    def showContent(self):
        self.outer_stack.setCurrentWidget(self.content)

    def setTitle(self, text: str):
        self.title_label.setText(text)

    def setBackEnabled(self, enabled: bool):
        self.back_button.setEnabled(enabled)

    def setUserImage(self, pixmap: QtGui.QPixmap | None):
        if pixmap is None or pixmap.isNull():
            self.user_image_label.clear()
            return

        scaled = pixmap.scaled(
            self.user_image_label.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.user_image_label.setPixmap(scaled)

    def setBusy(self, busy: bool):
        self.setDisabled(busy)

        if busy and not self.isEnabled():
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def closeEvent(self, event: QtGui.QCloseEvent):
        # Closing the window (e.g. the WM's [X]) just hides it - the tray icon is what
        # actually keeps the app alive, per app.setQuitOnLastWindowClosed(False) in main().
        event.ignore()
        self.hide()

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        menu = QtWidgets.QMenu(self)
        menu.addAction(qta.icon("fa5s.sync"), "Reload", lambda: self.reloadRequested.emit())
        menu.addSeparator()
        menu.addAction(qta.icon("fa5s.sign-out-alt"), "Quit", QtWidgets.QApplication.instance().quit)
        menu.exec(event.globalPos())


def _download_pixmap(url: str) -> QtGui.QPixmap | None:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read()
    except urllib.error.URLError:
        logger.exception("Failed to download image from %s", url)
        return None

    pixmap = QtGui.QPixmap()
    if not pixmap.loadFromData(data):
        return None
    return pixmap


def launch(project: Project, command: CommandDefinition):
    env = os.environ.copy()
    env["JAVELIN_PROJECT_PATH"] = project.directory

    logger.info("Launching %s: %s", command.label, command.command)
    subprocess.Popen(command.command, env=env, start_new_session=True)


class LauncherController(BaseController):
    def __init__(
        self,
        projects_dir: str | None = None,
        database: Database | None = None,
        view: LauncherView | None = None,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.projects_dir = projects_dir or os.environ.get(PROJECTS_DIR_ENV_VAR, DEFAULT_PROJECTS_DIR)
        self.database = database or get_database()
        self.view = view or LauncherView()
        self.project: Project | None = None

        self.project_model_controller = ProjectModelController(self.projects_dir, self.database)
        self.view.project_list.setModel(self.project_model_controller.model)
        self.view.command_list.setModel(self.project_model_controller.model)

        self.login_controller = LoginController(self.database.site_url, view=self.view.getLoginView())

        self.view.backClicked.connect(self.onBackClicked)
        self.view.reloadRequested.connect(self.reload)
        self.view.project_list.activated.connect(self.onProjectActivated)
        self.view.command_list.activated.connect(self.onCommandActivated)

        self.project_model_controller.busyChanged.connect(self.setBusy)
        self.busyChanged.connect(self.view.setBusy)

        self.database.authenticationRequired.connect(self.onAuthenticationRequired)
        self.login_controller.ready.connect(self.onCredentialsReady)

    def start(self):
        """Entry point - shows the login screen and begins sign-in. populate() runs once
        credentials are ready, whether that's now or after any later reauth."""
        self.onAuthenticationRequired()

    def onAuthenticationRequired(self):
        self.view.showLogin()
        self.login_controller.start()

    def onCredentialsReady(self, credentials):
        self.database.set_credentials(credentials)
        self.view.showContent()
        self.populate()

    def populate(self):
        self.project_model_controller.populate()
        self.loadUserImage()
        self._showProjectList()

    def reload(self):
        """Re-scan projects_dir and re-fetch ShotGrid names/commands from scratch, and
        reset to the Projects page with nothing selected - simpler than trying to carry a
        selection across a wholesale model rebuild, and this already re-emits `populated`,
        which TrayController listens on to rebuild the tray's Projects menu too.
        """
        logger.info("Reloading projects and commands...")
        self.project_model_controller.populate()
        self._showProjectList()

    def onBackClicked(self):
        self._showProjectList()

    def _showProjectList(self):
        self.project = None
        self.view.setTitle("Projects")
        self.view.setBackEnabled(False)
        self.view.showProjectList()

    def onProjectActivated(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return

        tank_name = index.data(ItemDataRole.UserRole)
        self.project = self.project_model_controller.getProject(tank_name)
        self.view.command_list.setRootIndex(index)
        self.view.setTitle(self.project_model_controller.getDisplayName(tank_name))
        self.view.setBackEnabled(True)
        self.view.showCommandList()

    def onCommandActivated(self, index: QtCore.QModelIndex):
        if not index.isValid() or self.project is None:
            return
        launch(self.project, index.data(ItemDataRole.UserRole))

    def loadUserImage(self):
        user = self.database.user()
        self.database.find_one(self, "HumanUser", [["id", "is", user["id"]]], ["image"]).then(self.onUserFetched)

    def onUserFetched(self, entity: dict | None):
        url = entity.get("image") if entity else None
        if not url:
            self.view.setUserImage(None)
            return

        self.promise(_download_pixmap, url).then(self.view.setUserImage)

    def get_view(self) -> LauncherView:
        return self.view


def _command_icon(command: CommandDefinition) -> QtGui.QIcon:
    if not command.icon:
        return QtGui.QIcon()
    return QtGui.QIcon(command.icon)


def _tray_icon() -> QtGui.QIcon:
    icon = QtGui.QIcon(f"{icon_resources.PREFIX}/icon.png")
    if icon.isNull():
        icon = QtGui.QIcon.fromTheme("applications-graphics")
    if icon.isNull():
        icon = QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
    return icon


class TrayController(BaseController):
    """Owns the QSystemTrayIcon: raising the launcher window, and a
    Projects -> Commands menu that launches DCC sessions without opening the window."""

    def __init__(self, launcher_controller: LauncherController, parent=None):
        super().__init__(parent=parent)
        self.launcher_controller = launcher_controller

        self.menu = QtWidgets.QMenu()
        self.menu.addAction(qta.icon("fa5s.external-link-alt"), "Show UI", self.showView)
        self.menu.addSeparator()

        self.projects_menu = self.menu.addMenu(qta.icon("fa5s.folder"), "Projects")
        self.buildProjectsMenu()
        # The shared model is usually still empty when we build the menu above (project
        # loading is async) - rebuild once it lands, rather than resolving anything lazily
        # on open.
        launcher_controller.project_model_controller.populated.connect(self.buildProjectsMenu)

        self.menu.addSeparator()
        self.menu.addAction(qta.icon("fa5s.sync"), "Reload", launcher_controller.reload)
        self.menu.addSeparator()
        self.menu.addAction(qta.icon("fa5s.sign-out-alt"), "Quit", QtWidgets.QApplication.instance().quit)

        self.tray_icon = QtWidgets.QSystemTrayIcon(_tray_icon(), parent)
        self.tray_icon.setToolTip("Javelin")
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self.onActivated)

    def show(self):
        self.tray_icon.show()

    def buildProjectsMenu(self):
        """Mirrors the shared project/command model onto the tray's Projects submenu -
        nothing is loaded here, it just walks rows the model has already built."""
        self.projects_menu.clear()
        model = self.launcher_controller.project_model_controller.model

        for row in range(model.rowCount()):
            project_item = model.item(row)
            tank_name = project_item.data(ItemDataRole.UserRole)

            submenu = self.projects_menu.addMenu(project_item.text())
            for command_row in range(project_item.rowCount()):
                command_item = project_item.child(command_row)
                command = command_item.data(ItemDataRole.UserRole)
                submenu.addAction(
                    command_item.icon(),
                    command.label,
                    lambda tank_name=tank_name, command=command: self.launchCommand(tank_name, command),
                )

    def launchCommand(self, tank_name: str, command: CommandDefinition):
        project = self.launcher_controller.project_model_controller.getProject(tank_name)
        if project is None:
            return
        launch(project, command)

    def showView(self):
        view = self.launcher_controller.get_view()
        view.show()
        view.raise_()
        view.activateWindow()

    def onActivated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self.showView()


SINGLE_INSTANCE_SERVER_NAME = "javelin-launcher"
SINGLE_INSTANCE_TIMEOUT_MS = 500
_SHOW_REQUEST = b"show"
_SHOW_REPLY = b"ok"


def _notify_running_instance() -> bool:
    """Ask any already-running launcher (over a local socket - a Unix domain socket on
    Linux/macOS, a named pipe on Windows, all handled transparently by QLocalSocket) to
    show itself.

    Returns True only once that instance actually *replies* - being able to connect
    isn't proof of a healthy process, since a hung instance can still hold the socket
    open without ever answering. Callers should treat both "nothing is listening" and
    "connected but never replied" the same way: proceed to start up as normal and take
    over as the new instance.
    """
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_SERVER_NAME)
    if not socket.waitForConnected(SINGLE_INSTANCE_TIMEOUT_MS):
        return False

    socket.write(_SHOW_REQUEST)
    socket.flush()

    if not socket.waitForReadyRead(SINGLE_INSTANCE_TIMEOUT_MS):
        logger.warning("Existing Javelin instance did not respond in time, taking over.")
        socket.abort()
        return False

    replied = bytes(socket.readAll()) == _SHOW_REPLY
    socket.disconnectFromServer()
    return replied


class SingleInstanceServer(QtCore.QObject):
    """Listens for _notify_running_instance() pings from later launches and re-emits
    them as showRequested, so a second launch just raises this process's window
    instead of starting a second instance."""

    showRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        # Only reached after _notify_running_instance() already failed or timed out,
        # i.e. nothing is actually listening anymore - safe to clear a socket file a
        # crashed process left behind, which would otherwise make listen() below fail.
        QtNetwork.QLocalServer.removeServer(SINGLE_INSTANCE_SERVER_NAME)

        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._onNewConnection)
        if not self.server.listen(SINGLE_INSTANCE_SERVER_NAME):
            logger.warning("Could not start single-instance server: %s", self.server.errorString())

    def _onNewConnection(self):
        socket = self.server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._onReadyRead(socket))

    def _onReadyRead(self, socket: QtNetwork.QLocalSocket):
        if bytes(socket.readAll()) == _SHOW_REQUEST:
            self.showRequested.emit()
            socket.write(_SHOW_REPLY)
            socket.flush()
        socket.disconnectFromServer()


def _install_signal_handlers(app: QtWidgets.QApplication) -> QtCore.QTimer:
    """Let SIGINT (Ctrl-C) and SIGTERM quit the app instead of being silently ignored.

    Qt's event loop runs entirely in C++ and never hands control back to the Python
    interpreter, so Python's signal handlers are never invoked while app.exec() blocks.
    A short-interval QTimer forces the interpreter to wake up regularly, which is enough
    for the handler queued by a signal to actually run. The timer is returned so the
    caller can keep a reference alive for as long as the app runs.
    """
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    signal.signal(signal.SIGTERM, lambda *_args: app.quit())

    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)
    return timer


def main():
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Launching Javelin launcher...")

    app = QtWidgets.QApplication([])
    app.setApplicationName("Javelin Launcher")
    app.setWindowIcon(_tray_icon())

    app.setQuitOnLastWindowClosed(False)
    signal_timer = _install_signal_handlers(app)  # noqa: F841 - keeps the timer alive

    if _notify_running_instance():
        logger.info("Another Javelin instance is already running, exiting.")
        return

    controller = LauncherController()
    controller.start()

    tray = TrayController(controller)
    tray.show()

    single_instance_server = SingleInstanceServer()  # noqa: F841 - keeps the server alive
    single_instance_server.showRequested.connect(tray.showView)

    controller.get_view().show()
    app.exec()


if __name__ == "__main__":
    main()
