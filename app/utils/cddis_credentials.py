# app/utils/cddis_credentials.py
from __future__ import annotations
import os, platform, stat, shutil
from pathlib import Path
import netrc

URS = "urs.earthdata.nasa.gov"
CDDIS = "cddis.nasa.gov"

def _win_user_home() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home())))

def netrc_candidates() -> tuple[Path, ...]:
    """
    返回本机可能使用到的凭据文件路径：
      - Windows: 先返回 %USERPROFILE%\.netrc（你的 HTTPS 脚本会看它），再返回 %USERPROFILE%\_netrc
      - macOS/Linux: 返回 ~/.netrc
    """
    if platform.system().lower().startswith("win"):
        return (_win_user_home() / ".netrc", _win_user_home() / "_netrc")
    return (Path.home() / ".netrc",)

def _write_text_secure(p: Path, content: str) -> None:
    p.write_text(content, encoding="utf-8")
    if not platform.system().lower().startswith("win"):
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # 0600

def save_earthdata_credentials(username: str, password: str) -> tuple[Path, ...]:
    """
    保存 Earthdata 凭据；一次写两台主机（URS + CDDIS）。
    - Windows: 同时写 .netrc 和 _netrc（保证你的 HTTPS 脚本能找到 .netrc；工具链也能用 _netrc）
    - macOS/Linux: 写 ~/.netrc 并设 600 权限
    返回实际写入的路径列表。
    """
    content = (
        f"machine {URS}   login {username} password {password}\n"
        f"machine {CDDIS} login {username} password {password}\n"
    )
    written: list[Path] = []
    for p in netrc_candidates():
        # Windows 会写两份； *nix 就一份
        _write_text_secure(p, content)
        written.append(p)
    # 方便部分库查找
    os.environ["NETRC"] = str(written[0])
    return tuple(written)

def _ensure_windows_mirror() -> None:
    """
    若只有 _netrc 而没有 .netrc，则在 Windows 上自动复制一份 .netrc，
    以适配 download_products_https.py（它会去读 ~/.netrc）。
    """
    if not platform.system().lower().startswith("win"):
        return
    dot, under = _win_user_home() / ".netrc", _win_user_home() / "_netrc"
    if under.exists() and not dot.exists():
        try:
            shutil.copyfile(under, dot)
        except Exception:
            pass

def validate_netrc(required=(URS, CDDIS)) -> tuple[bool, str]:
    """
    校验是否有可用凭据：
      - Windows: 若只有 _netrc，自动镜像一份 .netrc
      - 检查 required 主机都有 login/password
      - 设置 NETRC 环境变量指向首选文件（Windows 为 .netrc；*nix 为 ~/.netrc）
    返回 (ok, 路径或错误原因)
    """
    _ensure_windows_mirror()
    candidates = netrc_candidates()
    # 取第一个存在的作为“首选”（Windows 为 .netrc；*nix 就 ~/.netrc）
    p = next((c for c in candidates if c.exists()), candidates[0])
    if not p.exists():
        return False, f"not found: {p}"
    try:
        n = netrc.netrc(p)
        for host in required:
            auth = n.authenticators(host)
            if not auth or not auth[0] or not auth[2]:
                return False, f"missing credentials for {host} in {p}"
        os.environ["NETRC"] = str(p)
        return True, str(p)
    except Exception as e:
        return False, f"invalid netrc {p}: {e}"