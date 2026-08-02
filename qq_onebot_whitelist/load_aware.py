"""负载感知调度：系统高负载（如打游戏）时推迟图片处理/维护等重活。

所有"重活"（图片混淆检测/还原、重分类、重建视图、AI 分析）统一走
load_aware_ok() 判定：未启用或 CPU 低于阈值时允许执行，否则由调用方延迟重试。
"""

from __future__ import annotations

import ctypes
import time

from .config import AppConfig

_last_cpu: float = 0.0
_last_cpu_at: float = 0.0


def system_cpu_percent(sample_seconds: float = 0.4) -> float:
    """通过 GetSystemTimes 采样 CPU 占用（0~100），失败时返回 0。"""
    try:
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        def sample() -> tuple:
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            return idle, kernel, user

        def to64(ft: FILETIME) -> int:
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        idle0, kernel0, user0 = sample()
        time.sleep(max(0.05, min(1.0, sample_seconds)))
        idle1, kernel1, user1 = sample()
        idle = to64(idle1) - to64(idle0)
        kernel = to64(kernel1) - to64(kernel0)
        user = to64(user1) - to64(user0)
        total = max(1, kernel + user)
        return max(0.0, min(100.0, 100.0 * (1.0 - idle / total)))
    except Exception:
        return 0.0


def cached_cpu_percent(ttl: float = 3.0) -> float:
    """带 TTL 的 CPU 读数：高频调用（如逐条消息判断）避免每次都采样阻塞。"""
    global _last_cpu, _last_cpu_at
    now = time.monotonic()
    if now - _last_cpu_at < ttl:
        return _last_cpu
    _last_cpu = system_cpu_percent(0.2)
    _last_cpu_at = now
    return _last_cpu


def load_aware_ok(config: AppConfig, cpu: float | None = None) -> bool:
    """是否允许执行重活：未启用 → True；CPU 低于阈值 → True。"""
    if not config.load_aware_enabled:
        return True
    if cpu is None:
        cpu = cached_cpu_percent()
    return cpu < config.load_aware_cpu_threshold


def load_aware_defer_seconds(config: AppConfig) -> int:
    """高负载时的重试间隔（秒）。"""
    return max(1, config.load_aware_check_seconds)
