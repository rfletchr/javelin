import typing

from qtpy import QtCore, QtWidgets

from javelin.project import ContextClasses
from javelin.ui.promise import Promise
from javelin.ui.utils import invokeInContext


class BaseController(QtCore.QObject):
    busyChanged = QtCore.Signal(bool)  # type: ignore

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.__flow_pool = QtCore.QThreadPool(maxThreadCount=1)
        self.__busy_counter = 0

    def setBusy(self, busy: bool):
        was_busy = self.__busy_counter > 0
        self.__busy_counter += 1 if busy else -1
        still_busy = self.__busy_counter > 0

        if was_busy != still_busy:
            self.busyChanged.emit(still_busy)

    def promise(self, func: typing.Callable, *args, **kwargs):
        promise = Promise(self, func, *args, **kwargs)
        invokeInContext(self, lambda: self.__flow_pool.start(promise))
        return promise


class PanelController(BaseController):
    """A controller that can be handed to MainController.addTabController() to be
    hosted as a tab. Subclasses must implement getView()/getName(); setup()/teardown()
    are optional hooks for lazy initialization and cleanup around a tab's lifetime."""

    def getView(self) -> QtWidgets.QWidget:
        raise NotImplementedError

    def getName(self) -> str:
        raise NotImplementedError

    def setup(self):
        pass

    def teardown(self):
        pass

    def setProject(self, project: dict):
        pass

    def setContext(self, context: ContextClasses | None):
        pass
