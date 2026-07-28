from __future__ import annotations

import os
import re

import nuke
from qtpy import QtCore, QtGui

from javelin.deadline import DeadlineJob, JobInfo, NukeInfo
from javelin.ui.render_submit import RenderItemRole, RenderSubmitController, RenderSubmitView

CheckState = QtCore.Qt.CheckState

_VERSION_PATTERN = re.compile(r"_v(\d+)", re.IGNORECASE)

_DEBOUNCE_INTERVAL_MS = 500
_RELEVANT_KNOB_NAMES = frozenset({"disable"})


def _scene_version(scene_path: str) -> str:
    match = _VERSION_PATTERN.search(os.path.basename(scene_path))
    return match.group(1) if match else "0"


class NukeRenderSubmitController(RenderSubmitController):
    def __init__(self, view: RenderSubmitView | None = None, parent=None):
        super().__init__(view=view, parent=parent)

        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(_DEBOUNCE_INTERVAL_MS)
        self._debounce_timer.timeout.connect(self.populate)

        nuke.addOnCreate(self.onUserCreate)
        nuke.addKnobChanged(self.onKnobChanged, nodeClass="Write")

    def onUserCreate(self):
        self._debounce_timer.start()

    def onKnobChanged(self):
        """Knob changes on Write nodes cluster - e.g. pasting several, or a script load
        touching every knob - so debounce rather than repopulating per change. Also
        ignore knobs populate() doesn't actually read, so unrelated edits (label,
        selection, etc.) don't trigger a rebuild for no reason."""
        if nuke.thisKnob().name() not in _RELEVANT_KNOB_NAMES:
            return
        self._debounce_timer.start()

    def populate(self):
        model = self.model()
        model.clear()

        for node in nuke.allNodes(recurseGroups=True):
            if nuke.getNodeClassName(node) != "Write":
                continue

            if "disable" not in node.knobs():
                continue

            disabled = node["disable"].value()

            item = QtGui.QStandardItem(node.fullName())
            item.setEditable(False)
            item.setCheckable(True)
            item.setCheckState(CheckState.Unchecked if disabled else CheckState.Checked)
            item.setEnabled(not disabled)
            if disabled:
                item.setToolTip("Write node is disabled")
            item.setData(node, RenderItemRole.Payload)
            model.appendRow(item)

        self.view.setFrameRange(f"{int(nuke.root().firstFrame())}-{int(nuke.root().lastFrame())}")

    def generateJobs(self, comment: str, frame_range: str) -> list[DeadlineJob]:
        scene_path = nuke.root().name()
        scene_name = os.path.basename(scene_path)

        env = os.environ.copy()

        jobs = []
        for item in self.getCheckedItems():
            node = item.data(RenderItemRole.Payload)
            job_info: JobInfo = {
                "Plugin": "Nuke",
                "Frames": frame_range,
                "Name": f"{scene_name} - {node.name()}",
                "Comment": comment,
                "Environment": env,
            }
            plugin_info: NukeInfo = {
                "SceneFile": scene_path,
                "Version": str(nuke.NUKE_VERSION_MAJOR),
                "WriteNode": node.name(),
            }
            jobs.append(DeadlineJob(job_info=job_info, plugin_info=plugin_info))

        return jobs
