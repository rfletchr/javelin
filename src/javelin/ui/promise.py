import logging
import typing

import shiboken6
from qtpy import QtCore

logger = logging.getLogger(__name__)


class Promise(QtCore.QRunnable):
    def __init__(self, context: QtCore.QObject, func: typing.Callable, *args, **kwargs):
        super().__init__()
        self.__context = context
        self.__func = func
        self.__args = args
        self.__kwargs = kwargs
        self.__then: typing.Callable | None = None
        self.__catch: typing.Callable[[Exception], None] | None = None
        self.__finally: typing.Callable | None = None

    def noAutoDelete(self):
        self.setAutoDelete(False)
        return self

    def then(self, func: typing.Callable):
        self.__then = func
        return self

    def catch(self, func: typing.Callable[[Exception], None]):
        self.__catch = func
        return self

    def and_finally(self, func: typing.Callable[[], None]):
        self.__finally = func
        return self

    def _invokeMethod(self, func: typing.Callable, *args, **kwargs):
        if shiboken6.isValid(self.__context):
            QtCore.QTimer.singleShot(0, self.__context, lambda: func(*args, **kwargs))

    def run(self, /) -> None:
        if not shiboken6.isValid(self.__context):
            return
        try:
            result = self.__func(*self.__args, **self.__kwargs)
            if self.__then:
                self._invokeMethod(self.__then, result)

        except Exception as e:
            if self.__catch:
                self._invokeMethod(self.__catch, e)
            else:
                logger.exception("Unhandled exception in promise func %r", self.__func)

        finally:
            if self.__finally:
                self._invokeMethod(self.__finally)
