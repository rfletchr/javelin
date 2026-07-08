import nuke
from nukescripts import panels

from javelin.ui.panel.main import get_main_controller

JAVELIN_MAIN_CONTROLLER = get_main_controller()
pane = nuke.getPaneFor("Properties.1")
panels.registerWidgetAsPanel("JAVELIN_MAIN_CONTROLLER.get_view", "Javelin", "javelin.MainPanel", True).addToPane(pane)
