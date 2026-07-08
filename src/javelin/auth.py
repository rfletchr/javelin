from __future__ import annotations

import dataclasses
import json
import logging
import platform
import threading
import time
import webbrowser

import keyring
import requests
import requests.exceptions
import shotgun_api3

SERVICE_NAME = "atgm:flow"

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

    session = requests.Session()
    if http_proxy:
        session.proxies = {"http": http_proxy, "https": http_proxy}

    session_id, browser_url = _begin_request(session, site_url)
    webbrowser.open(browser_url)
    return _poll_for_credentials(session, site_url, session_id, timeout, cancel_event)


def _begin_request(session: requests.Session, site_url: str) -> tuple[str, str]:
    try:
        resp = session.post(
            site_url + _ASL_PATH,
            json={"appName": "toolkit", "machineId": platform.node()},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as exc:
        raise AuthenticationError(f"Failed to create session request: {exc}") from exc

    session_id = data.get("sessionRequestId") or data.get("id")
    browser_url = data.get("url")
    if not session_id or not browser_url:
        raise AuthenticationError(f"Unexpected ASL response: {data!r}")

    return session_id, browser_url


def _poll_for_credentials(
    session: requests.Session,
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
            resp = session.put(poll_url, json={}, timeout=15)
            if resp.status_code == 404:
                raise AuthenticationTimeout("Login session expired before browser approval.")
            resp.raise_for_status()
            result = resp.json()
        except AuthenticationTimeout:
            raise
        except requests.exceptions.RequestException as exc:
            raise AuthenticationError(f"Network error while polling: {exc}") from exc

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
    site_url = site_url or "https://elephant-goldfish.shotgrid.autodesk.com"

    creds = get_credentials(site_url)

    return shotgun_api3.Shotgun(
        site_url,
        session_token=creds.session_token,
    )


def store_credentials(creds: Credentials) -> None:
    keyring.set_password(SERVICE_NAME, creds.site_url, json.dumps(dataclasses.asdict(creds)))


def clear_credentials(site_url: str) -> None:
    """Remove any stored credentials for site_url, if present."""
    try:
        keyring.delete_password(SERVICE_NAME, site_url)
    except keyring.errors.PasswordDeleteError:
        pass


def _load_credentials(site_url: str) -> Credentials | None:
    encoded = keyring.get_password(SERVICE_NAME, site_url)
    if not encoded:
        logger.info("No cached credentials found for site_url %s", site_url)
        return None
    try:
        logger.info("Loading cached credentials for site_url %s", site_url)
        return Credentials(**json.loads(encoded))
    except Exception:
        return None


if __name__ == "__main__":
    connection = connect()
    print(connection.find_one("Project", []))
