import logging

from qtpy import QtCore, QtWidgets

from javelin.project import ProjectManager, Workfile
from javelin.ui.controller import BaseController
from javelin.ui.database import Database
from javelin.ui.launcher.projects import ProjectsController, ProjectsView
from javelin.ui.launcher.publishes import PublishesController, PublishesView
from javelin.ui.launcher.shared import SharedData
from javelin.ui.launcher.shots import ShotsController, ShotsView
from javelin.ui.launcher.tasks import TasksController, TasksView
from javelin.ui.launcher.workfiles import WorkfilesController, WorkfilesView

logger = logging.getLogger(__name__)


class LoaderView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.shots_view = ShotsView()
        self.publish_view = PublishesView()

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.splitter.addWidget(self.shots_view)
        self.splitter.addWidget(self.publish_view)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.splitter)

    def setShotsModel(self, model):
        self.shots_view.setModel(model)

    def setPublishesModel(self, model):
        self.publish_view.setModel(model)


class LoaderController(BaseController):
    def __init__(
        self,
        project_manager: ProjectManager,
        db: Database,
        shared_data: SharedData,
        view: LoaderView | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent=parent)
        self._view = view or LoaderView()
        self.shared_data = shared_data

        self.publishes_controller = PublishesController(project_manager, db, view=self._view.publish_view)
        self.shots_controller = ShotsController(project_manager, db, shared_data, view=self._view.shots_view)

        self.shots_controller.shotClicked.connect(self.onEntityClicked)
        self.shots_controller.busyChanged.connect(self.setBusy)
        self.publishes_controller.busyChanged.connect(self.setBusy)
        self.__project: dict = {}
        self.__entity: dict = {}

    def setProject(self, project: dict):
        self.__project = project
        self.shots_controller.setProject(project)

    def onEntityClicked(self, shot: dict):
        self.__entity = shot
        self.publishes_controller.setEntity(shot)


class MyTasksView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.tasks_view = TasksView()
        self.workfiles_view = WorkfilesView()

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.splitter.addWidget(self.tasks_view)
        self.splitter.addWidget(self.workfiles_view)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)


class MyTasksController(BaseController):
    def __init__(
        self,
        project_manager: ProjectManager,
        db: Database,
        shared_data: SharedData,
        view: MyTasksView | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent=parent)
        self._view = view or MyTasksView()

        self.project_manager = project_manager

        self.tasks_controller = TasksController(project_manager, db, shared_data, view=self._view.tasks_view)
        self.workfiles_controller = WorkfilesController(project_manager, view=self._view.workfiles_view)

        self.tasks_controller.contextClicked.connect(self.workfiles_controller.setContext)

        self.tasks_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.workfileActivated.connect(self.onWorkfileActivated)

    def setProject(self, project: dict):
        self.tasks_controller.setProject(project)
        self.workfiles_controller.clear()

    def onWorkfileActivated(self, workfile: Workfile):
        print(workfile.path)


class TaskBrowserView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.shots_view = ShotsView()
        self.tasks_view = TasksView(compact=True)
        self.workfiles_view = WorkfilesView()

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.splitter.addWidget(self.shots_view)
        self.splitter.addWidget(self.tasks_view)
        self.splitter.addWidget(self.workfiles_view)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)


class TaskBrowserController(BaseController):
    def __init__(
        self,
        project_manager: ProjectManager,
        db: Database,
        shared_data: SharedData,
        view: TaskBrowserView | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent=parent)
        self._view = view or TaskBrowserView()

        self.project_manager = project_manager

        self.shots_controller = ShotsController(project_manager, db, shared_data, view=self._view.shots_view)
        self.tasks_controller = TasksController(project_manager, db, shared_data, view=self._view.tasks_view)
        self.workfiles_controller = WorkfilesController(project_manager, view=self._view.workfiles_view)

        self.shots_controller.shotClicked.connect(self.onShotClicked)
        self.tasks_controller.contextClicked.connect(self.workfiles_controller.setContext)

        self.shots_controller.busyChanged.connect(self.setBusy)
        self.tasks_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.workfileActivated.connect(self.onWorkfileActivated)

    def onShotClicked(self, shot: dict):
        self.tasks_controller.setEntity(shot)
        self.workfiles_controller.clear()

    def setProject(self, project: dict):
        self.shots_controller.setProject(project)
        self.workfiles_controller.clear()

    def onWorkfileActivated(self, workfile: Workfile):
        print(workfile.path)


