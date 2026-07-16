from __future__ import annotations

import logging

from qtpy import QtCore, QtGui, QtWidgets

from javelin.ui.controller import BaseController, PanelController
from javelin.ui.database import Database

logger = logging.getLogger(__name__)

ENTITY_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
TREE_INDEX_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2
TASKS_LOADED_ROLE = QtCore.Qt.ItemDataRole.UserRole + 3

# Synthetic node types: not real ShotGrid entities, but they flow through the
# same QStandardItem / activation machinery as everything else.
_SHOTS_FOLDER = "_ShotsFolder"
_ASSETS_FOLDER = "_AssetsFolder"
_ASSET_TYPE_GROUP = "_AssetTypeGroup"
_MY_TASKS_FOLDER = "_MyTasksFolder"
_ROOT = "_Root"

_NAME_FIELDS = ("code", "content", "name", "tank_name")


# ---------------------------------------------------------------------------
# Project picker: a combo box above the browser, split out so project
# selection isn't just another level you click through.
# ---------------------------------------------------------------------------


class ProjectPickerView(QtWidgets.QWidget):
    """Pure layout: a combo box backed by an item model, emitting the
    selected row as a QModelIndex whenever the selection changes."""

    currentIndexChanged = QtCore.Signal(QtCore.QModelIndex)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._combo = QtWidgets.QComboBox()
        self._combo.currentIndexChanged.connect(self._onCurrentIndexChanged)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._combo)
        self.setLayout(layout)

    def setModel(self, model: QtGui.QStandardItemModel):
        self._combo.setModel(model)

    def setBusy(self, busy: bool):
        self.setDisabled(busy)

    def _onCurrentIndexChanged(self, row: int):
        model = self._combo.model()
        if model is None or row < 0:
            return
        self.currentIndexChanged.emit(model.index(row, 0))


class ProjectPickerController(BaseController):
    """Fetches the project list once and emits the chosen entity whenever
    the combo box selection changes - including the initial auto-select
    that happens as soon as the list arrives."""

    projectChanged = QtCore.Signal(object)  # dict (SG Project entity)

    def __init__(self, database: Database, view: ProjectPickerView | None = None, parent=None):
        super().__init__(parent=parent)
        self.database = database
        self.view = view or ProjectPickerView()
        self.model = QtGui.QStandardItemModel(self)

        self.view.setModel(self.model)
        self.view.currentIndexChanged.connect(self._onCurrentIndexChanged)
        self.busyChanged.connect(self.view.setBusy)

    def getView(self) -> QtWidgets.QWidget:
        return self.view

    def populate(self):
        self.setBusy(True)
        (
            self.database.find(self, "Project", [], ["name", "tank_name"])
            .then(self._onProjectsLoaded)
            .and_finally(lambda: self.setBusy(False))
        )

    def _onProjectsLoaded(self, projects: list[dict]):
        self.model.clear()
        for project in projects:
            self.model.appendRow(_entity_item(project))

    def _onCurrentIndexChanged(self, index: QtCore.QModelIndex):
        entity = index.data(ENTITY_ROLE)
        if entity is not None:
            self.projectChanged.emit(entity)


# ---------------------------------------------------------------------------
# Browser: a breadcrumb strip plus a classic list view, navigating a tree
# that's built once per project (see _ProjectTreeBuilder below) instead of
# being re-queried at every level.
# ---------------------------------------------------------------------------


class ExplorerView(QtWidgets.QWidget):
    """Project picker + path bar + list, stacked: pure layout, no ShotGrid
    knowledge. Forwards item activation (double-click or Enter) in the list,
    and single clicks in the breadcrumb strip, upward as QModelIndex
    signals."""

    activated = QtCore.Signal(QtCore.QModelIndex)
    crumbClicked = QtCore.Signal(QtCore.QModelIndex)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._project_picker_view = ProjectPickerView()

        self._breadcrumb_view = QtWidgets.QListView()
        self._breadcrumb_view.setViewMode(QtWidgets.QListView.ViewMode.ListMode)
        self._breadcrumb_view.setFlow(QtWidgets.QListView.Flow.LeftToRight)
        self._breadcrumb_view.setWrapping(False)
        self._breadcrumb_view.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self._breadcrumb_view.setIconSize(QtCore.QSize(16, 16))
        self._breadcrumb_view.setSpacing(2)
        self._breadcrumb_view.setFixedHeight(28)
        self._breadcrumb_view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._breadcrumb_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self._breadcrumb_view.clicked.connect(self.crumbClicked)

        self._list_view = QtWidgets.QListView()
        self._list_view.setViewMode(QtWidgets.QListView.ViewMode.ListMode)
        self._list_view.setFlow(QtWidgets.QListView.Flow.TopToBottom)
        self._list_view.setWrapping(False)
        self._list_view.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self._list_view.setMovement(QtWidgets.QListView.Movement.Static)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setWordWrap(False)
        self._list_view.setIconSize(QtCore.QSize(24, 24))
        self._list_view.setSpacing(2)
        self._list_view.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        self._list_view.activated.connect(self.activated)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._project_picker_view)
        layout.addWidget(self._breadcrumb_view)
        layout.addWidget(self._list_view)
        self.setLayout(layout)

    def getProjectPickerView(self) -> ProjectPickerView:
        return self._project_picker_view

    def setModel(self, model: QtGui.QStandardItemModel):
        self._list_view.setModel(model)

    def setBreadcrumbModel(self, model: QtGui.QStandardItemModel):
        self._breadcrumb_view.setModel(model)

    def setRootIndex(self, index: QtCore.QModelIndex):
        self._list_view.setRootIndex(index)

    def setBusy(self, busy: bool):
        self.setDisabled(busy)


