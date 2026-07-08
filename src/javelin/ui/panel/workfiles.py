from __future__ import annotations

import logging
import os
import shutil
import typing

from qtpy import QtCore, QtGui, QtWidgets

from javelin.project import ContextClasses, Project, ProjectManager, Workfile, WorkfileDefinition
from javelin.ui.controller import BaseController
from javelin.ui.panel.shared import (
    GenerationalItemModel,
    IconProviderModel,
    IconWidget,
    IndexType,
    ModelRoles,
    StampTreeView,
    StampWidget,
    get_theme_icon,
)

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


class WorkfileStamp(StampWidget):
    _SIZE_HINT = QtCore.QSize(240, 32)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)

        self.icon_widget = IconWidget()
        self.icon_widget.setObjectName("icon_widget")

        self.name_label = QtWidgets.QLabel()
        self.name_label.setProperty("stampRole", "primary")

        self.version_label = QtWidgets.QLabel()
        self.version_label.setProperty("stampRole", "secondary")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)
        layout.addWidget(self.icon_widget, 0)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.version_label, 0)

        self.setStyleSheet(
            """
            WorkfileStamp {
                background-color: rgba(24, 24, 24, 255);
            }
            WorkfileStamp QLabel[stampRole="primary"] {
                font-weight: 600;
                color: rgba(255, 255, 255, 0.9);
            }
            WorkfileStamp QLabel[stampRole="secondary"] {
                font-size: 12px;
                font-weight: 300;
                color: rgba(255, 255, 255, 0.7);
            }
            """
        )

    def populate(self, index: IndexType):
        name = index.data(ModelRoles.NameRole)
        if name:
            self.name_label.setText(name)

        version = index.data(ModelRoles.VersionNumberRole)
        if version is not None:
            self.version_label.setText(f"v{version:03d}")

        icon = index.data(ItemDataRole.DecorationRole)
        if icon:
            self.icon_widget.setIcon(icon)

    def sizeHint(self, /) -> QtCore.QSize:
        return self._SIZE_HINT


class WorkfileItem(QtGui.QStandardItem):
    def __init__(self, workfile: Workfile):
        super().__init__()
        self.setEditable(False)
        self.setData(workfile, ItemDataRole.UserRole)
        self.setData(workfile.name, ModelRoles.NameRole)
        self.setData(workfile.version, ModelRoles.VersionNumberRole)
        self.setData(workfile.path, ModelRoles.PathRole)


class WorkfilesView(QtWidgets.QWidget):
    workfileActivated = QtCore.Signal(QtCore.QModelIndex)  # type: ignore
    newFileTriggered = QtCore.Signal(object, str)  # WorkfileDefinition, template name  # type: ignore

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.new_file_button = QtWidgets.QToolButton()
        self.new_file_button.setText("New File")
        self.new_file_button.setIcon(get_theme_icon("document-new", QtWidgets.QStyle.StandardPixmap.SP_FileIcon))
        self.new_file_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.new_file_button.setEnabled(False)

        self.new_file_menu = QtWidgets.QMenu(self.new_file_button)
        self.new_file_button.setMenu(self.new_file_menu)

        self.workfiles_tree = StampTreeView(WorkfileStamp(), empty_text="no context set...")
        self.workfiles_tree.setHeaderHidden(True)
        self.workfiles_tree.setUniformRowHeights(True)
        self.workfiles_tree.setExpandsOnDoubleClick(False)

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
        project_manager: ProjectManager,
        view: WorkfilesView | None = None,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.project_manager = project_manager

        self.model = GenerationalItemModel(self)
        self.icon_provider = IconProviderModel(self)
        self.icon_provider.setSourceModel(self.model)

        self.view = view or WorkfilesView()
        self.view.setModel(self.icon_provider)

        self.__project: Project | None = None
        self.__context: ContextClasses | None = None

        self.view.workfileActivated.connect(self.onWorkfileActivated)
        self.view.newFileTriggered.connect(self.onNewFileTriggered)

    def setContext(self, context: ContextClasses):
        self.__context = context
        self.__project = self.project_manager.get_project(context.project)

        self.view.setNewFileDefinitions(context.definition.workfiles)
        self.refresh()

    def clear(self):
        self.__project = None
        self.__context = None
        self.refresh()

    def refresh(self):
        if self.__project is None or self.__context is None:
            self.model.setItems([])
            return

        self.setBusy(True)
        try:
            all_workfiles: list[Workfile] = []
            for definition in self.__context.definition.workfiles:
                all_workfiles.extend(self.__project.list_workfiles(self.__context, definition))

            groups = _group_workfiles(all_workfiles, key=lambda wf: (wf.name, os.path.splitext(wf.path)[1].lower()))

            rows = []
            for versions in groups.values():
                latest, *older = versions
                root_item = WorkfileItem(latest)
                for workfile in older:
                    root_item.appendRow(WorkfileItem(workfile))
                rows.append(root_item)

            self.model.setItems(rows)
        finally:
            self.setBusy(False)

    def onWorkfileActivated(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return

        workfile = index.data(ItemDataRole.UserRole)
        if workfile is not None:
            self.workfileActivated.emit(workfile)

    def onNewFileTriggered(self, definition: WorkfileDefinition, template_name: str):
        if self.__project is None or self.__context is None:
            return

        self.setBusy(True)
        try:
            workfile = self._createWorkfile(self.__project, self.__context, definition, template_name)
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
