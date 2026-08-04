from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import ipaddress
import socket
from urllib.parse import urljoin, urlparse
import urllib.request

from . import netutil

MAX_RESPONSE_BYTES = 256 * 1024
FETCH_TIMEOUT_SECONDS = 3
SUCCESS_CACHE_SECONDS = 7 * 24 * 60 * 60
ERROR_CACHE_SECONDS = 60 * 60


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {str(key).lower(): str(value or '').strip() for key, value in attrs}
        if tag == 'title':
            self._in_title = True
        if tag != 'meta':
            return
        name = (values.get('property') or values.get('name') or '').lower()
        content = values.get('content') or ''
        if name in {'og:title', 'twitter:title', 'description', 'og:description', 'twitter:description'} and content:
            self.meta.setdefault(name, content)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == 'title':
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_parts.append(data)


def _compact(value: str, limit: int) -> str:
    return ' '.join(str(value or '').split())[:limit].strip()


def parse_html_metadata(html: str) -> dict[str, str]:
    parser = _MetadataParser()
    parser.feed(html or '')
    title = parser.meta.get('og:title') or parser.meta.get('twitter:title') or _compact(' '.join(parser.title_parts), 200)
    description = parser.meta.get('og:description') or parser.meta.get('twitter:description') or parser.meta.get('description') or ''
    result = {}
    if title:
        result['title'] = _compact(title, 200)
    if description:
        result['description'] = _compact(description, 400)
    return result


def _assert_public_host(host: str) -> None:
    lowered = host.lower().rstrip('.')
    if lowered in {'localhost', 'localhost.localdomain'} or lowered.endswith('.local'):
        raise ValueError('local host is not allowed')
    try:
        addresses = [ipaddress.ip_address(lowered)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(lowered, None, type=socket.SOCK_STREAM)]
        except OSError as exc:
            raise ValueError('host resolution failed') from exc
    if any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified for address in addresses):
        raise ValueError('private host is not allowed')


def validate_fetch_url(url: str) -> None:
    parsed = urlparse(str(url or '').strip())
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('only public http(s) URLs are allowed')
    _assert_public_host(parsed.hostname)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        validate_fetch_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def fetch_link_metadata(url: str) -> dict[str, str]:
    validate_fetch_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'qq-onebot-whitelist/1.0'}, method='GET')
    with netutil.open_url(request, timeout=FETCH_TIMEOUT_SECONDS, handlers=(_SafeRedirectHandler,)) as response:
        content_type = str(response.headers.get('Content-Type') or '').lower()
        if content_type and 'html' not in content_type and 'xhtml' not in content_type:
            return {}
        body = response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]
        charset = response.headers.get_content_charset() or 'utf-8'
    return parse_html_metadata(body.decode(charset, errors='replace'))


def _cache_fresh(row: dict, now: datetime) -> bool:
    try:
        fetched = datetime.fromisoformat(str(row.get('fetched_at') or ''))
    except ValueError:
        return False
    age = max(0, (now - fetched).total_seconds())
    return age <= (ERROR_CACHE_SECONDS if row.get('error') else SUCCESS_CACHE_SECONDS)


def get_or_fetch_link_metadata(store, url: str, *, fetcher=fetch_link_metadata) -> dict[str, str]:
    from .daily_report import canonical_url

    key = canonical_url(url)
    cached = store.get_link_metadata(key)
    now = datetime.utcnow()
    if cached and _cache_fresh(cached, now):
        return {name: str(cached.get(name) or '') for name in ('title', 'description') if cached.get(name)}
    try:
        metadata = fetcher(key) or {}
        store.save_link_metadata(key, metadata.get('title', ''), metadata.get('description', ''), '')
        return {name: str(metadata.get(name) or '') for name in ('title', 'description') if metadata.get(name)}
    except Exception as exc:
        store.save_link_metadata(key, '', '', f'{type(exc).__name__}: {exc}')
        return {}
