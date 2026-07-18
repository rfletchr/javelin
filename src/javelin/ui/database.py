from __future__ import annotations

__all__ = ["Database"]

import logging
import threading

import shotgun_api3
from qtpy import QtCore
from shotgun_api3.shotgun import Shotgun  # type: ignore[reportPrivateImportUsage]

from javelin import auth
from javelin.shotgun_connection import ConnectionFactory, NotAuthenticated
from javelin.ui.promise import Promise
from javelin.ui.utils import invokeInContext

SITE_URL = "https://elephant-goldfish.shotgrid.autodesk.com"


logger = logging.getLogger(__name__)


class Database(QtCore.QObject):
    """Thin facade over a ConnectionFactory: dispatches shotgun_api3 calls onto a thread
    pool and returns Promises, and emits authenticationRequired whenever a call finds no
    usable credentials.

    This class has no opinion on how credentials are obtained or fixed - that's
    javelin.ui.login.LoginController's job. It only reports the problem.
    """

    authenticationRequired = QtCore.Signal()

    def __init__(self, connection_factory: ConnectionFactory, parent=None):
        super().__init__(parent=parent)
        logger.info("Database initialized.")
        self.__factory = connection_factory

    @property
    def site_url(self) -> str:
        return self.__factory.site_url

    def set_credentials(self, credentials: auth.Credentials) -> None:
        self.__factory.set_credentials(credentials)

    def get_entity_link(self, entity_type, entity_id):
        credentials = self.__factory.credentials
        if not credentials:
            raise RuntimeError("No credentials available")
        return f"{credentials.site_url}/detail/{entity_type}/{entity_id}"

    def get_connection(self) -> Shotgun:
        try:
            return self.__factory.get_client()
        except NotAuthenticated:
            self.authenticationRequired.emit()
            raise

    # -- call dispatch --------------------------------------------------

    def __invoke(self, method: str, args: tuple, kwargs: dict):
        try:
            client = self.__factory.get_client()
            return getattr(client, method)(*args, **kwargs)
        except (shotgun_api3.AuthenticationFault, NotAuthenticated):  # type: ignore[attr-defined]
            self.authenticationRequired.emit()
            raise

    def __call(self, context: QtCore.QObject, method: str, *args, **kwargs) -> Promise:
        promise = Promise(context, self.__invoke, method, args, kwargs)
        invokeInContext(context, lambda: QtCore.QThreadPool.globalInstance().start(promise))
        return promise

    # -- public API -------------------------------------------------------
    def user(self) -> dict:
        credentials = self.__factory.credentials
        if credentials is None:
            raise RuntimeError("Not authenticated")
        return credentials.user

    def find(
        self,
        context: QtCore.QObject,
        entity_type: str,
        filters: list,
        fields: list[str] | None = None,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "find", entity_type, filters, fields, *args, **kwargs)

    def find_one(
        self,
        context: QtCore.QObject,
        entity_type: str,
        filters: list,
        fields: list[str] | None = None,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "find_one", entity_type, filters, fields, *args, **kwargs)

    def create(
        self,
        context: QtCore.QObject,
        entity_type: str,
        data: dict,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "create", entity_type, data, *args, **kwargs)

    def update(
        self,
        context: QtCore.QObject,
        entity_type: str,
        entity_id: int,
        data: dict,
        *args,
        **kwargs,
    ) -> Promise:
        return self.__call(context, "update", entity_type, entity_id, data, *args, **kwargs)

    def delete(
        self,
        context: QtCore.QObject,
        entity_type: str,
        entity_id: int,
    ) -> Promise:
        return self.__call(context, "delete", entity_type, entity_id)

    def batch(self, context: QtCore.QObject, requests: list[dict]) -> Promise:
        return self.__call(context, "batch", requests)


__database: Database | None = None
__database_lock = threading.Lock()


def get_database() -> Database:
    global __database
    if __database is None:
        with __database_lock:
            if __database is None:
                __database = Database(ConnectionFactory(SITE_URL))
    return __database


if __name__ == "__main__":
    from qtpy import QtWidgets

    from javelin import auth

    app = QtWidgets.QApplication([])
    db = get_database()
    db.set_credentials(auth.get_credentials(SITE_URL))

    view = QtWidgets.QLabel()

    def on_result(row: dict):
        view.setText(row["code"])

    result = db.find_one(app, "Shot", [], ["code"]).then(on_result)
    view.show()

    app.exec()
