from __future__ import annotations

from qtpy import QtCore, QtGui, QtWidgets

from javelin.project import ProjectManager
from javelin.ui.controller import BaseController
from javelin.ui.database import Database
from javelin.ui.panel.shared import (
    BurninStamp,
    GenerationalItemModel,
    ImageProviderModel,
    IndexType,
    ItemDataRole,
    ModelRoles,
    SharedData,
    StampListView,
)


class ShotItem(QtGui.QStandardItem):
    @staticmethod
    def fields() -> list[str]:
        return ["code", "sg_status_list", "project.Project.tank_name", "image_blur_hash"]

    def __init__(self, entity: dict, shared_data: SharedData):
        super().__init__()
        self.setEditable(False)
        self.setData(entity, ItemDataRole.UserRole)
        self.setData(entity["code"], ModelRoles.NameRole)

        self.setData(shared_data.status_code_to_name[entity["sg_status_list"]], ModelRoles.StatusRole)

        self.setData(entity["project.Project.tank_name"], ModelRoles.ProjectNameRole)
        self.setData(entity["image_blur_hash"], ModelRoles.BlurhashRole)
        self.setData(entity, ModelRoles.ThumbnailEntityRole)


class ShotStamp(BurninStamp):
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)

        self.entity_label = self._make_label("primary", "entity_label")
        self.top_layout.addWidget(self.entity_label)

        self.status_label = self._make_label("secondary", "status_label")
        self.bottom_layout.addWidget(self.status_label)

    def populate(self, index: IndexType):
        image = index.data(ItemDataRole.DecorationRole)
        if image:
            self.image_widget.setPixmap(image)

        entity_name = index.data(ModelRoles.NameRole)
        if entity_name:
            self.entity_label.setText(entity_name)

        status = index.data(ModelRoles.StatusRole)
        if status:
            self.status_label.setText(status)


class ShotsView(QtWidgets.QWidget):
    shotClicked = QtCore.Signal(QtCore.QModelIndex)  # type: ignore
    shotFilterChanged = QtCore.Signal(str)  # type: ignore

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.shot_filter = QtWidgets.QLineEdit()
        self.shot_filter.setPlaceholderText("Filter shots...")

        self.shot_list = StampListView(ShotStamp(), empty_text="no shots found...")
        self.shot_list.setMinimumWidth(420)
        self.shot_list.setDragEnabled(False)

        shot_layout = QtWidgets.QVBoxLayout(self)
        shot_layout.setContentsMargins(0, 0, 0, 0)
        shot_layout.addWidget(self.shot_filter, 0)
        shot_layout.addWidget(self.shot_list, 1)

        self.shot_list.clicked.connect(self.shotClicked)
        self.shot_filter.textChanged.connect(self.shotFilterChanged)

    def setModel(self, model):
        self.shot_list.setModel(model)


class ShotsController(BaseController):
    shotClicked = QtCore.Signal(dict)  # type: ignore

    def __init__(
        self,
        project_manager: ProjectManager,
        db: Database,
        shared_data: SharedData,
        view: ShotsView | None = None,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.project_manager = project_manager
        self.db = db
        self.shared_data = shared_data

        self.model = GenerationalItemModel()

        self.images_model = ImageProviderModel("/mnt/projects")  # TODO: inject
        self.images_model.setSourceModel(self.model)

        self.filter_model = QtCore.QSortFilterProxyModel()
        self.filter_model.setSourceModel(self.images_model)
        self.filter_model.setFilterRole(ModelRoles.NameRole)

        self.view = view or ShotsView()
        self.view.setModel(self.filter_model)

        self.__status_map = dict[str, str]()

        self.view.shotClicked.connect(self.onShotClicked)
        self.view.shotFilterChanged.connect(self.filter_model.setFilterFixedString)

    def setProject(self, project: dict):
        self.setBusy(True)
        (
            self.db.find(self, "Shot", [["project", "is", project]], fields=ShotItem.fields())
            .then(self.onShotsFetched)
            .and_finally(lambda: self.setBusy(False))
        )

    def onShotsFetched(self, entities: list[dict]):
        self.model.setItems([ShotItem(e, self.shared_data) for e in entities])

    def onShotClicked(self, index: QtCore.QModelIndex):
        while hasattr(index.model(), "mapToSource"):
            index = index.model().mapToSource(index)

        item = self.model.itemFromIndex(index)
        self.shotClicked.emit(item.data(ItemDataRole.UserRole))
