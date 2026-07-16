import logging
import os
import signal
import subprocess
import urllib.error
import urllib.request

from qtpy import QtCore, QtGui, QtNetwork, QtWidgets

from javelin.project import CommandDefinition, Project, list_projects
from javelin.ui.controller import BaseController
from javelin.ui.database import Database, get_database
from javelin.ui.panel.shared import IconProviderModel, ModelRoles

ItemDataRole = QtCore.Qt.ItemDataRole

logger = logging.getLogger(__name__)

PROJECTS_DIR_ENV_VAR = "JAVELIN_PROJECTS_DIR"
DEFAULT_PROJECTS_DIR = "/mnt/projects"
USER_IMAGE_SIZE = 32


class CommandItem(QtGui.QStandardItem):
    def __init__(self, command: CommandDefinition):
        super().__init__(command.label)
        self.setEditable(False)
        self.setData(command, ItemDataRole.UserRole)
        self.setData(f"{command.label}.{command.extension}", ModelRoles.PathRole)


class CommandListView(QtWidgets.QWidget):
    commandActivated = QtCore.Signal(QtCore.QModelIndex)  # type: ignore

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.command_list = QtWidgets.QListView()
        self.command_list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.command_list)

        self.command_list.activated.connect(self.commandActivated)

    def setModel(self, model):
        self.command_list.setModel(model)


class CommandListController(BaseController):
    commandActivated = QtCore.Signal(object)  # CommandDefinition  # type: ignore

    def __init__(self, view: CommandListView | None = None, parent=None):
        super().__init__(parent=parent)
        self.view = view or CommandListView()

        self.model = QtGui.QStandardItemModel(self)
        self.icon_model = IconProviderModel(self)
        self.icon_model.setSourceModel(self.model)
        self.view.setModel(self.icon_model)

        self.view.commandActivated.connect(self.onCommandActivated)

    def setProject(self, project: Project):
        self.model.clear()
        for command in project.commands():
            self.model.appendRow(CommandItem(command))

    def onCommandActivated(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return
        self.commandActivated.emit(index.data(ItemDataRole.UserRole))


class ProjectItem(QtGui.QStandardItem):
    def __init__(self, tank_name: str, display_name: str):
        super().__init__(display_name)
        self.setEditable(False)
        self.setData(tank_name, ItemDataRole.UserRole)


class ProjectListView(QtWidgets.QWidget):
    projectActivated = QtCore.Signal(QtCore.QModelIndex)  # type: ignore

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.project_list = QtWidgets.QListView()
        self.project_list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.project_list)

        self.project_list.activated.connect(self.projectActivated)

    def setModel(self, model):
        self.project_list.setModel(model)


