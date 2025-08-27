from __future__ import annotations
import os
import platform
from pathlib import Path
from typing import Tuple
import netrc
import base64

ENV_FILE = Path(__file__).resolve().parent / "CDDIS.env"
EMAIL_KEY = "EMAIL"

# ------------------------------
#  Select .netrc/_netrc path (cross-platform compatibility)
# ------------------------------
def _pick_netrc() -> Path:
    """
    Prefer to use the path function provided in app.utils.cddis_credentials;
    if unavailable, try candidates; otherwise fall back to platform defaults.
    """
    try:
        from app.utils.cddis_credentials import netrc_path as _netrc_path  # type: ignore
    except Exception:
        _netrc_path = None
    if _netrc_path:
        try:
            return _netrc_path()
        except Exception:
            pass

    try:
        from app.utils.cddis_credentials import netrc_candidates as _netrc_candidates  # type: ignore
        cands = _netrc_candidates()
        for p in cands:
            if p.exists():
                return p
        return cands[0]
    except Exception:
        # Platform default
        if platform.system().lower().startswith("win"):
            return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".netrc"
        return Path.home() / ".netrc"


# ------------------------------
#  EMAIL read/write
# ------------------------------
def read_email() -> str | None:
    """First read from environment variable, then from utils/CDDIS.env (supporting EMAIL=xxx or EMAIL="xxx")."""
    v = os.environ.get(EMAIL_KEY, "").strip()
    if v:
        return v
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            k, _, val = s.partition("=")
            if k.strip() == EMAIL_KEY:
                return val.strip().strip('"').strip("'")
    return None


def write_email(email: str) -> Path:
    """Write to utils/CDDIS.env and synchronize EMAIL environment variable."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(f'{EMAIL_KEY}="{email}"\n', encoding="utf-8")
    os.environ[EMAIL_KEY] = email
    return ENV_FILE


# ------------------------------
#  Read username from .netrc (convention: username == email)
# ------------------------------
def get_username_from_netrc(prefer_host: str = "urs.earthdata.nasa.gov") -> Tuple[bool, str]:
    """
    Only read username from .netrc/_netrc (does not set env or write to disk).
    Return (ok, username_or_reason).
    """
    p = _pick_netrc()
    if not p.exists():
        return False, f"no netrc at {p}"
    try:
        n = netrc.netrc(p)
        auth = n.authenticators(prefer_host) or n.authenticators("cddis.nasa.gov")
        if not auth or not auth[0]:
            return False, f"no authenticators for {prefer_host} or cddis.nasa.gov in {p}"
        return True, auth[0]
    except Exception as e:
        return False, f"parse netrc failed: {e}"


def ensure_email_from_netrc(prefer_host: str = "urs.earthdata.nasa.gov") -> Tuple[bool, str]:
    """
    If EMAIL already exists, return it directly; otherwise, get username from .netrc as EMAIL,
    write to CDDIS.env, and return.
    """
    existing = read_email()
    if existing:
        os.environ[EMAIL_KEY] = existing
        return True, existing
    ok, user = get_username_from_netrc(prefer_host=prefer_host)
    if not ok:
        return False, user
    write_email(user)
    return True, user


# ------------------------------
#  Retrieve (username, password) from .netrc for authentication test
# ------------------------------
def _get_netrc_auth() -> tuple[str, str] | None:
    """Get (username, password) from .netrc/_netrc."""
    p = _pick_netrc()
    if not p.exists():
        return None
    n = netrc.netrc(p)
    for host in ("cddis.nasa.gov", "urs.earthdata.nasa.gov"):
        auth = n.authenticators(host)
        if auth and auth[0] and auth[2]:
            return (auth[0], auth[2])
    return None


# ------------------------------
#  Connectivity + authentication test (two phases)
# ------------------------------
def test_cddis_connection(timeout: int = 15) -> tuple[bool, str]:
    """
    Phase 1: Access robots.txt (network reachability)
    Phase 2: Use requests.Session() with (user, pass) from .netrc to access a restricted directory (authentication check)
    """
    import requests  # Force using requests since it is already installed
    # Phase 1: lightweight connectivity check
    r = requests.get("https://cddis.nasa.gov/robots.txt",
                     timeout=(5, timeout), headers={"User-Agent": "ginan-ui/https-check"})
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} on robots.txt"

    # Phase 2: restricted directory authentication
    creds = _get_netrc_auth()
    if not creds:
        return False, "no usable credentials in .netrc"
    session = requests.Session()
    session.auth = creds
    url = "https://cddis.nasa.gov/archive/gnss/products/2060/"  # Historical week directory, stable existence
    resp = session.get(url, timeout=(5, timeout),
                       headers={"User-Agent": "ginan-ui/auth-check"},
                       allow_redirects=True)
    head = resp.text[:1200]
    if resp.status_code == 200 and "Earthdata Login" not in head:
        return True, "AUTH OK"
    return False, f"HTTP {resp.status_code} or login page returned"