class ExplorerController(PanelController):
    """Drives the browser. Picking a project (via the injected
    ProjectPickerController) fires shallow Shot/Sequence/Asset queries (no
    dot-notation joins, which ShotGrid handles badly); a _ProjectTreeBuilder
    turns those into a real parent/child QStandardItem tree held in
    self.model for the rest of that project's session. Browsing is then
    just moving the list view's root index around that tree. Shot/Asset/My
    Tasks nodes additionally fetch their own Task children lazily, on first
    visit, cached from then on via TASKS_LOADED_ROLE on the item itself.
    Task is the only true leaf: activating one emits taskActivated instead
    of drilling further.

    The breadcrumb strip's model is a separate, flat trail: each crumb keeps
    a QPersistentModelIndex (TREE_INDEX_ROLE) pointing back into self.model,
    so clicking an earlier crumb trims the trail and jumps setRootIndex back
    to that node.
    """

    taskActivated = QtCore.Signal(object)  # dict (SG Task entity)

    def __init__(self, database: Database, view: ExplorerView | None = None, parent=None):
        super().__init__(parent=parent)
        self.database = database
        self.view = view or ExplorerView()
        self.model = QtGui.QStandardItemModel(self)
        self.breadcrumb_model = QtGui.QStandardItemModel(self)

        self._current_project: dict | None = None

        self.project_picker_controller = ProjectPickerController(
            database, view=self.view.getProjectPickerView()
        )
        self.project_picker_controller.projectChanged.connect(self._onProjectChanged)

        self.view.setModel(self.model)
        self.view.setBreadcrumbModel(self.breadcrumb_model)
        self.view.activated.connect(self._onActivated)
        self.view.crumbClicked.connect(self._onCrumbClicked)
        self.busyChanged.connect(self.view.setBusy)

    def getView(self) -> QtWidgets.QWidget:
        return self.view

    def getName(self) -> str:
        return "Explorer"

    def populate(self):
        self.project_picker_controller.populate()

    # -- project selection ----------------------------------------------------

    def _onProjectChanged(self, project: dict):
        """Builds the Shot/Asset skeleton from three shallow queries (no
        dot-notation joins - those are what made the old single Task fetch
        slow). Sequence's own "episode" link and Shot's own "sg_sequence"
        link each come back with the linked entity's name pre-embedded by
        ShotGrid at no extra cost, so no joins are needed to label them.
        Tasks aren't fetched here at all - see _enterTaskContainer."""
        self._current_project = project
        self.setBusy(True)
        (
            self.database.find(self, "Shot", [["project", "is", _ref(project)]], ["code", "sg_sequence"])
            .then(lambda shots: self._onShotsLoaded(project, shots))
            .and_finally(lambda: self.setBusy(False))
        )

    def _onShotsLoaded(self, project: dict, shots: list[dict]):
        self.setBusy(True)
        (
            self.database.find(self, "Sequence", [["project", "is", _ref(project)]], ["code", "episode"])
            .then(lambda sequences: self._onSequencesLoaded(project, shots, sequences))
            .and_finally(lambda: self.setBusy(False))
        )

    def _onSequencesLoaded(self, project: dict, shots: list[dict], sequences: list[dict]):
        self.setBusy(True)
        (
            self.database.find(self, "Asset", [["project", "is", _ref(project)]], ["code", "sg_asset_type"])
            .then(lambda assets: self._onAssetsLoaded(shots, sequences, assets))
            .and_finally(lambda: self.setBusy(False))
        )

    def _onAssetsLoaded(self, shots: list[dict], sequences: list[dict], assets: list[dict]):
        builder = _ProjectTreeBuilder(sequences)
        for shot in shots:
            builder.addShot(shot)
        for asset in assets:
            builder.addAsset(asset)
        self._setItems(builder.build())
        self._resetBreadcrumb()

    # -- activation dispatch ------------------------------------------------

    def _onActivated(self, index: QtCore.QModelIndex):
        """Double-click/Enter in the list: drill in, appending a crumb.
        Shot/Asset/My Tasks nodes fetch (and cache, via TASKS_LOADED_ROLE
        on the item itself) their Task children on first visit."""
        entity = index.data(ENTITY_ROLE)
        if entity is None:
            return

        if entity["type"] == "Task":
            self.taskActivated.emit(entity)
        elif entity["type"] in ("Shot", "Asset"):
            self._enterTaskContainer(index, [["entity", "is", _ref(entity)]])
        elif entity["type"] == _MY_TASKS_FOLDER:
            self._enterTaskContainer(index, self._myTasksFilters())
        else:
            self._pushCrumb(index)
            self.view.setRootIndex(index)

    def _enterTaskContainer(self, index: QtCore.QModelIndex, filters: list):
        item = self.model.itemFromIndex(index)
        if item.data(TASKS_LOADED_ROLE):
            self._pushCrumb(index)
            self.view.setRootIndex(index)
            return

        self.setBusy(True)
        (
            self.database.find(self, "Task", filters, ["content"])
            .then(lambda tasks: self._onContainerTasksLoaded(index, item, tasks))
            .and_finally(lambda: self.setBusy(False))
        )

    def _onContainerTasksLoaded(self, index: QtCore.QModelIndex, item: QtGui.QStandardItem, tasks: list[dict]):
        for task in tasks:
            item.appendRow(_entity_item({"type": "Task", "id": task["id"], "content": task.get("content")}))
        item.setData(True, TASKS_LOADED_ROLE)
        self._pushCrumb(index)
        self.view.setRootIndex(index)

    def _myTasksFilters(self) -> list:
        return [
            ["project", "is", _ref(self._current_project)],
            ["task_assignees", "is", self.database.user()],
        ]

    def _onCrumbClicked(self, crumb_index: QtCore.QModelIndex):
        """Click on a breadcrumb: jump back, trimming crumbs after it."""
        self.breadcrumb_model.removeRows(
            crumb_index.row() + 1, self.breadcrumb_model.rowCount() - crumb_index.row() - 1
        )

        persistent = crumb_index.data(TREE_INDEX_ROLE)
        if persistent is not None and persistent.isValid():
            self.view.setRootIndex(QtCore.QModelIndex(persistent))
        else:
            self.view.setRootIndex(QtCore.QModelIndex())

    def _pushCrumb(self, index: QtCore.QModelIndex):
        item = _entity_item(index.data(ENTITY_ROLE))
        item.setData(QtCore.QPersistentModelIndex(index), TREE_INDEX_ROLE)
        self.breadcrumb_model.appendRow(item)

    def _resetBreadcrumb(self):
        self.breadcrumb_model.clear()
        self.breadcrumb_model.appendRow(_root_crumb_item())

    # -- shared plumbing ------------------------------------------------------

    def _setItems(self, items: list[QtGui.QStandardItem]):
        self.model.clear()
        for item in items:
            self.model.appendRow(item)


