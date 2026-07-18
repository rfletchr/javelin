from qtpy import QtCore, QtWidgets

from javelin.project import Project
from javelin.ui.controller import BaseController, PanelController
from javelin.ui.database import Database
from javelin.ui.panel.shots import ShotsController, ShotsView
from javelin.ui.panel.tasks import TasksController, TasksView
from javelin.ui.panel.workfiles import WorkfilesController, WorkfilesView


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
    workfileActivated = QtCore.Signal(object)  # Workfile  # type: ignore
    workfileCreated = QtCore.Signal(object)  # Workfile  # type: ignore

    def __init__(
        self,
        project: Project,
        db: Database,
        view: MyTasksView | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent=parent)
        self._view = view or MyTasksView()

        self.tasks_controller = TasksController(project, db, view=self._view.tasks_view)
        self.workfiles_controller = WorkfilesController(project, view=self._view.workfiles_view)

        self.tasks_controller.contextClicked.connect(self.workfiles_controller.setContext)

        self.tasks_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.workfileActivated.connect(self.workfileActivated)
        self.workfiles_controller.workfileCreated.connect(self.workfileCreated)

    def populate(self):
        self.tasks_controller.populate()


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
    workfileActivated = QtCore.Signal(object)  # Workfile  # type: ignore
    workfileCreated = QtCore.Signal(object)  # Workfile  # type: ignore

    def __init__(
        self,
        project: Project,
        db: Database,
        view: TaskBrowserView | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent=parent)
        self._view = view or TaskBrowserView()

        self.shots_controller = ShotsController(project, db, view=self._view.shots_view)
        self.tasks_controller = TasksController(project, db, view=self._view.tasks_view)
        self.workfiles_controller = WorkfilesController(project, view=self._view.workfiles_view)

        self.shots_controller.shotClicked.connect(self.onShotClicked)
        self.tasks_controller.contextClicked.connect(self.workfiles_controller.setContext)

        self.shots_controller.busyChanged.connect(self.setBusy)
        self.tasks_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.busyChanged.connect(self.setBusy)
        self.workfiles_controller.workfileActivated.connect(self.workfileActivated)
        self.workfiles_controller.workfileCreated.connect(self.workfileCreated)

    def onShotClicked(self, shot: dict):
        self.tasks_controller.setEntity(shot)
        self.workfiles_controller.clear()

    def populate(self):
        self.shots_controller.populate()


class FileOpenView(QtWidgets.QWidget):
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


class FileOpenController(PanelController):
    workfileActivated = QtCore.Signal(object)  # Workfile  # type: ignore
    workfileCreated = QtCore.Signal(object)  # Workfile  # type: ignore

    def __init__(
        self,
        project: Project,
        db: Database,
        view: FileOpenView | None = None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent=parent)
        self._view = view or FileOpenView()

        self.my_tasks_controller = MyTasksController(project, db, view=self._view.my_tasks_view)
        self.task_browser_controller = TaskBrowserController(project, db, view=self._view.task_browser_view)

        self.my_tasks_controller.busyChanged.connect(self.setBusy)
        self.task_browser_controller.busyChanged.connect(self.setBusy)
        self.my_tasks_controller.workfileActivated.connect(self.workfileActivated)
        self.my_tasks_controller.workfileCreated.connect(self.workfileCreated)
        self.task_browser_controller.workfileActivated.connect(self.workfileActivated)
        self.task_browser_controller.workfileCreated.connect(self.workfileCreated)

    def populate(self):
        self.my_tasks_controller.populate()
        self.task_browser_controller.populate()

    def getView(self) -> FileOpenView:
        return self._view

    def getName(self) -> str:
        return "Tasks"
