import logging
import typing

import shiboken6
from qtpy import QtCore

from javelin.ui.utils import invokeInContext

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
            invokeInContext(self.__context, lambda: func(*args, **kwargs))

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


class PromiseAll:
    """Combines already-dispatched Promises into one then()/catch()/and_finally() surface
    that settles once every child has resolved, or as soon as the first one rejects.

    Callers must hand over bare promises and let this be the sole owner of their
    then()/catch() - Promise only holds a single callback per slot, so attaching your own
    callback first and then wrapping the promise here would silently clobber it.
    """

    def __init__(self, promises: list[Promise]):
        self.__results: list[typing.Any] = [None] * len(promises)
        self.__remaining = len(promises)
        self.__error: Exception | None = None
        self.__then: typing.Callable | None = None
        self.__catch: typing.Callable[[Exception], None] | None = None
        self.__finally: typing.Callable | None = None

        for index, promise in enumerate(promises):
            promise.then(lambda result, i=index: self.__onResult(i, result))
            promise.catch(self.__onError)

        if not promises:
            # Nothing to wait on - defer so then()/catch()/and_finally() below have a
            # chance to attach before we settle, same as they would for any real promise.
            QtCore.QTimer.singleShot(0, self.__settle)

    def then(self, func: typing.Callable):
        self.__then = func
        return self

    def catch(self, func: typing.Callable[[Exception], None]):
        self.__catch = func
        return self

    def and_finally(self, func: typing.Callable[[], None]):
        self.__finally = func
        return self

    def __onResult(self, index: int, result: typing.Any):
        if self.__error is not None:
            return
        self.__results[index] = result
        self.__remaining -= 1
        if self.__remaining == 0:
            self.__settle()

    def __onError(self, error: Exception):
        if self.__error is not None:
            return
        self.__error = error
        self.__settle()

    def __settle(self):
        if self.__error is not None:
            if self.__catch:
                self.__catch(self.__error)
        elif self.__then:
            self.__then(self.__results)

        if self.__finally:
            self.__finally()
