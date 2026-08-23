"""
PacketStore - Phase 6: GW-P8 上下文数据包存储引擎
内存缓存 + TTL 自动清理 + type 校验。
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from ..config import get_packets_settings

logger = logging.getLogger(__name__)

# ── type 注册表（权威真源: functional_design/packets-api.md §4.2） ──
# _c: 类型准入改配置驱动（config.yaml packets.types 完整列表）；此处保留内置默认（空配置回落）
DEFAULT_PACKET_TYPES: set[str] = {
    # chrome-plugin
    "browser_structure",
    "browser_dom",
    "browser_meta",
    "browser_selection",
    "browser_audio",
    # mini-program
    "wechat_context",
    # dm-im-buddy
    "im_thread",
    "im_message_history",
    "packet_consent",
    # ESP32
    "aiot_sensor",
    "device_status",
    # 远期预留
    "rpi_sensor",
    "camera_frame",
}

# 兼容别名（packets.py 曾 import VALID_PACKET_TYPES）；实际准入用 get_valid_packet_types()
VALID_PACKET_TYPES: set[str] = DEFAULT_PACKET_TYPES


def get_valid_packet_types() -> set[str]:
    """类型准入：读 config.yaml packets.types（完整列表）；空配置回落内置默认（向后兼容）。"""
    types = get_packets_settings().types
    if types:
        return set(types)
    return DEFAULT_PACKET_TYPES


@dataclass
class Packet:
    """上下文数据包"""
    packet_id: str
    source: str
    type: str
    payload: dict
    meta: dict = field(default_factory=dict)
    captured_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def __post_init__(self):
        if self.expires_at == 0.0:
            settings = get_packets_settings()
            self.expires_at = self.captured_at + settings.ttl_seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class PacketStore:
    """Packet 内存存储，TTL 自动清理。读取无锁（CPython GIL 保证 dict 单操作安全）。"""

    def __init__(self, ttl_seconds: int = 1800):
        self._store: dict[str, Packet] = {}
        self._ttl = ttl_seconds

    def store(self, source: str, ptype: str, payload: dict, meta: dict) -> Packet:
        """存入 packet，返回 Packet 对象"""
        packet_id = f"pkt_{uuid4().hex[:16]}"
        packet = Packet(
            packet_id=packet_id,
            source=source,
            type=ptype,
            payload=payload,
            meta=meta,
        )
        self._store[packet_id] = packet
        logger.info(f"PacketStore: stored {packet_id} (type={ptype})")
        return packet

    def get(self, packet_id: str) -> Packet | None:
        """按 ID 取 packet（已过期返回 None）"""
        pkt = self._store.get(packet_id)
        if pkt is None:
            return None
        if pkt.is_expired():
            del self._store[packet_id]
            logger.debug(f"PacketStore: expired {packet_id}")
            return None
        return pkt

    def get_batch(self, packet_ids: list[str]) -> tuple[list[Packet], list[str]]:
        """批量取，返回 (有效的packets, 过期的packet_ids)"""
        valid: list[Packet] = []
        expired: list[str] = []
        for pid in packet_ids:
            pkt = self.get(pid)
            if pkt is not None:
                valid.append(pkt)
            else:
                expired.append(pid)
        self._evict_expired()
        return valid, expired

    def _evict_expired(self):
        """惰性清理过期 packet"""
        now = time.time()
        expired = [pid for pid, p in self._store.items() if now > p.expires_at]
        for pid in expired:
            del self._store[pid]
            logger.debug(f"PacketStore: evicted expired {pid}")

    @staticmethod
    def validate_type(ptype: str) -> bool:
        """校验 packet type 是否在类型准入列表中（配置驱动，空配置回落内置默认）"""
        return ptype in get_valid_packet_types()

    @property
    def size(self) -> int:
        return len(self._store)


# ── 全局实例 ──
_packet_store: Optional[PacketStore] = None


def get_packet_store() -> PacketStore:
    """获取 PacketStore 单例"""
    global _packet_store
    if _packet_store is None:
        settings = get_packets_settings()
        _packet_store = PacketStore(ttl_seconds=settings.ttl_seconds)
    return _packet_store
