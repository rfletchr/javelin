import typing

from qtpy import QtCore

from javelin.ui.promise import Promise


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
        QtCore.QTimer.singleShot(0, lambda: self.__flow_pool.start(promise))
        return promise
