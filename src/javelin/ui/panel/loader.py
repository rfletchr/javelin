from qtpy import QtCore, QtWidgets

from javelin.project import ProjectManager
from javelin.ui.controller import PanelController
from javelin.ui.database import Database
from javelin.ui.panel.publishes import PublishesController, PublishesView
from javelin.ui.panel.shared import SharedData
from javelin.ui.panel.shots import ShotsController, ShotsView


class LoaderView(QtWidgets.QWidget):
    modeChanged = QtCore.Signal(bool)  # True == "current" mode

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.shots_view = ShotsView()
        self.publish_view = PublishesView()

        self.current_radio = QtWidgets.QRadioButton("Current")
        self.current_radio.setEnabled(False)
        self.all_radio = QtWidgets.QRadioButton("All")
        self.all_radio.setChecked(True)

        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.addButton(self.current_radio)
        self.mode_group.addButton(self.all_radio)

        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.addWidget(self.current_radio)
        mode_layout.addWidget(self.all_radio)
        mode_layout.addStretch(1)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.splitter.addWidget(self.shots_view)
        self.splitter.addWidget(self.publish_view)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(mode_layout)
        layout.addWidget(self.splitter)

        self.current_radio.toggled.connect(self.modeChanged)

    def setShotsModel(self, model):
        self.shots_view.setModel(model)

    def setPublishesModel(self, model):
        self.publish_view.setModel(model)

    def setCurrentModeEnabled(self, enabled: bool):
        self.current_radio.setEnabled(enabled)
        if not enabled and self.current_radio.isChecked():
            self.all_radio.setChecked(True)

    def setCurrentMode(self, current: bool):
        (self.current_radio if current else self.all_radio).setChecked(True)

    def setShotsCollapsed(self, collapsed: bool):
        self.shots_view.setVisible(not collapsed)


class LoaderController(PanelController):
    publishActivated = QtCore.Signal(object)  # Publish  # type: ignore

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
        self.publishes_controller.publishActivated.connect(self.publishActivated)
        self._view.modeChanged.connect(self.onModeChanged)
        self.__project: dict = {}
        self.__entity: dict = {}
        self.__current_mode = False
        self.__session_shot_id: int | None = None

    def setProject(self, project: dict):
        self.__project = project
        self.shots_controller.setProject(project)

    def selectShot(self, shot_id: int):
        """Record the session's current shot and switch to "Current" mode -- the default
        workflow most users want. If already in that mode, just re-selects the new shot."""
        self.__session_shot_id = shot_id
        self._view.setCurrentModeEnabled(True)
        if self.__current_mode:
            self.shots_controller.selectShotId(shot_id)
        else:
            self._view.setCurrentMode(True)  # triggers onModeChanged, which selects the shot

    def onModeChanged(self, current: bool):
        self.__current_mode = current
        self._view.setShotsCollapsed(current)
        if current and self.__session_shot_id is not None:
            self.shots_controller.selectShotId(self.__session_shot_id)

    def clearSessionShot(self):
        self.__session_shot_id = None
        self._view.setCurrentModeEnabled(False)

    def onEntityClicked(self, shot: dict):
        self.__entity = shot
        self.publishes_controller.setEntity(shot)

    def getView(self) -> LoaderView:
        return self._view

    def getName(self) -> str:
        return "Loader"
