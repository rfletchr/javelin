import logging

from qtpy import QtCore, QtGui, QtWidgets

from javelin.project import ProjectManager
from javelin.ui.controller import BaseController
from javelin.ui.database import Database
from javelin.ui.panel.shared import (
    BurninStamp,
    GenerationalItemModel,
    ImageProviderModel,
    ModelRoles,
    SharedData,
    StampListView,
)

ItemDataRole = QtCore.Qt.ItemDataRole
SelectionMode = QtWidgets.QAbstractItemView.SelectionMode
SelectionBehavior = QtWidgets.QAbstractItemView.SelectionBehavior
IndexType = QtCore.QModelIndex | QtCore.QPersistentModelIndex
FilterRole = ModelRoles.VersionNumberRole + 1
DragDropMode = QtWidgets.QAbstractItemView.DragDropMode

logger = logging.getLogger(__name__)


class TaskStamp(BurninStamp):
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)

        self.entity_label = self._make_label("secondary", "entity_label")
        self.top_layout.addWidget(self.entity_label)

        self.name_label = self._make_label("primary", "name_label")
        self.bottom_layout.addWidget(self.name_label)
        self.bottom_layout.insertStretch(1)

        self.status_label = self._make_label("secondary", "status_label")
        self.bottom_layout.addWidget(self.status_label)

    def populate(self, index: IndexType):
        image = index.data(ItemDataRole.DecorationRole)
        if image:
            self.image_widget.setPixmap(image)

        entity_name = index.data(ModelRoles.LinkedEntityNameRole)
        if entity_name:
            self.entity_label.setText(entity_name)

        task_name = index.data(ModelRoles.NameRole)
        if task_name:
            self.name_label.setText(task_name)

        status = index.data(ModelRoles.StatusRole)
        if status:
            self.status_label.setText(status)


class TasksView(QtWidgets.QWidget):
    filterChanged = QtCore.Signal(str)  # type: ignore
    taskClicked = QtCore.Signal(QtCore.QModelIndex)  # type: ignore

    def __init__(self, parent=None, compact: bool = False, icon_size: QtCore.QSize | None = None):
        super().__init__(parent=parent)
        self.filter_editor = QtWidgets.QLineEdit()
        self.filter_editor.setPlaceholderText("Filter tasks...")

        if compact:
            self.tasks_list = QtWidgets.QTreeView()
            self.tasks_list.setSelectionBehavior(SelectionBehavior.SelectRows)
            self.tasks_list.setUniformRowHeights(True)
            self.tasks_list.setIconSize(icon_size or QtCore.QSize(32, 32))
            self.tasks_list.setStyleSheet("QTreeView::item { padding: 4px 6px; }")
            self.tasks_list.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        else:
            self.tasks_list = StampListView(TaskStamp(), list_mode=False)
        self.tasks_list.setDragDropMode(DragDropMode.NoDragDrop)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_editor)
        layout.addWidget(self.tasks_list)
        self.setLayout(layout)

        self.tasks_list.clicked.connect(self.taskClicked)
        self.filter_editor.textChanged.connect(self.filterChanged)

    def setTasksModel(self, model):
        self.tasks_list.setModel(model)


_TASK_FIELDS = [
    "content",
    "entity",
    "entity.Asset.sg_asset_type",
    "entity.Asset.code",
    "entity.Shot.code",
    "entity.Shot.sg_sequence.Sequence.code",
    "entity.Shot.sg_sequence.Sequence.episode.Episode.code",
    "entity.Asset.image_blur_hash",
    "entity.Shot.image_blur_hash",
    "project.Project.tank_name",
    "sg_status_list",
]


def _build_context_fields(task: dict) -> dict:
    try:
        if task["entity"]["type"] == "Asset":
            return {
                "project": task["project.Project.tank_name"],
                "asset_type": task["entity.Asset.sg_asset_type"],
                "asset": task["entity.Asset.code"],
                "task": task["content"],
            }
        elif task["entity"]["type"] == "Shot":
            value = {
                "project": task["project.Project.tank_name"],
                "sequence": task["entity.Shot.sg_sequence.Sequence.code"],
                "shot": task["entity.Shot.code"],
                "task": task["content"],
            }
            if task["entity.Shot.sg_sequence.Sequence.episode.Episode.code"]:
                value["episode"] = task["entity.Shot.sg_sequence.Sequence.episode.Episode.code"]
        else:
            raise ValueError(f"Unknown entity type: {task['type']}")

    except Exception as e:
        logger.error("Failed to build context fields: %s", e)
        return {}

    return value