class ProjectListController(BaseController):
    projectSelected = QtCore.Signal(str)

    def __init__(self, projects_dir: str, database: Database, view: ProjectListView | None = None, parent=None):
        super().__init__(parent=parent)
        self.projects_dir = projects_dir
        self.database = database
        self.view = view or ProjectListView()
        self.__display_names: dict[str, str] = {}

        self.model = QtGui.QStandardItemModel(self)
        self.view.setModel(self.model)

        self.view.projectActivated.connect(self.onProjectActivated)

    def populate(self):
        tank_names = list_projects(self.projects_dir)
        self.setBusy(True)
        (
            self.database.find(self, "Project", [["tank_name", "in", tank_names]], ["tank_name", "name"])
            .then(lambda rows: self._onProjectsFetched(tank_names, rows))
            .and_finally(lambda: self.setBusy(False))
        )

    def _onProjectsFetched(self, tank_names: list[str], rows: list[dict]):
        self.__display_names = {row["tank_name"]: row["name"] for row in rows}

        self.model.clear()
        for tank_name in tank_names:
            self.model.appendRow(ProjectItem(tank_name, self.getDisplayName(tank_name)))

    def getDisplayName(self, tank_name: str) -> str:
        return self.__display_names.get(tank_name, tank_name)

    def onProjectActivated(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return
        self.projectSelected.emit(index.data(ItemDataRole.UserRole))


class LauncherView(QtWidgets.QWidget):
    backClicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.title_label = QtWidgets.QLabel()
        self.title_label.setObjectName("title_label")
        self.title_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        heading_font = self.title_label.font()
        heading_font.setPointSize(heading_font.pointSize() + 3)
        heading_font.setWeight(QtGui.QFont.Weight.DemiBold)
        self.title_label.setFont(heading_font)
        self.back_button = QtWidgets.QPushButton("Back")
        self.back_button.setObjectName("back_button")
        self.back_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        top_bar_layout = QtWidgets.QHBoxLayout()
        top_bar_layout.addWidget(self.title_label)
        top_bar_layout.addWidget(self.back_button)

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("top_bar")
        top_bar.setLayout(top_bar_layout)

        self.command_list_view = CommandListView()
        self.project_list_view = ProjectListView()

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.command_list_view)
        self.stack.addWidget(self.project_list_view)

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

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top_bar)
        layout.addWidget(self.stack, 1)
        layout.addWidget(bottom_bar)

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
                margin: 6px 8px;
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
        self.stack.setCurrentWidget(self.command_list_view)

    def showProjectList(self):
        self.stack.setCurrentWidget(self.project_list_view)

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

    def closeEvent(self, event: QtGui.QCloseEvent):
        # Closing the window (e.g. the WM's [X]) just hides it - the tray icon is what
        # actually keeps the app alive, per app.setQuitOnLastWindowClosed(False) in main().
        event.ignore()
        self.hide()


def _download_pixmap(url: str) -> QtGui.QPixmap | None:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read()
    except urllib.error.URLError:
        logger.exception("Failed to download user image from %s", url)
        return None

    pixmap = QtGui.QPixmap()
    if not pixmap.loadFromData(data):
        return None
    return pixmap


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

        self.command_list_controller = CommandListController(view=self.view.command_list_view)
        self.project_list_controller = ProjectListController(
            self.projects_dir, self.database, view=self.view.project_list_view
        )

        self.view.backClicked.connect(self.onBackClicked)
        self.command_list_controller.commandActivated.connect(self.onCommandActivated)
        self.project_list_controller.projectSelected.connect(self.onProjectSelected)

    def populate(self):
        self.project_list_controller.populate()
        self.view.setTitle("Projects")
        self.view.setBackEnabled(False)
        self.view.showProjectList()
        self.loadUserImage()

    def onBackClicked(self):
        if self.view.stack.currentWidget() is self.view.project_list_view:
            if self.project is not None:
                self.view.setTitle(self.project_list_controller.getDisplayName(str(self.project)))
                self.view.showCommandList()
        else:
            self.view.setTitle("Projects")
            self.view.showProjectList()

    def onProjectSelected(self, tank_name: str):
        self.project = Project.from_name(self.projects_dir, tank_name)
        self.command_list_controller.setProject(self.project)
        self.view.setTitle(self.project_list_controller.getDisplayName(tank_name))
        self.view.setBackEnabled(True)
        self.view.showCommandList()

    def onCommandActivated(self, command: CommandDefinition):
        if self.project is None:
            return

        env = os.environ.copy()
        env["JAVELIN_PROJECT_PATH"] = self.project.directory

        logger.info("Launching %s: %s", command.label, command.command)
        subprocess.Popen(command.command, env=env, start_new_session=True)

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


def _tray_icon() -> QtGui.QIcon:
    icon = QtGui.QIcon.fromTheme("applications-graphics")
    if icon.isNull():
        icon = QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
    return icon


