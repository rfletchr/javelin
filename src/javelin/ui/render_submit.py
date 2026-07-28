from __future__ import annotations

import logging
import re

from qtpy import QtCore, QtGui, QtWidgets

from javelin.deadline import DeadlineJob
from javelin.deadline import submit
from javelin.ui.controller import PanelController

ItemDataRole = QtCore.Qt.ItemDataRole
CheckState = QtCore.Qt.CheckState

logger = logging.getLogger(__name__)

_FRAME_RANGE_PATTERN = re.compile(r"^(\d+)(?:-(\d+))?$")


def _is_valid_frame_range(text: str) -> bool:
    match = _FRAME_RANGE_PATTERN.match(text)
    if not match:
        return False

    start, end = match.groups()
    return end is None or int(start) <= int(end)


class RenderItemRole:
    """Custom roles stashed on each row's QStandardItem. Label, tooltip and
    checked/enabled state all live on standard Qt roles/flags - these are the only two
    the base controller needs beyond that, so items stay opaque otherwise. Payload is
    whatever a subclass's generateJobs() needs to build a DeadlineJob for the row (e.g.
    a Nuke Write node)."""

    Payload = ItemDataRole.UserRole + 1
    DependsOn = ItemDataRole.UserRole + 2  # list[QStandardItem]


class RenderSubmitView(QtWidgets.QWidget):
    """Checkable list of pending jobs, global comment/frame-range fields, and a submit
    button. Pure layout - all state lives in the controller/model."""

    submitClicked = QtCore.Signal()
    frameRangeChanged = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.job_list = QtWidgets.QListView()
        self.job_list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.comment_edit = QtWidgets.QLineEdit()
        self.frame_range_edit = QtWidgets.QLineEdit()

        form_layout = QtWidgets.QFormLayout()
        form_layout.addRow("Comment", self.comment_edit)
        form_layout.addRow("Frame Range", self.frame_range_edit)

        self.submit_button = QtWidgets.QPushButton("Submit")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.job_list, 1)
        layout.addLayout(form_layout)
        layout.addWidget(self.submit_button, 0, QtCore.Qt.AlignmentFlag.AlignRight)

        self.submit_button.clicked.connect(self.submitClicked)
        self.frame_range_edit.textChanged.connect(self.frameRangeChanged)

    def setModel(self, model: QtCore.QAbstractItemModel):
        self.job_list.setModel(model)

    def getComment(self) -> str:
        return self.comment_edit.text()

    def setComment(self, text: str):
        self.comment_edit.setText(text)

    def getFrameRange(self) -> str:
        return self.frame_range_edit.text()

    def setFrameRange(self, text: str):
        self.frame_range_edit.setText(text)

    def setBusy(self, busy: bool):
        self.setDisabled(busy)

    def setSubmitEnabled(self, enabled: bool):
        self.submit_button.setEnabled(enabled)


class RenderSubmitController(PanelController):
    submitted = QtCore.Signal(list)  # list[DeadlineJob] - as returned by submit_jobs
    submitFailed = QtCore.Signal(Exception)

    def __init__(self, view: RenderSubmitView | None = None, parent=None):
        super().__init__(parent=parent)
        self.view = view or RenderSubmitView()

        self._model = QtGui.QStandardItemModel(self)
        self.view.setModel(self._model)

        self.view.submitClicked.connect(self.onSubmitClicked)
        self.view.job_list.clicked.connect(self.onItemClicked)
        self.busyChanged.connect(self.view.setBusy)
        self.view.frameRangeChanged.connect(self.onFrameRangeChanged)
        self.onFrameRangeChanged(self.view.getFrameRange())

    def getView(self) -> RenderSubmitView:
        return self.view

    def getName(self) -> str:
        return "Render Submit"

    def model(self) -> QtGui.QStandardItemModel:
        """The model populate() should build rows into, via model().appendRow(...)."""
        return self._model

    def populate(self):
        """Clear and rebuild model() with one checkable QStandardItem per candidate
        job: label on DisplayRole, tooltip on ToolTipRole, checked/enabled state via
        setCheckState()/setEnabled(), plus RenderItemRole.Payload and, optionally,
        RenderItemRole.DependsOn (a list of the QStandardItem rows it depends on)."""
        raise NotImplementedError

    def generateJobs(self, comment: str, frame_range: str) -> list[DeadlineJob]:
        """Read the checked rows of model() (see getCheckedItems()) and build the
        DeadlineJobs to submit for them."""
        raise NotImplementedError

    def getCheckedItems(self) -> list[QtGui.QStandardItem]:
        model = self.model()
        items = []
        for row in range(model.rowCount()):
            item = model.item(row)
            if item.checkState() == CheckState.Checked:
                items.append(item)
        return items

    def onItemClicked(self, index: QtCore.QModelIndex):
        """A job that depends on a now-unchecked job can't submit correctly (its
        JobDependencies would point at nothing), so uncheck and disable it - and cascade,
        since the same applies to whatever depends on *it*. Checking a job the other way
        pulls its own dependencies back in, since it can't submit without them either.
        """
        model = self.model()
        item = model.itemFromIndex(index)
        if item is None or not item.isCheckable():
            return

        checked = item.checkState() == CheckState.Checked

        with QtCore.QSignalBlocker(model):
            if checked:
                self._enableRequired(item)
            else:
                self._disableDependents(item)

        top_left = model.index(0, 0)
        bottom_right = model.index(model.rowCount() - 1, 0)
        model.dataChanged.emit(top_left, bottom_right)

    def _enableRequired(self, item: QtGui.QStandardItem, visited: list[QtGui.QStandardItem] | None = None):
        # QStandardItem is unhashable (PySide/PyQt), so a list stands in for a visited-set.
        visited = visited if visited is not None else []
        for dep in item.data(RenderItemRole.DependsOn) or []:
            if dep in visited:
                continue
            visited.append(dep)

            dep.setEnabled(True)
            dep.setCheckState(CheckState.Checked)
            self._enableRequired(dep, visited)

    def _disableDependents(self, item: QtGui.QStandardItem, visited: list[QtGui.QStandardItem] | None = None):
        visited = visited if visited is not None else []
        for dependent in self._dependentsOf(item):
            if dependent in visited:
                continue
            visited.append(dependent)

            dependent.setCheckState(CheckState.Unchecked)
            dependent.setEnabled(False)
            self._disableDependents(dependent, visited)

    def _dependentsOf(self, item: QtGui.QStandardItem) -> list[QtGui.QStandardItem]:
        model = self.model()
        dependents = []
        for row in range(model.rowCount()):
            other = model.item(row)
            if item in (other.data(RenderItemRole.DependsOn) or []):
                dependents.append(other)
        return dependents

    def onSubmitClicked(self):
        jobs = self.generateJobs(self.view.getComment(), self.view.getFrameRange())
        if not jobs:
            return

        self.setBusy(True)
        (
            self.promise(submit, jobs)
            .then(self.submitted.emit)
            .catch(self.onSubmitFailed)
            .and_finally(lambda: self.setBusy(False))
        )

    def onSubmitFailed(self, error: Exception):
        logger.warning("Render submission failed: %s", error)
        self.submitFailed.emit(error)

    def onFrameRangeChanged(self, text: str):
        self.view.setSubmitEnabled(_is_valid_frame_range(text))
