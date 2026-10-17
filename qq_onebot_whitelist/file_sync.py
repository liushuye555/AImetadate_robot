"""群文件上云流水线：NapCat 群文件列表补历史 + 实时入队 → 下载本体 → WebDAV 上传。

上传端对接 AList/OpenList 的 WebDAV 接口（把百度/阿里/OneDrive 等网盘统一挂载），
bot 不关心后端是哪家网盘。状态持久化在 file_uploads 表，按 (scope, file_id) 幂等。
"""
from __future__ import annotations

import asyncio
import base64
import http.client
import re
import shutil
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError

# NapCat 群文件 API 在不同版本叫法不同，逐个试探
_LIST_ACTIONS = ('get_group_root_files', 'get_group_files_by_folder', 'get_group_file_list')
_URL_ACTION = 'get_group_file_url'
_MAX_FOLDER_DEPTH = 6


class FileTooLargeError(RuntimeError):
    pass


class DeferredError(RuntimeError):
    """磁盘空间不足等暂时性障碍：本轮回滚为 pending，稍后再试。"""


class FileReferenceUnavailable(RuntimeError):
    """A stale file reference had no unique metadata match in the same group."""


class AmbiguousFileReference(FileReferenceUnavailable):
    """More than one same-group file has the exact requested name and size."""


