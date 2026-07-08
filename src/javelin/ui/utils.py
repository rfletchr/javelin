from __future__ import annotations

__all__ = ["invokeInContext"]

import typing

import shiboken6
from qtpy import QtCore

# Keeps unparented invokers alive until they fire; PySide would otherwise
# garbage collect them as soon as invokeInContext() returns.
_pending: set["_Invoker"] = set()


class _Invoker(QtCore.QObject):
    def __init__(self, context: QtCore.QObject, func: typing.Callable):
        super().__init__()
        self._context = context
        self._func = func

    @QtCore.Slot()
    def run(self) -> None:
        _pending.discard(self)
        self.deleteLater()
        if shiboken6.isValid(self._context):
            self._func()


def invokeInContext(context: QtCore.QObject, func: typing.Callable) -> None:
    """Runs func on context's thread on the next iteration of its event loop,
    like QTimer.singleShot(0, context, func), for Qt bindings that don't
    support the functor+context overload. Safe to call from any thread. The
    callback is skipped if `context` is destroyed before it runs.
    """
    invoker = _Invoker(context, func)
    invoker.moveToThread(context.thread())
    _pending.add(invoker)
    QtCore.QMetaObject.invokeMethod(invoker, "run", QtCore.Qt.QueuedConnection)
