from __future__ import annotations

import typing
import logging

import fileseq
import nuke
from qtpy import QtCore, QtWidgets

from javelin.project import Workfile
from javelin.ui.panel.publishes import Publish

logger = logging.getLogger(__name__)

_RENDER_PUBLISH_TYPES = {"Render", "Plate"}
_REFERENCE_PUBLISH_TYPES = {"Review", "Reference"}


class NukeController(QtCore.QObject):
    """Reacts to panel events inside a Nuke session: opening workfiles and importing publishes."""

    @QtCore.Slot(object)
    def openWorkfile(self, workfile: Workfile):
        if not _confirm_discard_current_script():
            return
        nuke.scriptClose()
        nuke.scriptOpen(workfile.path)

    @QtCore.Slot(object)
    def importFile(self, publish: Publish):
        if not publish.path:
            logger.warning("Publish %r has no local path, skipping import.", publish.name)
            return

        if publish.published_file_type in _RENDER_PUBLISH_TYPES:
            _import_render(publish)
        elif publish.published_file_type in _REFERENCE_PUBLISH_TYPES:
            _import_reference(publish)
        else:
            QtWidgets.QMessageBox.information(
                None,
                "Javelin",
                f"Publishes of type '{publish.published_file_type}' aren't supported yet.",
            )


def _import_render(publish: Publish):
    # Same as _import_reference for now; kept separate since renders will need
    # colorspace/format handling that reference footage won't.
    _create_read_node(publish)


def _import_reference(publish: Publish):
    _create_read_node(publish)


def _create_read_node(publish: Publish):
    node = nuke.createNode("Read", inpanel=False)
    file_knob = typing.cast(nuke.File_Knob, node["file"])
    file_knob.fromUserText(publish.path)
    _apply_frame_range(node, publish.path)
    node["label"].setValue(f"{publish.name} (v{publish.version_number:03d})")


def _confirm_discard_current_script() -> bool:
    """True if it's safe to blow away the current script: nothing to lose, the
    user chose to discard changes, or the changes were saved successfully."""
    if not nuke.root().modified():
        return True

    answer = QtWidgets.QMessageBox.question(
        None,
        "Javelin",
        "The current script has unsaved changes. Save before opening the new file?",
        QtWidgets.QMessageBox.StandardButton.Yes
        | QtWidgets.QMessageBox.StandardButton.No
        | QtWidgets.QMessageBox.StandardButton.Cancel,
    )
    if answer == QtWidgets.QMessageBox.StandardButton.Cancel:
        return False
    if answer == QtWidgets.QMessageBox.StandardButton.No:
        return True

    return _save_current_script()


def _save_current_script() -> bool:
    try:
        if nuke.root().name():
            nuke.scriptSave()
        else:
            # Never saved: scriptSaveAs() with no path pops Nuke's native Save As panel.
            nuke.scriptSaveAs()
    except RuntimeError:
        # User cancelled the save panel.
        return False

    return True


def _apply_frame_range(node, path: str) -> None:
    """Scan a sequence path on disk and set the frame range knobs on a Read node."""
    try:
        seq = fileseq.findSequenceOnDisk(path)
        node["first"].setValue(seq.start())
        node["last"].setValue(seq.end())
        node["origfirst"].setValue(seq.start())
        node["origlast"].setValue(seq.end())
    except fileseq.FileSeqException:
        pass