# ---------------------------------------------------------------------------
# Shot/Sequence/Asset rows (shallow queries, no dot-notation joins) -> the
# nested tree the browser drills through. Task children are deliberately
# not part of this: see ExplorerController._enterTaskContainer.
# ---------------------------------------------------------------------------


class _ProjectTreeBuilder:
    """Builds the Episode/Sequence/Shot and asset-type/Asset trees from Shot
    and Asset rows fetched with only shallow, single-hop link fields - cheap
    for ShotGrid, unlike deep dot-notation joins. A Shot's own "sg_sequence"
    link and a Sequence's own "episode" link each come back from the API
    with the linked entity's name pre-embedded at no extra query cost, so a
    small Sequence-id -> row lookup is enough to also resolve episodes
    without ever querying Episode directly."""

    def __init__(self, sequences: list[dict]):
        self._sequences_by_id = {sequence["id"]: sequence for sequence in sequences}
        self._is_episodic = False

        self.shots_root = _folder_item(_SHOTS_FOLDER, "Shots")
        self.assets_root = _folder_item(_ASSETS_FOLDER, "Assets")
        self.my_tasks = _folder_item(_MY_TASKS_FOLDER, "My Tasks")

        self._episode_items: dict = {}
        self._sequence_items: dict = {}
        self._asset_type_items: dict = {}

    def addShot(self, shot: dict):
        item = _entity_item({"type": "Shot", "id": shot["id"], "code": shot.get("code")})
        self._sequenceItem(shot.get("sg_sequence")).appendRow(item)

    def addAsset(self, asset: dict):
        item = _entity_item({"type": "Asset", "id": asset["id"], "code": asset.get("code")})
        self._assetTypeItem(asset.get("sg_asset_type")).appendRow(item)

    def build(self) -> list[QtGui.QStandardItem]:
        self.shots_root.setText("Episodes" if self._is_episodic else "Shots")
        return [self.my_tasks, self.shots_root, self.assets_root]

    def _sequenceItem(self, sequence_link: dict | None) -> QtGui.QStandardItem:
        key = sequence_link["id"] if sequence_link else "_none"
        if key in self._sequence_items:
            return self._sequence_items[key]

        if sequence_link is None:
            item = _entity_item({"type": "Sequence", "id": None, "label": "(No Sequence)"})
            self.shots_root.appendRow(item)
            self._sequence_items[key] = item
            return item

        sequence = self._sequences_by_id.get(key)
        code = sequence["code"] if sequence else sequence_link.get("name")
        item = _entity_item({"type": "Sequence", "id": key, "code": code})

        episode = sequence.get("episode") if sequence else None
        if episode:
            self._is_episodic = True
            self._episodeItem(episode).appendRow(item)
        else:
            self.shots_root.appendRow(item)

        self._sequence_items[key] = item
        return item

    def _episodeItem(self, episode: dict) -> QtGui.QStandardItem:
        if episode["id"] not in self._episode_items:
            item = _entity_item({"type": "Episode", "id": episode["id"], "code": episode.get("name")})
            self.shots_root.appendRow(item)
            self._episode_items[episode["id"]] = item
        return self._episode_items[episode["id"]]

    def _assetTypeItem(self, asset_type: str | None) -> QtGui.QStandardItem:
        asset_type = asset_type or "(No Type)"
        if asset_type not in self._asset_type_items:
            item = _asset_type_item(asset_type)
            self.assets_root.appendRow(item)
            self._asset_type_items[asset_type] = item
        return self._asset_type_items[asset_type]