def sanitize_segment(name: str) -> str:
    """路径段清洗：去掉 Windows/网络盘非法字符与首尾空点。"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name or '')).strip().strip('.')
    return cleaned or 'unnamed'


def _parse_base(base_url: str) -> tuple[str, int, str, bool]:
    parsed = urllib.parse.urlparse(base_url if '://' in base_url else 'http://' + base_url)
    host = parsed.hostname or '127.0.0.1'
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return host, port, parsed.path.rstrip('/'), parsed.scheme == 'https'


class WebDavClient:
    """最小 WebDAV 客户端（PROPFIND/MKCOL/PUT），标准库实现，零依赖。"""

    def __init__(self, base_url: str, user: str = '', password: str = ''):
        self.base_url = base_url
        self.host, self.port, self.prefix, self.use_tls = _parse_base(base_url)
        self.auth_headers: dict[str, str] = {}
        parsed = urllib.parse.urlparse(base_url if '://' in base_url else 'http://' + base_url)
        user = user or urllib.parse.unquote(parsed.username or '')
        password = password or urllib.parse.unquote(parsed.password or '')
        if user:
            credential = f'{user}:{password}'
            self.auth_headers['Authorization'] = 'Basic ' + base64.b64encode(credential.encode()).decode()

    def _request(self, method: str, path: str, *, data: Any = None,
                 headers: dict[str, str] | None = None, timeout: int = 30) -> int:
        target = (self.prefix + '/' + path.lstrip('/')) if path else (self.prefix or '/')
        if self.use_tls:
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(self.host, self.port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            all_headers = {**self.auth_headers, **(headers or {})}
            conn.request(method, urllib.parse.quote(target), body=data, headers=all_headers)
            resp = conn.getresponse()
            resp.read()
            return resp.status
        finally:
            conn.close()

    def exists(self, path: str) -> bool:
        try:
            return self._request('PROPFIND', path, headers={'Depth': '0'}) == 207
        except (HTTPError, OSError):
            return False

    def mkdirs(self, path: str) -> None:
        """逐段 MKCOL；已存在（405）视为成功。"""
        current = ''
        for part in [p for p in path.split('/') if p]:
            current += '/' + part
            try:
                status = self._request('MKCOL', current)
            except (HTTPError, OSError) as exc:
                raise RuntimeError(f'MKCOL {current} 失败: {exc}') from exc
            if status not in (200, 201, 405):
                raise RuntimeError(f'MKCOL {current} 返回 {status}')

    def put_file(self, remote_path: str, local_path: Path) -> None:
        """流式 PUT（http.client 直接吃文件对象，GB 级不占内存）。"""
        size = local_path.stat().st_size
        if self.use_tls:
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(self.host, self.port, timeout=1800)
        else:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=1800)
        target = self.prefix + '/' + remote_path.lstrip('/')
        try:
            with open(local_path, 'rb') as fh:
                headers = {**self.auth_headers, 'Content-Length': str(size)}
                conn.request('PUT', urllib.parse.quote(target), body=fh, headers=headers)
                resp = conn.getresponse()
                resp.read()
                if resp.status not in (200, 201, 204):
                    raise RuntimeError(f'WebDAV PUT {target} 返回 {resp.status}')
        finally:
            conn.close()


# ---- NapCat 群文件接口 ----

def _pick(data: Any, *names: str) -> Any:
    if not isinstance(data, dict):
        return None
    for name in names:
        if data.get(name) is not None:
            return data.get(name)
    return None


def _parse_listing(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """兼容 files/folders 数组在 data 或 data.data 下的各种返回形态。"""
    for _ in range(3):
        if (not isinstance(data, dict) or 'files' in data or 'folders' in data
                or not isinstance(data.get('data'), dict)):
            break
        data = data['data']
    files, folders = [], []
    for key, sink in (('files', files), ('folders', folders)):
        rows = data.get(key) if isinstance(data, dict) else None
        for row in rows or []:
            if isinstance(row, dict):
                sink.append(row)
    return files, folders


def url_from_response(resp: dict[str, Any]) -> str:
    body = resp.get('data') if isinstance(resp, dict) else None
    url = _pick(body if body is not None else resp, 'url')
    if not url:
        raise RuntimeError('get_group_file_url 未返回 url')
    return str(url)


async def scan_group(call_action, group_id: str, *, on_file: Callable[[dict[str, Any]], None],
                     max_depth: int = _MAX_FOLDER_DEPTH,
                     file_count: int | None = None,
                     require_complete: bool = False) -> int:
    """递归列出一个群的文件树，对每个文件回调 on_file(row)。返回文件数。"""
    total = 0
    visited_folders: set[str] = set()

    async def walk(folder_id: str, depth: int) -> None:
        nonlocal total
        if depth > max_depth:
            raise RuntimeError('群文件目录超过扫描深度上限')
        folder_id = str(folder_id or '')
        if folder_id in visited_folders:
            return
        visited_folders.add(folder_id)
        params: dict[str, Any] = {'group_id': int(group_id)}
        if folder_id:
            params['folder_id'] = folder_id
        if file_count is not None:
            params['file_count'] = int(file_count)
        listing = None
        last_error: Exception | None = None
        actions = _LIST_ACTIONS if not folder_id else _LIST_ACTIONS[1:]
        for action in actions:
            try:
                resp = await call_action(action, dict(params))
            except Exception as exc:
                last_error = exc
                continue
            status = str(resp.get('status') or '').lower() if isinstance(resp, dict) else ''
            body = resp.get('data') if isinstance(resp, dict) else None
            files, folders = _parse_listing(body if body is not None else resp)
            if status not in ('', 'ok', 'async'):
                last_error = RuntimeError('群文件列表接口返回失败状态')
                continue
            if require_complete and status == 'async':
                raise RuntimeError('群文件列表仍在异步处理中，不能确认扫描完整')
            if require_complete and _listing_is_incomplete(resp, len(files) + len(folders)):
                raise RuntimeError('群文件列表分页或总量信息表明扫描不完整')
            if status in ('', 'ok', 'async'):
                listing = (files, folders)
                break
        if listing is None:
            raise RuntimeError(f'群 {group_id} 文件列表接口不可用（试过 {", ".join(_LIST_ACTIONS)}）: {last_error}')
        files, folders = listing
        if file_count is not None and len(files) >= file_count:
            raise RuntimeError('群文件列表达到单次数量上限，不能确认扫描完整')
        for row in files:
            file_id = _pick(row, 'file_id', 'id')
            name = _pick(row, 'file_name', 'name', 'filename')
            if file_id is None or not name:
                continue
            total += 1
            on_file({
                'file_id': str(file_id),
                'file_name': str(name),
                'file_size': _pick(row, 'file_size', 'size'),
                'upload_time': _pick(row, 'uploaded_time', 'upload_time', 'upload_date'),
                'busid': _pick(row, 'busid'),
            })
        for row in folders:
            child_id = _pick(row, 'folder_id', 'id')
            if child_id is not None:
                await walk(str(child_id), depth + 1)

    await walk('', 0)
    return total


def _listing_is_incomplete(resp: Any, page_entries: int) -> bool:
    """Detect explicit pagination/truncation markers in common NapCat envelopes."""
    layers: list[dict[str, Any]] = []
    current = resp
    for _ in range(3):
        if not isinstance(current, dict):
            break
        layers.append(current)
        current = current.get('data')
    for layer in layers:
        for key in ('has_more', 'hasMore'):
            value = layer.get(key)
            if (value is True or (type(value) is int and value != 0)
                    or (isinstance(value, str) and value.strip().lower() in ('true', '1', 'yes'))):
                return True
        for key in ('next_cursor', 'nextCursor', 'next_page'):
            value = layer.get(key)
            if value is not None and value is not False and value != 0 and value != '':
                return True
        for key in ('total', 'total_count', 'totalCount'):
            value = layer.get(key)
            if isinstance(value, str) and value.isdecimal():
                value = int(value)
            if type(value) is int and value > page_entries:
                return True
    return False


# ---- 下载与上传 ----

def download_to_staging(url: str, staging_path: Path, *, max_bytes: int) -> Path:
    """流式下载到暂存路径；超过 max_bytes 抛 FileTooLargeError（调用方标记 skipped）。"""
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    partial = staging_path.with_suffix(staging_path.suffix + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': 'qq-onebot-whitelist/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=120) as resp, open(partial, 'wb') as out:
            received = 0
            while True:
                chunk = resp.read(1024 * 512)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise FileTooLargeError(f'文件超过上限 {max_bytes // (1024**3)}GB')
                out.write(chunk)
        partial.replace(staging_path)
        return staging_path
    finally:
        partial.unlink(missing_ok=True)


def remote_path_for(remote_base: str, group_name: str, scope: str,
                    file_name: str, upload_time: str | None) -> str:
    date_dir = '未知日期'
    stamp = str(upload_time or '').strip()
    if stamp.isdigit() and int(stamp) > 0:
        date_dir = datetime.fromtimestamp(int(stamp)).strftime('%Y-%m')
    elif stamp:
        match = re.match(r'(\d{4}-\d{2})', stamp)
        if match:
            date_dir = match.group(1)
    base = str(remote_base or '').strip('/')
    return '/'.join(
        part for part in (
            base,
            sanitize_segment(group_name or scope),
            date_dir,
            sanitize_segment(file_name),
        ) if part
    )


def staging_path_for(staging_dir: str | Path, scope: str, file_id: str, file_name: str) -> Path:
    return Path(staging_dir) / sanitize_segment(scope) / f'{sanitize_segment(file_id)}_{sanitize_segment(file_name)}'


def ensure_staging_disk_space(staging_dir: str | Path, needed_bytes: int, *, min_free_bytes: int = 2 * 1024**3) -> None:
    staging = Path(staging_dir)
    # disk_usage 要求路径已存在；暂存目录此时可能还没建
    probe = staging
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    free = shutil.disk_usage(probe).free
    if free < needed_bytes + min_free_bytes:
        gb = free / 1024**3
        raise DeferredError(f'暂存盘剩余 {gb:.1f}GB，不足以容纳下一个文件，本轮推迟')


async def process_pending(store, config, fetch_url: Callable[..., Any], *,
                          limit: int = 3) -> dict[str, int]:
    """处理至多 limit 条 pending：取链接 → 下载到暂存 → WebDAV 上传 → 标记。

    fetch_url(group_id, file_id, busid) 是异步回调：bot 传 call_action 包装，
    独立进程传 fetch_download_url 的包装。返回 {uploaded, skipped, failed, deferred} 计数。
    """
    stats = {'uploaded': 0, 'skipped': 0, 'failed': 0, 'deferred': 0}
    max_bytes = int(config.file_sync_max_file_gb * 1024**3)
    rows = store.pending_file_uploads(limit=limit)
    for row in rows:
        scope = str(row['scope'])
        file_id = str(row['file_id'])
        file_name = str(row['file_name'] or '')
        file_size = row['file_size']
        try:
            if file_size and file_size > max_bytes:
                store.mark_file_upload(int(row['id']), 'skipped', error=f'超过 max_file_gb={config.file_sync_max_file_gb}')
                stats['skipped'] += 1
                continue
            try:
                ensure_staging_disk_space(config.file_sync_staging_dir, int(file_size or 0))
            except DeferredError:
                stats['deferred'] += 1
                break
            staged = staging_path_for(config.file_sync_staging_dir, scope, file_id, file_name)
            if not (staged.exists() and (file_size or 0) == staged.stat().st_size):
                url = await fetch_url(scope, file_id, row.get('busid'))
                download_to_staging(url, staged, max_bytes=max_bytes)
            remote = remote_path_for(
                config.file_sync_remote_dir,
                store.group_display_name(scope), scope,
                file_name, row.get('upload_time'),
            )
            client = WebDavClient(config.file_sync_webdav_url,
                                  config.file_sync_webdav_user, config.file_sync_webdav_password)
            if not (client.exists(remote) and file_size and _remote_size_ok(client, remote, int(file_size))):
                client.mkdirs(remote.rsplit('/', 1)[0] if '/' in remote else remote)
                client.put_file(remote, staged)
            store.mark_file_upload(int(row['id']), 'uploaded', webdav_path=remote)
            stats['uploaded'] += 1
            staged.unlink(missing_ok=True)
        except FileTooLargeError as exc:
            store.mark_file_upload(int(row['id']), 'skipped', error=str(exc))
            stats['skipped'] += 1
        except DeferredError as exc:
            stats['deferred'] += 1
            print(f'file_sync: {file_name} 推迟: {exc}')
            break
        except Exception as exc:
            store.mark_file_upload(int(row['id']), 'failed', error=f'{type(exc).__name__}: {exc}'[:400])
            stats['failed'] += 1
    return stats


def _remote_size_ok(client: WebDavClient, remote: str, size: int) -> bool:
    """PROPFIND 里带 getcontentlength 时对一下大小；拿不到就当不存在（重新传覆盖）。"""
    try:
        host, port, prefix, use_tls = _parse_base(client.base_url)
        target = (prefix + '/' + remote.lstrip('/')) if remote else (prefix or '/')
        if use_tls:
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(host, port, timeout=30)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=30)
        try:
            conn.request('PROPFIND', urllib.parse.quote(target),
                         headers={**client.auth_headers, 'Depth': '0'})
            resp = conn.getresponse()
            body = resp.read().decode('utf-8', errors='replace')
            if resp.status != 207:
                return False
            match = re.search(r'getcontentlength[^>]*>(\d+)<', body)
            return int(match.group(1)) == size if match else False
        finally:
            conn.close()
    except (HTTPError, OSError):
        return False


def fetch_download_url_once(group_id: str, file_id: str, busid: int | None = None, *,
                            ws_url: str = 'ws://127.0.0.1:3001', timeout: float = 20,
                            file_name: str | None = None, file_size: int | None = None) -> str:
    """独立进程取新下载链接（群文件 URL 会过期）：开一条短 ws 连接。"""
    import json as _json

    async def _once() -> str:
        import websockets
        deadline = time.monotonic() + timeout
        try:
            async with websockets.connect(ws_url, open_timeout=timeout) as ws:
                async def call_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('群文件引用恢复超时')
                    echo = f'fs-{time.time()}-{id(params)}'
                    try:
                        await ws.send(_json.dumps({'action': action, 'params': params, 'echo': echo}, ensure_ascii=False))
                        while True:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError('群文件引用恢复超时')
                            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                            data = _json.loads(raw)
                            if not isinstance(data, dict) or data.get('echo') != echo:
                                continue
                            if isinstance(data.get('status'), str) and data['status'].lower() in ('failed', 'false'):
                                raise RuntimeError('OneBot 群文件请求失败')
                            return data
                    except asyncio.TimeoutError as exc:
                        raise TimeoutError('群文件引用恢复超时') from exc

                params: dict[str, Any] = {'group_id': int(group_id), 'file_id': str(file_id)}
                if busid:
                    try:
                        params['busid'] = int(busid)
                    except (TypeError, ValueError):
                        pass
                try:
                    url = url_from_response(await call_action(_URL_ACTION, params))
                    return url
                except Exception:
                    if not isinstance(file_name, str) or not file_name.strip() or type(file_size) is not int or file_size <= 0:
                        raise RuntimeError('无法取得群文件下载链接') from None

                matches: list[dict[str, Any]] = []
                visited: set[str] = set()
                calls = 0
                max_calls = 100

                async def bounded_call(action: str, params: dict[str, Any]) -> dict[str, Any]:
                    nonlocal calls
                    if calls >= max_calls:
                        raise RuntimeError('群文件列表扫描达到安全上限')
                    folder = str(params.get('folder_id') or '')
                    if action in _LIST_ACTIONS and folder in visited:
                        raise RuntimeError('群文件目录重复')
                    calls += 1
                    result = await call_action(action, params)
                    if action in _LIST_ACTIONS:
                        visited.add(folder)
                    return result

                matched_file_ids: set[str] = set()
                listed_files = 0

                def collect(row: dict[str, Any]) -> None:
                    nonlocal listed_files
                    listed_files += 1
                    if listed_files > 20000:
                        raise RuntimeError('群文件列表超过恢复扫描上限')
                    size = _pick(row, 'file_size', 'size')
                    if isinstance(size, str) and size.isdecimal():
                        size = int(size)
                    file_id_value = row.get('file_id')
                    if (row.get('file_name') == file_name and type(size) is int and size == file_size
                            and file_id_value is not None and str(file_id_value) not in matched_file_ids):
                        matched_file_ids.add(str(file_id_value))
                        matches.append(row)

                try:
                    await scan_group(bounded_call, str(group_id), on_file=collect,
                                     max_depth=_MAX_FOLDER_DEPTH, file_count=10000,
                                     require_complete=True)
                except Exception:
                    raise RuntimeError('无法安全扫描群文件列表') from None
                if not matches:
                    raise FileReferenceUnavailable('群内没有名称和大小均匹配的文件')
                if len(matches) != 1:
                    raise AmbiguousFileReference('群内有多个名称和大小均匹配的文件')
                recovered = matches[0]
                recovered_id = recovered.get('file_id')
                if recovered_id is None:
                    raise FileReferenceUnavailable('匹配文件缺少可用引用')
                recovered_params: dict[str, Any] = {'group_id': int(group_id), 'file_id': str(recovered_id)}
                recovered_busid = recovered.get('busid')
                if recovered_busid:
                    try:
                        recovered_params['busid'] = int(recovered_busid)
                    except (TypeError, ValueError):
                        pass
                try:
                    return url_from_response(await call_action(_URL_ACTION, recovered_params))
                except Exception:
                    raise RuntimeError('匹配到的群文件无法取得下载链接') from None
        except asyncio.TimeoutError:
            raise TimeoutError('群文件引用恢复超时') from None

    return asyncio.run(_once())
