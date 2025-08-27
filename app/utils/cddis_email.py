# app/utils/cddis_email.py
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
#  选择 .netrc/_netrc 的路径（兼容不同实现）
# ------------------------------
def _pick_netrc() -> Path:
    """
    优先使用 app.utils.cddis_credentials 中已提供的路径函数；
    若不可用，则尝试 candidates；再否则按平台默认推断。
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
        # 平台默认
        if platform.system().lower().startswith("win"):
            return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".netrc"
        return Path.home() / ".netrc"


# ------------------------------
#  EMAIL 读/写
# ------------------------------
def read_email() -> str | None:
    """优先读环境变量，其次读 utils/CDDIS.env（支持 EMAIL=xxx 或 EMAIL=\"xxx\"）。"""
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
    """写 utils/CDDIS.env，并同步环境变量 EMAIL。"""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(f'{EMAIL_KEY}="{email}"\n', encoding="utf-8")
    os.environ[EMAIL_KEY] = email
    return ENV_FILE


# ------------------------------
#  从 .netrc 读取用户名（你们约定：username == email）
# ------------------------------
def get_username_from_netrc(prefer_host: str = "urs.earthdata.nasa.gov") -> Tuple[bool, str]:
    """
    只读取 .netrc/_netrc 的用户名（不写 env、不落盘）。
    返回 (ok, username_or_reason)。
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
    若 EMAIL 已存在，直接返回；否则从 .netrc 取用户名作为 EMAIL，写入 CDDIS.env 并返回。
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
#  取 .netrc 的 (username, password) 供鉴权测试
# ------------------------------
def _get_netrc_auth() -> tuple[str, str] | None:
    """从 .netrc/_netrc 取 (username, password)。"""
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
#  连通性 + 鉴权测试（双阶段）
# ------------------------------
def test_cddis_connection(timeout: int = 15) -> tuple[bool, str]:
    """
    Phase 1: 访问 robots.txt（网络可达）
    Phase 2: requests.Session() 携带 .netrc 的 (user, pass) 访问受限目录（鉴权可用）
    """
    import requests  # 既然你已安装，我们强制走 requests 路径
    # Phase 1: 轻量连通
    r = requests.get("https://cddis.nasa.gov/robots.txt",
                     timeout=(5, timeout), headers={"User-Agent": "ginan-ui/https-check"})
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} on robots.txt"

    # Phase 2: 受限目录鉴权
    creds = _get_netrc_auth()
    if not creds:
        return False, "no usable credentials in .netrc"
    session = requests.Session()
    session.auth = creds
    url = "https://cddis.nasa.gov/archive/gnss/products/2060/"  # 历史周目录，稳定存在
    resp = session.get(url, timeout=(5, timeout),
                       headers={"User-Agent": "ginan-ui/auth-check"},
                       allow_redirects=True)
    head = resp.text[:1200]
    if resp.status_code == 200 and "Earthdata Login" not in head:
        return True, "AUTH OK"
    return False, f"HTTP {resp.status_code} or login page returned"