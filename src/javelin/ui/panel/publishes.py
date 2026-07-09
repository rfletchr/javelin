import typing

from qtpy import QtCore, QtGui, QtWidgets

from javelin.project import ProjectManager
from javelin.ui.controller import BaseController
from javelin.ui.database import Database
from javelin.ui.panel.shared import (
    GenerationalItemModel,
    IconProviderModel,
    IconWidget,
    IndexType,
    ModelRoles,
    StampTreeView,
    StampWidget,
)

SelectionMode = QtWidgets.QAbstractItemView.SelectionMode
ItemDataRole = QtCore.Qt.ItemDataRole


class Publish(typing.NamedTuple):
    name: str
    path: str
    published_file_type: str
    version_number: int
    entity: dict


class PublishStamp(StampWidget):
    """Stacks a publish's fields as text rows instead of the image + top/bottom burnin layout."""

    _SIZE_HINT = QtCore.QSize(186, 72)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        self.name_label = self._make_row_label("primary")
        self.type_label = self._make_row_label("secondary")
        self.version_label = self._make_row_label("secondary")

        text_layout = QtWidgets.QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.type_label)
        text_layout.addWidget(self.version_label)
        text_layout.addStretch(1)

        self.icon_widget = IconWidget()
        self.icon_widget.setObjectName("icon_widget")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.icon_widget, 0)

        self.setStyleSheet(
            """
            PublishStamp {
                background-color: rgba(24, 24, 24, 255);
            }
            PublishStamp QLabel[stampRole="primary"] {
                font-weight: 600;
                color: rgba(255, 255, 255, 0.9);
            }
            PublishStamp QLabel[stampRole="secondary"] {
                font-size: 12px;
                font-weight: 300;
                color: rgba(255, 255, 255, 0.7);
            }
            """
        )

    def _make_row_label(self, role: typing.Literal["primary", "secondary"]) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setProperty("stampRole", role)
        return label

    def populate(self, index: IndexType):
        name = index.data(ModelRoles.PublishNameRole)
        if name:
            self.name_label.setText(name)

        type_name = index.data(ModelRoles.PublishedFileTypeNameRole)
        if type_name:
            self.type_label.setText(type_name)

        version = index.data(ModelRoles.VersionNumberRole)
        if version is not None:
            self.version_label.setText(f"v{version}")

        icon = index.data(ItemDataRole.DecorationRole)
        if icon:
            self.icon_widget.setIcon(icon)

    def sizeHint(self, /) -> QtCore.QSize:
        return self._SIZE_HINT


class PublishItem(QtGui.QStandardItem):
    @staticmethod
    def fields() -> list[str]:
        return [
            "name",
            "published_file_type.PublishedFileType.code",
            "version_number",
            "entity",
            "entity.Shot.id",
            "entity.Asset.id",
            "path",
        ]

    def __init__(self, versions: list[dict]):
        super().__init__()
        self.setEditable(False)

        latest = versions[0]
        self.setData(latest, ItemDataRole.UserRole)
        self.setData(latest["name"], ModelRoles.PublishNameRole)
        self.setData(latest["published_file_type.PublishedFileType.code"], ModelRoles.PublishedFileTypeNameRole)
        self.setData(latest["version_number"], ModelRoles.VersionNumberRole)
        self.setData(versions, ModelRoles.PublishVersionsRole)

        path = latest.get("path")
        if path:
            self.setData(path["local_path"], ModelRoles.PathRole)


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


class PublishesView(QtWidgets.QWidget):
    publishActivated = QtCore.Signal(QtCore.QModelIndex)  # type: ignore

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.publishes_list = StampTreeView(PublishStamp(), empty_text="click a shot...")
        self.publishes_list.setIconSize(QtCore.QSize(64, 64))
        self.publishes_list.setSelectionMode(SelectionMode.SingleSelection)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.publishes_list)

        self.publishes_list.activated.connect(self.publishActivated)

    def setModel(self, model):
        self.publishes_list.setModel(model)


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
        self.publishes_icon_provider = IconProviderModel(self)
        self.publishes_icon_provider.setSourceModel(self.publishes_model)
        self.view.setModel(self.publishes_icon_provider)

        self.view.publishActivated.connect(self.onPublishActivated)

    def onPublishActivated(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return

        data = index.data(ItemDataRole.UserRole)
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
            fields=PublishItem.fields(),
        ).then(self.onPublishesFetched).and_finally(lambda: self.setBusy(False))

    def onPublishesFetched(self, publishes: list[dict]):
        grouped = _groupPublishVersions(publishes)
        self.publishes_model.setRowCount(0)

        for versions in grouped:
            self.publishes_model.appendRow(PublishItem(versions))