# -- shared item/icon helpers -------------------------------------------------


def _ref(entity: dict) -> dict:
    return {"type": entity["type"], "id": entity["id"]}


def _display_name(entity: dict) -> str:
    for field in _NAME_FIELDS:
        if entity.get(field):
            return entity[field]
    return f"{entity['type']} {entity.get('id', '?')}"


def _icon(entity_type: str) -> QtGui.QIcon:
    style = QtWidgets.QApplication.style()
    if entity_type == "Task":
        standard_pixmap = QtWidgets.QStyle.StandardPixmap.SP_FileIcon
    elif entity_type == _ROOT:
        standard_pixmap = QtWidgets.QStyle.StandardPixmap.SP_DirHomeIcon
    else:
        standard_pixmap = QtWidgets.QStyle.StandardPixmap.SP_DirIcon
    return style.standardIcon(standard_pixmap)


def _entity_item(entity: dict) -> QtGui.QStandardItem:
    """Builds a fresh QStandardItem from an entity dict - used for the tree,
    the project combo box, and the breadcrumb strip alike, always as a new
    item. Synthetic nodes (folders, root) carry an explicit 'label' since
    they have no SG name field to fall back on - an empty label means
    icon-only, not "derive one"."""
    label = entity["label"] if "label" in entity else _display_name(entity)
    item = QtGui.QStandardItem(_icon(entity["type"]), label)
    item.setEditable(False)
    item.setData(entity, ENTITY_ROLE)
    return item


def _folder_item(folder_type: str, label: str) -> QtGui.QStandardItem:
    return _entity_item({"type": folder_type, "label": label})


def _asset_type_item(asset_type: str) -> QtGui.QStandardItem:
    return _entity_item({"type": _ASSET_TYPE_GROUP, "asset_type": asset_type, "label": asset_type})


def _root_crumb_item() -> QtGui.QStandardItem:
    item = _entity_item({"type": _ROOT, "label": "Home"})
    item.setToolTip("Back to top of project")
    return item


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Launching Explorer test...")

    app = QtWidgets.QApplication([])
    db = Database()
    controller = ExplorerController(db)
    controller.populate()
    controller.view.show()
    app.exec()
