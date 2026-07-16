from __future__ import annotations

import logging
import os
import shutil
import typing

from qtpy import QtCore, QtGui, QtWidgets

from javelin.project import ContextClasses, Project, Workfile, WorkfileDefinition
from javelin.ui.controller import BaseController
from javelin.ui.panel.shared import GenerationalItemModel, IconProviderModel, ModelRoles, get_theme_icon

ItemDataRole = QtCore.Qt.ItemDataRole

_GroupKey = typing.TypeVar("_GroupKey")

logger = logging.getLogger(__name__)


def _group_workfiles(
    workfiles: typing.Iterable[Workfile],
    key: typing.Callable[[Workfile], _GroupKey],
) -> dict[_GroupKey, list[Workfile]]:
    """Group workfiles by `key`, each group sorted latest (highest version) first."""
    grouped: dict[_GroupKey, list[Workfile]] = {}
    for workfile in workfiles:
        grouped.setdefault(key(workfile), []).append(workfile)
    for group in grouped.values():
        group.sort(key=lambda wf: wf.version, reverse=True)
    return grouped


def _make_workfile_row(workfile: Workfile) -> list[QtGui.QStandardItem]:
    name_item = QtGui.QStandardItem(workfile.name)
    name_item.setEditable(False)
    name_item.setData(workfile, ItemDataRole.UserRole)
    name_item.setData(workfile.path, ModelRoles.PathRole)

    version_item = QtGui.QStandardItem(f"v{workfile.version:03d}")
    version_item.setEditable(False)

    return [name_item, version_item]


class WorkfilesView(QtWidgets.QWidget):
    workfileActivated = QtCore.Signal(QtCore.QModelIndex)  # type: ignore
    newFileTriggered = QtCore.Signal(object, str)  # WorkfileDefinition, template name  # type: ignore

    def __init__(self, parent=None, icon_size: QtCore.QSize | None = None):
        super().__init__(parent=parent)
        self.new_file_button = QtWidgets.QToolButton()
        self.new_file_button.setText("New File")
        self.new_file_button.setIcon(get_theme_icon("document-new", QtWidgets.QStyle.StandardPixmap.SP_FileIcon))
        self.new_file_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.new_file_button.setEnabled(False)

        self.new_file_menu = QtWidgets.QMenu(self.new_file_button)
        self.new_file_button.setMenu(self.new_file_menu)

        self.workfiles_tree = QtWidgets.QTreeView()
        self.workfiles_tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.workfiles_tree.setUniformRowHeights(True)
        self.workfiles_tree.setExpandsOnDoubleClick(False)
        self.workfiles_tree.setIconSize(icon_size or QtCore.QSize(32, 32))
        self.workfiles_tree.setStyleSheet("QTreeView::item { padding: 4px 6px; }")
        self.workfiles_tree.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.workfiles_tree.setAlternatingRowColors(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.new_file_button, 0)
        layout.addWidget(self.workfiles_tree, 1)

        self.workfiles_tree.activated.connect(self.workfileActivated)

    def setModel(self, model):
        self.workfiles_tree.setModel(model)

    def setNewFileDefinitions(self, definitions: typing.Sequence[WorkfileDefinition]):
        self.new_file_menu.clear()

        has_templates = False
        for definition in definitions:
            if not definition.template_files:
                continue
            has_templates = True

            submenu = self.new_file_menu.addMenu(definition.label)
            for template_name in definition.template_files:
                action = submenu.addAction(template_name)
                action.triggered.connect(
                    lambda _checked=False, d=definition, t=template_name: self.newFileTriggered.emit(d, t)
                )

        self.new_file_button.setEnabled(has_templates)


class WorkfilesController(BaseController):
    workfileActivated = QtCore.Signal(object)  # Workfile  # type: ignore
    workfileCreated = QtCore.Signal(object)  # Workfile  # type: ignore

    def __init__(
        self,
        project: Project,
        view: WorkfilesView | None = None,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.project = project

        self.model = GenerationalItemModel(self)
        self.icon_provider = IconProviderModel(self)
        self.icon_provider.setSourceModel(self.model)

        self.view = view or WorkfilesView()
        self.view.setModel(self.icon_provider)

        self.__context: ContextClasses | None = None

        self.view.workfileActivated.connect(self.onWorkfileActivated)
        self.view.newFileTriggered.connect(self.onNewFileTriggered)

    def setContext(self, context: ContextClasses):
        self.__context = context
        self.view.setNewFileDefinitions(context.definition.workfiles)
        self.refresh()

    def clear(self):
        self.__context = None
        self.refresh()

    def refresh(self):
        rows: list[list[QtGui.QStandardItem]] = []

        if self.__context is not None:
            self.setBusy(True)
            try:
                all_workfiles: list[Workfile] = []
                for definition in self.__context.definition.workfiles:
                    all_workfiles.extend(self.project.list_workfiles(self.__context, definition))

                groups = _group_workfiles(all_workfiles, key=lambda wf: (wf.name, os.path.splitext(wf.path)[1].lower()))

                for versions in groups.values():
                    latest, *older = versions
                    row = _make_workfile_row(latest)
                    for workfile in older:
                        row[0].appendRow(_make_workfile_row(workfile))
                    rows.append(row)
            finally:
                self.setBusy(False)

        self.model.setItems(rows)
        self.model.setHorizontalHeaderLabels(["Name", "Version"])

    def onWorkfileActivated(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return

        workfile = index.sibling(index.row(), 0).data(ItemDataRole.UserRole)
        if workfile is not None:
            self.workfileActivated.emit(workfile)

    def onNewFileTriggered(self, definition: WorkfileDefinition, template_name: str):
        if self.__context is None:
            return

        self.setBusy(True)
        try:
            workfile = self._createWorkfile(self.project, self.__context, definition, template_name)
        finally:
            self.setBusy(False)

        self.refresh()
        self.workfileCreated.emit(workfile)

    def _createWorkfile(
        self,
        project: Project,
        context: ContextClasses,
        definition: WorkfileDefinition,
        template_name: str,
    ) -> Workfile:
        context_fields = context.fields()
        name = definition.name_pattern.format(**context_fields)

        existing = project.list_workfiles(context, definition)
        by_name = _group_workfiles(existing, key=lambda wf: wf.name)
        version = by_name[name][0].version + 1 if name in by_name else 1

        target_path = definition.template.format(name=name, version=version, **context_fields)
        source_path = project.resolve_template_relpath(definition.template_files[template_name])

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(source_path, target_path)

        return Workfile(name=name, version=version, path=target_path, context=context)
