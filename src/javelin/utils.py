import contextlib
import functools
import importlib.util
import logging
import sys
import time
import types


def load_module_from_path(path: str, name: str | None = None) -> types.ModuleType:
    name = name or path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path!r}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class log_timing:
    """Logs execution time as a decorator or context manager.

    As a decorator, label defaults to the function name.
    As a context manager, label is required.
    """

    def __init__(self, logger: logging.Logger, label: str | None = None):
        self.logger = logger
        self.label = label
        self._t0: float = 0.0

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            result = func(*args, **kwargs)
            self.logger.debug("%s: %.3fs", self.label or func.__name__, time.perf_counter() - t0)
            return result

        return wrapper

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.logger.debug("%s: %.3fs", self.label or "block", time.perf_counter() - self._t0)
