from __future__ import annotations


class JavelinError(Exception):
    """Base class for all javelin-specific exceptions."""


class AppInterfaceNotSetError(JavelinError):
    """Raised when the host app interface is requested before bootstrap has set one."""


class AuthenticationError(JavelinError):
    pass


class AuthenticationTimeout(JavelinError):
    pass


class NotAuthenticated(JavelinError):
    """Raised when a client is requested before set_credentials() has ever been called."""


class WriteNodeError(JavelinError):
    pass


class NotSavedError(WriteNodeError):
    pass
