from __future__ import annotations

__all__ = ["ConnectionFactory", "NotAuthenticated"]

import threading
import typing

from shotgun_api3.shotgun import Shotgun  # type: ignore[reportPrivateImportUsage]

from javelin import auth


class NotAuthenticated(Exception):
    """Raised when a client is requested before set_credentials() has ever been called."""


class _PooledConnection(typing.NamedTuple):
    client: Shotgun
    generation: int


class ConnectionFactory:
    """Hands out a thread-local shotgun_api3 connection for the current credentials.

    shotgun_api3.Shotgun isn't safe to share across threads, so each thread gets its own
    client, created lazily and kept current via a generation counter: set_credentials()
    bumps the generation, and any thread-local client found stale on next use has its
    session token refreshed in place rather than being rebuilt from scratch.

    This class has no opinion on how credentials are obtained, cached, renewed, or on what
    to do when none are available yet - it only raises NotAuthenticated and leaves that
    policy entirely to the caller.
    """

    def __init__(self, site_url: str):
        self.site_url = site_url
        self.__local = threading.local()
        self.__lock = threading.Lock()
        self.__credentials: auth.Credentials | None = None
        self.__generation = 0

    @property
    def credentials(self) -> auth.Credentials | None:
        return self.__credentials

    def set_credentials(self, credentials: auth.Credentials) -> None:
        with self.__lock:
            self.__credentials = credentials
            self.__generation += 1

    def clear_credentials(self) -> None:
        with self.__lock:
            self.__credentials = None
            self.__generation += 1

    def get_client(self) -> Shotgun:
        pooled: _PooledConnection | None = getattr(self.__local, "connection", None)
        if pooled is not None and pooled.generation == self.__generation:
            return pooled.client

        with self.__lock:
            generation = self.__generation
            credentials = self.__credentials

        if credentials is None:
            raise NotAuthenticated()

        if pooled is not None:
            client = pooled.client
            client.config.session_token = credentials.session_token
        else:
            client = Shotgun(self.site_url, session_token=credentials.session_token)

        self.__local.connection = _PooledConnection(client, generation)
        return client
