"""代理设置解析与直连兜底。"""

import pytest
import urllib.error
import urllib.request

from qq_onebot_whitelist import netutil
from qq_onebot_whitelist.config import load_config
from qq_onebot_whitelist.config_bridge import config_schema


def test_load_proxy_settings_enabled(tmp_path):
    cfg = tmp_path / 'config.yaml'
    cfg.write_text('network:\n  proxy:\n    enabled: true\n    host: 127.0.0.1\n    port: 7897\n', encoding='utf-8')
    assert netutil.load_proxy_settings(cfg) == {
        'http': 'http://127.0.0.1:7897',
        'https': 'http://127.0.0.1:7897',
    }


def test_load_proxy_settings_disabled_or_missing(tmp_path):
    cfg = tmp_path / 'config.yaml'
    cfg.write_text('network:\n  proxy:\n    enabled: false\n', encoding='utf-8')
    assert netutil.load_proxy_settings(cfg) is None
    assert netutil.load_proxy_settings(tmp_path / 'nope.yaml') is None


def test_open_url_falls_back_to_direct(monkeypatch, tmp_path):
    cfg = tmp_path / 'config.yaml'
    cfg.write_text('network:\n  proxy:\n    enabled: true\n    host: 127.0.0.1\n    port: 7897\n', encoding='utf-8')
    monkeypatch.setattr(netutil, 'load_proxy_settings', lambda *a: {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'})
    calls = []

    class FakeResp:
        def read(self):
            return b'ok'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeOpener:
        def __init__(self, proxy):
            self.proxy = proxy

        def open(self, req, data=None, timeout=None):
            calls.append(self.proxy)
            if self.proxy:
                raise urllib.error.URLError('proxy down')
            return FakeResp()

    def fake_build(*handlers):
        return FakeOpener(any(isinstance(h, urllib.request.ProxyHandler) for h in handlers))

    def fake_urlopen(req, timeout=None):
        calls.append(False)
        return FakeResp()

    monkeypatch.setattr(urllib.request, 'build_opener', fake_build)
    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    resp = netutil.open_url(urllib.request.Request('https://example.com/x'), timeout=3)
    assert calls == [True, False]  # 先代理，失败直连
    assert resp.read() == b'ok'


def test_open_url_never_proxies_local(monkeypatch, tmp_path):
    cfg = tmp_path / 'config.yaml'
    cfg.write_text('network:\n  proxy:\n    enabled: true\n', encoding='utf-8')
    calls = []

    def fake_build(*handlers):
        calls.append('opener')
        raise AssertionError('should not open')

    def fake_urlopen(req, timeout=None):
        calls.append('urlopen')
        raise AssertionError('should not reach')

    monkeypatch.setattr(urllib.request, 'build_opener', fake_build)
    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    with pytest.raises(AssertionError):
        netutil.open_url(urllib.request.Request('http://127.0.0.1:3001/health'), timeout=1)
    assert calls == ['urlopen']  # 本地地址直接 urlopen，不建代理 opener


def test_config_defaults_and_schema_include_proxy_and_both(tmp_path):
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text('', encoding='utf-8')
    config = load_config(cfg_path)
    assert config.links_link_judge == 'both'
    assert config.network_proxy_enabled is True
    assert config.network_proxy_host == '127.0.0.1'
    assert config.network_proxy_port == 7897
    schema = config_schema({})
    keys = [field['key'] for field in schema]
    assert 'network.proxy.enabled' in keys
    assert 'network.proxy.port' in keys
    link_field = next(field for field in schema if field['key'] == 'links.link_judge')
    assert link_field['default'] == 'both'
