import logging

from qtpy import QtCore, QtGui, QtWidgets

from javelin.project import AssetContext, ContextClasses, EpisodicShotContext, Project, ShotContext
from javelin.publish import task_filters_for_context
from javelin.ui.controller import BaseController, PanelController
from javelin.ui.database import Database, get_database
from javelin.ui.login import LoginController, LoginView
from javelin.ui.panel.file_open import FileOpenController
from javelin.ui.panel.loader import LoaderController

logger = logging.getLogger(__name__)


def _context_label(context: ContextClasses) -> str:
    if isinstance(context, AssetContext):
        entity = f"{context.asset}"
    elif isinstance(context, EpisodicShotContext):
        entity = f"{context.shot}"
    elif isinstance(context, ShotContext):
        entity = f"{context.shot}"
    else:
        raise TypeError(f"unhandled context type: {type(context)}")

    return f"{entity} / {context.task}"


class MainView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.project_label = QtWidgets.QLabel()
        self.project_label.setObjectName("project_label")
        self.context_label = QtWidgets.QLabel()
        self.context_label.setObjectName("context_label")

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.addWidget(self.project_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.context_label)

        self.tab_view = QtWidgets.QTabWidget()

        self.content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.content)
        content_layout.addLayout(header_layout)
        content_layout.addWidget(self.tab_view)

        self.login_view = LoginView()
        self.outer_stack = QtWidgets.QStackedWidget()
        self.outer_stack.addWidget(self.content)
        self.outer_stack.addWidget(self.login_view)

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(self.outer_stack)

        self.setStyleSheet(
            """
            MainView QLabel#context_label {
                color: palette(placeholder-text);
            }
            """
        )

    def setProjectName(self, name: str):
        self.project_label.setText(name)

    def setContextText(self, text: str):
        self.context_label.setText(text)
        self.context_label.setVisible(bool(text))

    def addTab(self, name: str, widget: QtWidgets.QWidget):
        self.tab_view.addTab(widget, name)

    def hasTab(self, name: str) -> bool:
        return any(self.tab_view.tabText(i) == name for i in range(self.tab_view.count()))

    def setBusy(self, busy: bool):
        self.setDisabled(busy)

        if busy and not self.isEnabled():
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def getLoginView(self) -> QtWidgets.QWidget:
        return self.login_view

    def showLogin(self):
        self.outer_stack.setCurrentWidget(self.login_view)

    def showContent(self):
        self.outer_stack.setCurrentWidget(self.content)


class MainController(BaseController):
    workfileActivated = QtCore.Signal(object)  # Workfile  # type: ignore
    workfileCreated = QtCore.Signal(object)  # Workfile  # type: ignore
    publishActivated = QtCore.Signal(object)  # Publish  # type: ignore

    def __init__(
        self,
        project: Project,
        database: Database | None = None,
        view: MainView | None = None,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.project = project
        self.database = database or get_database()
        self.view = view or MainView()
        self._panel_controllers: list[PanelController] = []

        self.file_open_controller = FileOpenController(project, self.database)
        self.loader_controller = LoaderController(project, self.database)

        self.addTabController(self.file_open_controller)
        self.addTabController(self.loader_controller)

        self.view.setProjectName(str(self.project))
        self.view.setContextText("")

        self.busyChanged.connect(self.view.setBusy)

        self.file_open_controller.workfileActivated.connect(self.workfileActivated)
        self.file_open_controller.workfileCreated.connect(self.workfileCreated)
        self.loader_controller.publishActivated.connect(self.publishActivated)

        self.login_controller = LoginController(self.database.site_url, view=self.view.getLoginView())
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

    def addTab(self, name: str, widget: QtWidgets.QWidget):
        if self.view.hasTab(name):
            raise ValueError(f"Tab with name '{name}' already exists.")
        self.view.addTab(name, widget)

    def addTabController(self, controller: PanelController):
        self.addTab(controller.getName(), controller.getView())
        controller.busyChanged.connect(self.setBusy)
        self._panel_controllers.append(controller)

    def populate(self):
        logger.info("Populating panel for project: %s", self.project)
        self.file_open_controller.populate()
        self.loader_controller.populate()
        self.loadProjectName()

    def loadProjectName(self):
        tank_name = str(self.project)
        self.database.find_one(
            self,
            "Project",
            [["tank_name", "is", tank_name]],
            ["name"],
        ).then(self.onProjectFetched)

    def onProjectFetched(self, entity: dict | None):
        if entity is None:
            logger.warning("No ShotGrid Project found for tank_name: %s", self.project)
            return
        self.view.setProjectName(entity["name"])

    def setSessionWorkfile(self, path: str):
        try:
            context = self.project.context_from_path(path)
        except ValueError:
            logger.info("Path is not part of this project's pipeline, skipping: %s", path)
            return
        self.setSessionContext(context)

    def clearSessionContext(self):
        """Cheap, synchronous reset of session-context state (e.g. once the scene closes):
        disables "Current" mode in the Loader and forgets its session shot."""
        self.view.setContextText("")
        self.loader_controller.clearSessionShot()
        for controller in self._panel_controllers:
            controller.setContext(None)

    def setSessionContext(self, context: ContextClasses):
        """Notify every panel of the raw context, then resolve it to its ShotGrid Task and
        select the context's shot in the Loader view."""
        self.view.setContextText(_context_label(context))

        for controller in self._panel_controllers:
            controller.setContext(context)

        self.setBusy(True)

        def on_resolved(task: dict | None):
            if task is None:
                logger.warning("No ShotGrid Task found for context: %s", context)
                return

            self.loader_controller.selectShot(task["entity"]["id"])

        (
            self.database.find_one(
                self,
                "Task",
                task_filters_for_context(context),
                ["entity"],
            )
            .then(on_resolved)
            .and_finally(lambda: self.setBusy(False))
        )

    def get_view(self):
        return self.view


def get_main_controller(project: Project) -> MainController:
    return MainController(project, get_database())


def main():
    logging.basicConfig(level=logging.INFO)
    logger.info("Launching Javelin panel...")

    app = QtWidgets.QApplication([])
    project = Project.from_environment()
    controller = get_main_controller(project)
    controller.start()
    controller.view.show()
    app.exec()


if __name__ == "__main__":
    main()
