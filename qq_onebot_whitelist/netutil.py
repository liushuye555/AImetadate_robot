"""出站 HTTP 代理工具：面板可配置，代理失败自动直连兜底。"""
from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
_cache = {"mtime": 0.0, "proxy": None}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def load_proxy_settings(config_path: str | Path | None = None) -> dict[str, str] | None:
    """读取 config.yaml 的 network.proxy；未启用/无配置返回 None（直连）。"""
    path = Path(config_path) if config_path else _REPO_ROOT / "config.yaml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    if mtime != _cache["mtime"]:
        proxy = None
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            cfg = (data.get("network") or {}).get("proxy") or {}
            if cfg.get("enabled", True):
                host = str(cfg.get("host") or "127.0.0.1").strip()
                port = int(cfg.get("port") or 7897)
                url = f"http://{host}:{port}"
                proxy = {"http": url, "https": url}
        except Exception:
            proxy = None
        _cache.update({"mtime": mtime, "proxy": proxy})
    return _cache["proxy"]


def _is_local_request(req: urllib.request.Request) -> bool:
    try:
        host = (urlparse(req.full_url).hostname or "").lower()
    except Exception:
        return False
    return host in _LOCAL_HOSTS or host.endswith(".local") or host.startswith("127.")


def open_url(
    req: urllib.request.Request,
    timeout: int | None = None,
    *,
    handlers: tuple = (),
):
    """代理优先，失败自动直连兜底；本地地址永不代理。"""
    if not _is_local_request(req):
        proxy = load_proxy_settings()
        if proxy:
            try:
                return urllib.request.build_opener(
                    urllib.request.ProxyHandler(proxy), *handlers
                ).open(req, timeout=timeout)
            except (urllib.error.URLError, OSError, TimeoutError):
                pass  # 代理不可用/超时 → 直连兜底
    if handlers:
        return urllib.request.build_opener(*handlers).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)
