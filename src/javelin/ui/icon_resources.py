import logging

logger = logging.getLogger(__name__)

PREFIX = ":/icons"

try:
    print("importing Qt icon resources")
    from javelin.ui import resources_rc  # noqa: F401 - import registers the :/icons/* resources
except ImportError:
    print("Qt icon resources have not been built - run `rez build` to generate them.")
