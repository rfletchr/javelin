import logging

from qtpy import QtCore, QtWidgets

from javelin.project import ContextClasses, ProjectManager
from javelin.publish import task_filters_for_context
from javelin.ui.controller import BaseController, PanelController
from javelin.ui.database import Database, get_database
from javelin.ui.panel.file_open import FileOpenController
from javelin.ui.panel.loader import LoaderController
from javelin.ui.panel.projects import ProjectsController, ProjectsView
from javelin.ui.panel.shared import SharedData

logger = logging.getLogger(__name__)


class MainView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._projects_view = ProjectsView()
        self.tab_view = QtWidgets.QTabWidget()

        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addWidget(self._projects_view)
        main_layout.addWidget(self.tab_view)
        self.setLayout(main_layout)

    def getProjectsView(self) -> ProjectsView:
        return self._projects_view

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


class MainController(BaseController):
    workfileActivated = QtCore.Signal(object)  # Workfile  # type: ignore
    workfileCreated = QtCore.Signal(object)  # Workfile  # type: ignore
    publishActivated = QtCore.Signal(object)  # Publish  # type: ignore

    def __init__(
        self,
        project_manager: ProjectManager,
        database: Database,
        shared_data: SharedData,
        view: MainView | None = None,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.project_manager = project_manager
        self.database = database
        self.view = view or MainView()
        self.shared_data = shared_data
        self._panel_controllers: list[PanelController] = []

        self.projects_controller = ProjectsController(project_manager, database, view=self.view.getProjectsView())
        self.file_open_controller = FileOpenController(project_manager, database, shared_data)
        self.loader_controller = LoaderController(project_manager, database, shared_data)

        self.addTabController(self.file_open_controller)
        self.addTabController(self.loader_controller)

        self.busyChanged.connect(self.view.setBusy)
        self.projects_controller.busyChanged.connect(self.setBusy)

        self.file_open_controller.workfileActivated.connect(self.workfileActivated)
        self.file_open_controller.workfileCreated.connect(self.workfileCreated)
        self.loader_controller.publishActivated.connect(self.publishActivated)

    def addTab(self, name: str, widget: QtWidgets.QWidget):
        if self.view.hasTab(name):
            raise ValueError(f"Tab with name '{name}' already exists.")
        self.view.addTab(name, widget)

    def addTabController(self, controller: PanelController):
        self.addTab(controller.getName(), controller.getView())
        controller.busyChanged.connect(self.setBusy)
        self.projects_controller.projectChanged.connect(controller.setProject)
        self._panel_controllers.append(controller)

    def populate(self):
        logger.info("Populating launcher...")
        self.projects_controller.populate()

    def setSessionWorkfile(self, path: str):
        project_name = self.project_manager.project_name_from_path(path)
        project = self.project_manager.get_project(project_name)
        context = project.context_from_path(path)
        self.setSessionContext(context)

    def clearSessionContext(self):
        """Cheap, synchronous reset of session-context state (e.g. once the scene closes):
        disables "Current" mode in the Loader and forgets its session shot. Leaves the picked
        project alone."""
        self.loader_controller.clearSessionShot()
        for controller in self._panel_controllers:
            controller.setContext(None)

    def setSessionContext(self, context: ContextClasses):
        """Notify every panel of the raw context, then resolve it to its ShotGrid Task and
        drive the panel to match: switches the selected project and, once its shots are
        loaded, selects the context's shot in the Loader view."""
        for controller in self._panel_controllers:
            controller.setContext(context)

        self.setBusy(True)

        def on_resolved(task: dict | None):
            if task is None:
                logger.warning("No ShotGrid Task found for context: %s", context)
                return

            self.loader_controller.selectShot(task["entity"]["id"])
            self.projects_controller.selectProjectByName(task["project.Project.tank_name"])

        (
            self.database.find_one(
                self,
                "Task",
                task_filters_for_context(context),
                ["project", "entity", "project.Project.tank_name"],
            )
            .then(on_resolved)
            .and_finally(lambda: self.setBusy(False))
        )

    def get_view(self):
        return self.view


def get_main_controller():
    db = get_database()
    manager = ProjectManager("/mnt/projects")
    db = get_database()
    shared_data = SharedData.from_db(db)

    return MainController(manager, db, shared_data)


def main():

    logging.basicConfig(level=logging.INFO)
    logger.info("Launching Rock UI launcher...")

    app = QtWidgets.QApplication([])
    controller = get_main_controller()
    controller.populate()
    controller.view.show()
    app.exec()


if __name__ == "__main__":
    main()
