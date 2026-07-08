import nuke
from nukescripts import panels
from qtpy import QtCore

from javelin.ui.panel.main import get_main_controller
from javelin.ui.nuke.controller import NukeController

JAVELIN_MAIN_CONTROLLER = get_main_controller()
JAVELIN_MAIN_CONTROLLER.populate()
JAVELIN_NUKE_CONTROLLER = NukeController()

JAVELIN_MAIN_CONTROLLER.workfileActivated.connect(JAVELIN_NUKE_CONTROLLER.openWorkfile)
JAVELIN_MAIN_CONTROLLER.workfileCreated.connect(JAVELIN_NUKE_CONTROLLER.openWorkfile)
JAVELIN_MAIN_CONTROLLER.publishActivated.connect(JAVELIN_NUKE_CONTROLLER.importFile)


def attach():
    pane = nuke.getPaneFor("Properties.1")
    panels.registerWidgetAsPanel(
        "JAVELIN_MAIN_CONTROLLER.get_view",
        "Javelin",
        "javelin.MainPanel",
        True,
    ).addToPane(pane)


QtCore.QTimer.singleShot(400, attach)
