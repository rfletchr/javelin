import typing

from qtpy import QtCore, QtGui, QtWidgets

from javelin.project import ProjectManager
from javelin.ui.controller import BaseController
from javelin.ui.database import Database
from javelin.ui.panel.shared import GenerationalItemModel, IconProviderModel, ModelRoles, get_theme_icon

SelectionMode = QtWidgets.QAbstractItemView.SelectionMode
ItemDataRole = QtCore.Qt.ItemDataRole


class Publish(typing.NamedTuple):
    name: str
    path: str
    published_file_type: str
    version_number: int
    entity: dict


_PUBLISH_FIELDS = [
    "name",
    "published_file_type.PublishedFileType.code",
    "version_number",
    "entity",
    "entity.Shot.id",
    "entity.Asset.id",
    "path",
]


def _make_publish_group_row(name: str) -> list[QtGui.QStandardItem]:
    name_item = QtGui.QStandardItem(name)
    name_item.setEditable(False)
    name_item.setData(True, ModelRoles.IsPublishGroupRole)
    name_item.setIcon(get_theme_icon("folder", QtWidgets.QStyle.StandardPixmap.SP_DirIcon))

    font = name_item.font()
    font.setBold(True)
    name_item.setFont(font)

    return [name_item, QtGui.QStandardItem(), QtGui.QStandardItem()]


def _make_publish_row(versions: list[dict]) -> list[QtGui.QStandardItem]:
    latest = versions[0]

    name_item = QtGui.QStandardItem(latest["name"])
    name_item.setEditable(False)
    name_item.setData(latest, ItemDataRole.UserRole)
    name_item.setData(versions, ModelRoles.PublishVersionsRole)

    path = latest.get("path")
    if path:
        name_item.setData(path["local_path"], ModelRoles.PathRole)

    type_item = QtGui.QStandardItem(latest["published_file_type.PublishedFileType.code"])
    type_item.setEditable(False)

    version_item = QtGui.QStandardItem(f"v{latest['version_number']}")
    version_item.setEditable(False)

    return [name_item, type_item, version_item]


def _groupPublishVersions(rows: list[dict]) -> list[list[dict]]:
    """Group a version-descending PublishedFile query by shot/asset + name + type, so within each
    group the first (and latest) entry is index 0."""
    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (
            row["entity.Shot.id"],
            row["entity.Asset.id"],
            row["name"],
            row["published_file_type.PublishedFileType.code"],
        )
        grouped.setdefault(key, []).append(row)
    return list(grouped.values())


def _groupPublishesByName(type_groups: list[list[dict]]) -> dict[tuple, list[list[dict]]]:
    """Group per-type version groups (from `_groupPublishVersions`) by shot/asset + name, so
    published file types sharing a name nest under one parent row."""
    grouped: dict[tuple, list[list[dict]]] = {}
    for versions in type_groups:
        latest = versions[0]
        name_key = (latest["entity.Shot.id"], latest["entity.Asset.id"], latest["name"])
        grouped.setdefault(name_key, []).append(versions)
    return grouped


class PublishesView(QtWidgets.QWidget):
    publishActivated = QtCore.Signal(QtCore.QModelIndex)  # type: ignore

    def __init__(self, parent=None, icon_size: QtCore.QSize | None = None):
        super().__init__(parent=parent)
        self.publishes_list = QtWidgets.QTreeView()
        self.publishes_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.publishes_list.setSelectionMode(SelectionMode.SingleSelection)
        self.publishes_list.setUniformRowHeights(True)
        self.publishes_list.setIconSize(icon_size or QtCore.QSize(32, 32))
        self.publishes_list.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.publishes_list.setAlternatingRowColors(True)
        self.publishes_list.setStyleSheet("QTreeView::item { padding: 4px 6px; }")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.publishes_list)

        self.publishes_list.activated.connect(self.publishActivated)

    def setModel(self, model):
        self.publishes_list.setModel(model)

    def expandAll(self):
        self.publishes_list.expandAll()


class PublishesController(BaseController):
    publishActivated = QtCore.Signal(object)  # Publish  # type: ignore

    def __init__(
        self, project_manager: ProjectManager, database: Database, view: PublishesView | None = None, parent=None
    ):
        super().__init__(parent=parent)
        self.database = database
        self.project_manager = project_manager

        self.view = view or PublishesView()

        self.publishes_model = GenerationalItemModel(self)
        self.publishes_model.setHorizontalHeaderLabels(["Name", "Type", "Version"])
        self.publishes_icon_provider = IconProviderModel(self)
        self.publishes_icon_provider.setSourceModel(self.publishes_model)
        self.view.setModel(self.publishes_icon_provider)

        self.view.publishActivated.connect(self.onPublishActivated)

    def onPublishActivated(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return

        name_index = index.sibling(index.row(), 0)
        if name_index.data(ModelRoles.IsPublishGroupRole):
            return

        data = name_index.data(ItemDataRole.UserRole)
        if data is None:
            return

        path = data["path"]
        self.publishActivated.emit(
            Publish(
                name=data["name"],
                path=path["local_path"],
                published_file_type=data["published_file_type.PublishedFileType.code"],
                version_number=data["version_number"],
                entity=data,
            )
        )

    def setEntity(self, entity: dict):
        self.setBusy(True)
        self.database.find(
            self,
            "PublishedFile",
            [
                ["entity", "is", entity],
                ["sg_status_list", "not_in", ["omt", "na"]],
            ],
            fields=_PUBLISH_FIELDS,
        ).then(self.onPublishesFetched).and_finally(lambda: self.setBusy(False))

    def onPublishesFetched(self, publishes: list[dict]):
        by_name = _groupPublishesByName(_groupPublishVersions(publishes))
        self.publishes_model.setRowCount(0)

        for type_groups in by_name.values():
            group_row = _make_publish_group_row(type_groups[0][0]["name"])
            for versions in type_groups:
                group_row[0].appendRow(_make_publish_row(versions))
            self.publishes_model.appendRow(group_row)

        self.view.expandAll()