class TasksCompositeView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.my_tasks_radio = QtWidgets.QRadioButton("My Tasks")
        self.my_tasks_radio.setChecked(True)

        self.all_tasks_radio = QtWidgets.QRadioButton("All Tasks")

        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.addButton(self.my_tasks_radio)
        self.mode_group.addButton(self.all_tasks_radio)

        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.addWidget(self.my_tasks_radio)
        mode_layout.addWidget(self.all_tasks_radio)
        mode_layout.addStretch(1)

        self.my_tasks_view = MyTasksView()
        self.task_browser_view = TaskBrowserView()

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.my_tasks_view)
        self.stack.addWidget(self.task_browser_view)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(mode_layout)
        layout.addWidget(self.stack)

        self.my_tasks_radio.toggled.connect(self.onMyTasksToggled)
        self.onMyTasksToggled(self.my_tasks_radio.isChecked())

    def onMyTasksToggled(self, checked: bool):
        self.stack.setCurrentWidget(self.my_tasks_view if checked else self.task_browser_view)


class TasksCompositeController(BaseController):
    def __init__(
        self,
        project_manager: ProjectManager,
        db: Database,
        shared_data: SharedData,
        view: TasksCompositeView | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent=parent)
        self._view = view or TasksCompositeView()

        self.project_manager = project_manager

        self.my_tasks_controller = MyTasksController(project_manager, db, shared_data, view=self._view.my_tasks_view)
        self.task_browser_controller = TaskBrowserController(
            project_manager, db, shared_data, view=self._view.task_browser_view
        )

        self.my_tasks_controller.busyChanged.connect(self.setBusy)
        self.task_browser_controller.busyChanged.connect(self.setBusy)

    def setProject(self, project: dict):
        self.my_tasks_controller.setProject(project)
        self.task_browser_controller.setProject(project)


class MainView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._projects_view = ProjectsView()
        self._tasks_composite_view = TasksCompositeView()

        self._loader_view = LoaderView()

        self.tab_view = QtWidgets.QTabWidget()
        self.tab_view.addTab(self._tasks_composite_view, "Tasks")
        self.tab_view.addTab(self._loader_view, "Loader")

        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addWidget(self._projects_view)
        main_layout.addWidget(self.tab_view)
        self.setLayout(main_layout)

    def getProjectsView(self) -> ProjectsView:
        return self._projects_view

    def getTasksCompositeView(self) -> TasksCompositeView:
        return self._tasks_composite_view

    def getLoaderView(self) -> LoaderView:
        return self._loader_view

    def setBusy(self, busy: bool):
        self.setDisabled(busy)

        if busy and not self.isEnabled():
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()


class MainController(BaseController):
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

        self.projects_controller = ProjectsController(project_manager, database, view=self.view.getProjectsView())
        self.tasks_composite_controller = TasksCompositeController(
            project_manager, database, shared_data, view=self.view.getTasksCompositeView()
        )
        self.loader_controller = LoaderController(
            project_manager, database, shared_data, view=self.view.getLoaderView()
        )

        self.projects_controller.projectChanged.connect(self.tasks_composite_controller.setProject)
        self.projects_controller.projectChanged.connect(self.loader_controller.setProject)

        self.busyChanged.connect(self.view.setBusy)
        self.projects_controller.busyChanged.connect(self.setBusy)
        self.tasks_composite_controller.busyChanged.connect(self.setBusy)
        self.loader_controller.busyChanged.connect(self.setBusy)

    def populate(self):
        logger.info("Populating launcher...")
        self.projects_controller.populate()


def main():
    import os

    from javelin.ui.database import get_database

    logging.basicConfig(level=logging.INFO)
    logger.info("Launching Rock UI launcher...")

    # TODO: move to the real entry point once one exists.
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.wayland.textinput.warning=false")
    # Native Wayland silently drops QDrag's icon surface on several compositors (confirmed: our
    # publish/shot drag pixmap never appears there but works under XWayland). Force XWayland by
    # default; an explicit QT_QPA_PLATFORM in the environment still wins over this.
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QtWidgets.QApplication([])

    manager = ProjectManager("/mnt/shared/facility", "/mnt/projects")
    db = get_database()
    shared_data = SharedData.from_db(db)

    controller = MainController(manager, db, shared_data)
    controller.populate()
    controller.view.show()
    app.exec()


if __name__ == "__main__":
    main()
