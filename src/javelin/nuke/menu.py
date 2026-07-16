import nuke
import shiboken6
from nukescripts import panels
from qtpy import QtCore

from javelin.project import Project
from javelin.ui.panel.main import get_main_controller
from javelin.nuke.controller import NukeController

JAVELIN_PROJECT = Project.from_environment()
JAVELIN_MAIN_CONTROLLER = get_main_controller(JAVELIN_PROJECT)
JAVELIN_MAIN_CONTROLLER.populate()
JAVELIN_NUKE_CONTROLLER = NukeController()

JAVELIN_MAIN_CONTROLLER.workfileActivated.connect(JAVELIN_NUKE_CONTROLLER.openWorkfile)
JAVELIN_MAIN_CONTROLLER.workfileCreated.connect(JAVELIN_NUKE_CONTROLLER.openWorkfile)
JAVELIN_MAIN_CONTROLLER.publishActivated.connect(JAVELIN_NUKE_CONTROLLER.importFile)


def _onScriptLoad():
    # Not run for new scripts, but root().name() is empty for those anyway.
    path = nuke.root().name()
    if path:
        JAVELIN_MAIN_CONTROLLER.setSessionWorkfile(path)


nuke.addOnScriptLoad(_onScriptLoad)


def _onScriptClose():
    # Also fires when opening a new script over this one; harmless, setSessionWorkfile
    # for the new script runs right after and overwrites whatever this clears.
    # Also fires on Nuke exit, by which point Qt may have already torn down the panel's
    # widgets -- skip if so, since there's nothing left to clear and touching a
    # destroyed widget crashes.
    if shiboken6.isValid(JAVELIN_MAIN_CONTROLLER.view):
        JAVELIN_MAIN_CONTROLLER.clearSessionContext()


nuke.addOnScriptClose(_onScriptClose)


def attach():
    pane = nuke.getPaneFor("Properties.1")
    panels.registerWidgetAsPanel(
        "JAVELIN_MAIN_CONTROLLER.get_view",
        "Javelin",
        "javelin.MainPanel",
        True,
    ).addToPane(pane)


QtCore.QTimer.singleShot(400, attach)
