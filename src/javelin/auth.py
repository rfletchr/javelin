from __future__ import annotations

import dataclasses
import http.cookiejar
import json
import logging
import pathlib
import platform
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import shotgun_api3

DEFAULT_SITE_URL = "https://elephant-goldfish.shotgrid.autodesk.com"

_CONFIG_DIR = pathlib.Path.home() / ".config" / "javelin"
_CONFIG_FILE = _CONFIG_DIR / "connection.json"

logger = logging.getLogger(__name__)


class NotgunAuthError(Exception):
    pass


class AuthenticationError(NotgunAuthError):
    pass


class AuthenticationTimeout(NotgunAuthError):
    pass


@dataclasses.dataclass(frozen=True)
class Credentials:
    site_url: str
    login: str
    session_token: str
    user: dict


_POLL_INTERVAL = 2
_ASL_PATH = "/internal_api/app_session_request"


# --- HTTP facade -----------------------------------------------------------
# The ASL login flow needs a handful of small JSON POST/PUT calls that share
# cookies across a single authentication attempt. This keeps that plumbing in
# one place instead of spreading urllib details through the module.


def _build_opener(http_proxy: str | None) -> urllib.request.OpenerDirector:
    handlers = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
    if http_proxy:
        handlers.append(urllib.request.ProxyHandler({"http": http_proxy, "https": http_proxy}))
    return urllib.request.build_opener(*handlers)


def _request_json(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    payload: dict,
    timeout: float,
) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.URLError as exc:
        raise AuthenticationError(f"Network error contacting {url}: {exc}") from exc


def authenticate(
    site_url: str,
    http_proxy: str | None = None,
    timeout: int = 180,
    cancel_event: threading.Event | None = None,
) -> Credentials:
    cancel_event = cancel_event or threading.Event()

    site_url = site_url.strip().rstrip("/")
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url

    opener = _build_opener(http_proxy)

    session_id, browser_url = _begin_request(opener, site_url)
    webbrowser.open(browser_url)
    return _poll_for_credentials(opener, site_url, session_id, timeout, cancel_event)


def _begin_request(opener: urllib.request.OpenerDirector, site_url: str) -> tuple[str, str]:
    try:
        data = _request_json(
            opener,
            "POST",
            site_url + _ASL_PATH,
            {"appName": "toolkit", "machineId": platform.node()},
            timeout=15,
        )
    except urllib.error.HTTPError as exc:
        raise AuthenticationError(f"Failed to create session request: {exc}") from exc

    session_id = data.get("sessionRequestId") or data.get("id")
    browser_url = data.get("url")
    if not session_id or not browser_url:
        raise AuthenticationError(f"Unexpected ASL response: {data!r}")

    return session_id, browser_url


def _poll_for_credentials(
    opener: urllib.request.OpenerDirector,
    site_url: str,
    session_id: str,
    timeout: int,
    cancel_event: threading.Event,
) -> Credentials:
    poll_url = f"{site_url}{_ASL_PATH}/{session_id}"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline and not cancel_event.is_set():
        time.sleep(_POLL_INTERVAL)
        if cancel_event.is_set():
            break
        try:
            result = _request_json(opener, "PUT", poll_url, {}, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise AuthenticationTimeout("Login session expired before browser approval.") from exc
            raise AuthenticationError(f"Error while polling: {exc}") from exc

        if result.get("approved"):
            login = result.get("userLogin") or result.get("login", "")
            token = result.get("sessionToken") or result.get("session_token", "")
            if not token:
                raise AuthenticationError(f"Session approved but no token in response: {result!r}")

            connection = shotgun_api3.Shotgun(site_url, session_token=token)
            user = connection.find_one("HumanUser", [["login", "is", login]])

            return Credentials(site_url=site_url, login=login, session_token=token, user=user)

    raise AuthenticationTimeout(f"Timed out after {timeout}s waiting for browser login approval.")


def validate(creds: Credentials, http_proxy: str | None = None) -> bool:
    try:
        sg = shotgun_api3.Shotgun(
            creds.site_url,
            session_token=creds.session_token,
            http_proxy=http_proxy,
        )
        sg.find_one("HumanUser", [])
        return True
    except shotgun_api3.AuthenticationFault:
        return False
    except Exception as exc:
        raise AuthenticationError(f"Unexpected error validating credentials: {exc}") from exc


def get_credentials(site_url: str) -> Credentials:
    creds = _load_credentials(site_url)
    if creds and validate(creds):
        return creds
    creds = authenticate(site_url)
    store_credentials(creds)
    return creds


def get_cached_credentials(site_url: str) -> Credentials | None:
    """Return locally cached credentials without contacting the server."""
    return _load_credentials(site_url)


def connect(site_url: str | None = None) -> shotgun_api3.Shotgun:
    site_url = site_url or DEFAULT_SITE_URL

    creds = get_credentials(site_url)

    return shotgun_api3.Shotgun(
        site_url,
        session_token=creds.session_token,
    )


# --- Credential store facade ------------------------------------------------
# Credentials live in a single JSON file, keyed by site_url, with SSH-style
# permissions (0700 dir / 0600 file) since there's no OS keychain backing it.


def _read_store() -> dict:
    try:
        with _CONFIG_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_store(store: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_DIR.chmod(0o700)
    _CONFIG_FILE.write_text(json.dumps(store), encoding="utf-8")
    _CONFIG_FILE.chmod(0o600)


def store_credentials(creds: Credentials) -> None:
    store = _read_store()
    store[creds.site_url] = dataclasses.asdict(creds)
    _write_store(store)


def clear_credentials(site_url: str) -> None:
    """Remove any stored credentials for site_url, if present."""
    store = _read_store()
    if store.pop(site_url, None) is not None:
        _write_store(store)


def _load_credentials(site_url: str) -> Credentials | None:
    store = _read_store()
    encoded = store.get(site_url)
    if not encoded:
        logger.info("No cached credentials found for site_url %s", site_url)
        return None
    try:
        logger.info("Loading cached credentials for site_url %s", site_url)
        return Credentials(**encoded)
    except Exception:
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    clear_credentials(DEFAULT_SITE_URL)
    connection = connect()
    print(connection.find_one("Project", []))
