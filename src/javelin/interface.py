from __future__ import annotations

import typing

from javelin.errors import AppInterfaceNotSetError


class AppInterface(typing.Protocol):
    """Structural contract a host app (Nuke, Maya, ...) implements to expose itself to
    host-agnostic javelin code, set once at bootstrap via set_interface()."""

    def current_path(self) -> str | None:
        """Path of the document currently open in the host, or None if nothing is open."""
        ...

    def is_modified(self) -> bool:
        """Whether the current document has unsaved changes."""
        ...

    def save(self) -> bool:
        """Save the current document.

        Returns False if the user cancels (e.g. dismisses a save dialog) rather than
        raising - cancellation is an expected outcome, not a failure.
        """
        ...

    def open(self, path: str) -> None:
        """Open `path` in the host, replacing the current document.

        Raises OSError (or a host-specific subclass) if `path` can't be opened.
        """
        ...


_interface: AppInterface | None = None


def set_interface(interface: AppInterface) -> None:
    global _interface
    _interface = interface


def get_interface() -> AppInterface:
    if _interface is None:
        raise AppInterfaceNotSetError("No AppInterface has been set. Call set_interface() during host bootstrap.")
    return _interface
