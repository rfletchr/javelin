import nuke
from nukescripts import panels
from qtpy import QtCore

from javelin.ui.panel.main import get_main_controller

JAVELIN_MAIN_CONTROLLER = get_main_controller()
JAVELIN_MAIN_CONTROLLER.populate()
pane = nuke.getPaneFor("Properties.1")


def attach():
    panels.registerWidgetAsPanel(
        "JAVELIN_MAIN_CONTROLLER.get_view",
        "Javelin",
        "javelin.MainPanel",
        True,
    ).addToPane(pane)


QtCore.QTimer.singleShot(0, attach)