class TrayController(BaseController):
    """Owns the QSystemTrayIcon: show/hide of the launcher window, and a
    Projects -> Commands menu that launches DCC sessions without opening the window."""

    def __init__(self, launcher_controller: LauncherController, parent=None):
        super().__init__(parent=parent)
        self.launcher_controller = launcher_controller
        self._project_cache: dict[str, Project] = {}
        self._project_submenus: dict[str, QtWidgets.QMenu] = {}

        self.menu = QtWidgets.QMenu()
        self.toggle_action = self.menu.addAction("Hide Javelin", self.onToggleView)
        self.menu.addSeparator()

        self.projects_menu = self.menu.addMenu("Projects")
        self.populateProjectsMenu()
        self.projects_menu.aboutToShow.connect(self.onProjectsMenuAboutToShow)

        self.menu.addSeparator()
        self.menu.addAction("Quit", QtWidgets.QApplication.instance().quit)

        self.menu.aboutToShow.connect(self.onMenuAboutToShow)

        self.tray_icon = QtWidgets.QSystemTrayIcon(_tray_icon(), parent)
        self.tray_icon.setToolTip("Javelin")
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self.onActivated)

    def show(self):
        self.tray_icon.show()

    def onMenuAboutToShow(self):
        view = self.launcher_controller.get_view()
        self.toggle_action.setText("Hide Javelin" if view.isVisible() else "Show Javelin")

    def populateProjectsMenu(self):
        """Build one submenu per project up front, each seeded with a placeholder action.

        GNOME/KDE render this menu out-of-process over DBusMenu, which decides whether an
        item is expandable from its children at the moment the menu is first serialized.
        A submenu that's still empty at that point never gets an arrow and never becomes
        clickable, so its own aboutToShow (where we'd normally populate lazily) never fires.
        The placeholder guarantees each submenu is always non-empty.
        """
        projects_dir = self.launcher_controller.projects_dir

        for tank_name in list_projects(projects_dir):
            submenu = self.projects_menu.addMenu(tank_name)
            submenu.addAction("Loading...").setEnabled(False)
            submenu.aboutToShow.connect(
                lambda tank_name=tank_name, submenu=submenu: self.onProjectSubmenuAboutToShow(tank_name, submenu)
            )
            self._project_submenus[tank_name] = submenu

    def onProjectsMenuAboutToShow(self):
        # Refresh labels only - rebuilding the submenus themselves would empty them again
        # and reintroduce the "never expandable" problem described above.
        display_names = self.launcher_controller.project_list_controller
        for tank_name, submenu in self._project_submenus.items():
            submenu.menuAction().setText(display_names.getDisplayName(tank_name))

    def onProjectSubmenuAboutToShow(self, tank_name: str, submenu: QtWidgets.QMenu):
        if tank_name in self._project_cache:
            return  # already populated from a previous open

        try:
            project = Project.from_name(self.launcher_controller.projects_dir, tank_name)
        except Exception:
            logger.exception("Failed to load project for tray menu: %s", tank_name)
            submenu.clear()
            submenu.addAction("Failed to load project").setEnabled(False)
            return

        self._project_cache[tank_name] = project

        submenu.clear()
        for command in project.commands():
            submenu.addAction(
                command.label,
                lambda tank_name=tank_name, command=command: self.launchCommand(tank_name, command),
            )

    def launchCommand(self, tank_name: str, command: CommandDefinition):
        project = self._project_cache[tank_name]

        env = os.environ.copy()
        env["JAVELIN_PROJECT_PATH"] = project.directory

        logger.info("Launching %s: %s", command.label, command.command)
        subprocess.Popen(command.command, env=env, start_new_session=True)

    def showView(self):
        view = self.launcher_controller.get_view()
        view.show()
        view.raise_()
        view.activateWindow()

    def onToggleView(self):
        view = self.launcher_controller.get_view()
        if view.isVisible():
            view.hide()
        else:
            self.showView()

    def onActivated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self.onToggleView()


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
    logging.basicConfig(level=logging.INFO)
    logger.info("Launching Javelin launcher...")

    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    signal_timer = _install_signal_handlers(app)  # noqa: F841 - keeps the timer alive

    if _notify_running_instance():
        logger.info("Another Javelin instance is already running, exiting.")
        return

    controller = LauncherController()
    controller.populate()

    tray = TrayController(controller)
    tray.show()

    single_instance_server = SingleInstanceServer()  # noqa: F841 - keeps the server alive
    single_instance_server.showRequested.connect(tray.showView)

    controller.get_view().show()
    app.exec()


if __name__ == "__main__":
    main()