def _make_task_row(task_entity: dict, shared_data: SharedData) -> list[QtGui.QStandardItem]:
    status_name = shared_data.status_code_to_name[task_entity["sg_status_list"]]

    name_item = QtGui.QStandardItem(task_entity["content"])
    name_item.setEditable(False)
    name_item.setData(task_entity, ItemDataRole.UserRole)
    name_item.setData(task_entity["content"], ModelRoles.NameRole)
    name_item.setData(
        task_entity["entity.Asset.code"] or task_entity["entity.Shot.code"], ModelRoles.LinkedEntityNameRole
    )
    name_item.setData(status_name, ModelRoles.StatusRole)
    name_item.setData(
        task_entity["entity.Asset.image_blur_hash"] or task_entity["entity.Shot.image_blur_hash"],
        ModelRoles.BlurhashRole,
    )
    name_item.setData(task_entity["project.Project.tank_name"], ModelRoles.ProjectNameRole)
    name_item.setData(task_entity["entity"], ModelRoles.ThumbnailEntityRole)

    entity_code = task_entity["entity.Shot.code"] or task_entity["entity.Asset.code"]
    name_item.setData(f"{entity_code} - {task_entity['content']}", ModelRoles.CustomFilterRole)
    name_item.setData(_build_context_fields(task_entity), ModelRoles.ContextFieldsRole)

    status_item = QtGui.QStandardItem(status_name)
    status_item.setEditable(False)

    return [name_item, status_item]


class TasksController(BaseController):
    contextClicked = QtCore.Signal(object)  # type: ignore

    def __init__(
        self,
        project_manager: ProjectManager,
        database: Database,
        shared_data: SharedData,
        view: TasksView | None = None,
        parent=None,
        compact: bool = False,
    ):
        super().__init__(parent=parent)
        self.project_manager = project_manager
        self.database = database
        self.shared_data = shared_data

        self.model = GenerationalItemModel()

        self.image_provider = ImageProviderModel("/mnt/projects")
        self.image_provider.setSourceModel(self.model)

        self.filter_model = QtCore.QSortFilterProxyModel()
        self.filter_model.setSourceModel(self.image_provider)
        self.filter_model.setFilterRole(ModelRoles.CustomFilterRole)
        self.filter_model.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)

        self.view = view or TasksView(compact=compact)
        self.view.setTasksModel(self.filter_model)

        self.view.filterChanged.connect(self.onFilterChanged)
        self.view.taskClicked.connect(self.onTaskClicked)

    def onTaskClicked(self, index: QtCore.QModelIndex):
        while hasattr(index.model(), "mapToSource"):
            index = index.model().mapToSource(index)
        index = index.sibling(index.row(), 0)

        context_fields = index.data(ModelRoles.ContextFieldsRole)
        project_name = context_fields["project"]
        project = self.project_manager.get_project(project_name)

        context = project.context_from_fields(context_fields)
        self.contextClicked.emit(context)

    def onFilterChanged(self, text: str):
        self.filter_model.setFilterFixedString(text)

    def setEntity(self, entity: dict):
        logger.info("Set entity: %s", entity)
        self.setBusy(True)

        def on_complete():
            self.setBusy(False)
            logger.info("Entity set: %s", entity)

        (
            self.database.find(
                self,
                "Task",
                [
                    ["entity", "is", entity],
                    ["sg_status_list", "not_in", ["omt", "na"]],
                ],
                _TASK_FIELDS,
            )
            .then(self.onTasksFetched)
            .and_finally(on_complete)
        )

    def setProject(self, project: dict):
        logger.info("Set project: %s", project["tank_name"])
        self.setBusy(True)

        def on_complete():
            self.setBusy(False)
            logger.info("Project set: %s", project["tank_name"])

        (
            self.database.find(
                self,
                "Task",
                [
                    ["project", "is", project],
                    ["task_assignees", "is", self.database.user()],
                    ["sg_status_list", "not_in", ["omt", "na"]],
                ],
                _TASK_FIELDS,
            )
            .then(self.onTasksFetched)
            .and_finally(on_complete)
        )

    def onTasksFetched(self, entities: dict):
        logger.info("Tasks fetched: %d", len(entities))
        self.model.setItems([_make_task_row(row, self.shared_data) for row in entities])
        self.model.setHorizontalHeaderLabels(["Task", "Status"])
