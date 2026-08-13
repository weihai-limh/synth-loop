"""
Preprocessors - Phase 6: GW-P8 上下文数据包预处理器
按 packet type 分发预处理器，提取摘要文本注入 system prompt。
原则：预处理器必须是廉价提取器（规则/正则/统计），不可调 LLM。
"""
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── 预处理器类型 ──
PreprocessorFn = Callable[[dict[str, Any]], str]

# ── 截断常量 ──
DEFAULT_TRUNCATE_LEN = 200


# ═══════════════════════════════════════════════════════════
# 内置预处理器
# ═══════════════════════════════════════════════════════════

def _preprocess_dom(payload: dict) -> str:
    """DOM 结构摘要器：提取关键标签"""
    html = payload.get("html", payload.get("dom", ""))
    if not html:
        return ""
    import re
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    title = title_m.group(1) if title_m else "(无标题)"
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE)
    body_text = re.sub(r"<[^>]+>", " ", html)
    body_text = re.sub(r"\s+", " ", body_text).strip()
    parts = [f"网页标题: {title}"]
    if h1s:
        parts.append(f"主标题: {'; '.join(h1s[:3])}")
    parts.append(f"正文摘要: {body_text[:300]}")
    return "\n".join(parts)


def _preprocess_selection(payload: dict) -> str:
    """文本截断器"""
    text = payload.get("text", payload.get("selection", ""))
    if not text:
        return ""
    max_len = 5000
    if len(text) <= max_len:
        return f"[用户选中文本]\n{text}"
    return f"[用户选中文本(已截断)]\n{text[:max_len]}..."


def _preprocess_meta(payload: dict) -> str:
    """资源统计器：按 type 计数汇总"""
    resources = payload.get("resources", [])
    if not resources:
        return ""
    counts: dict[str, int] = {}
    for r in resources:
        t = r.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    lines = ["[页面资源统计]"]
    for t, c in sorted(counts.items()):
        lines.append(f"  {t}: {c} 个")
    total_size = payload.get("total_size", 0)
    if total_size:
        lines.append(f"  总大小: {total_size / 1024:.1f} KB")
    return "\n".join(lines)


def _preprocess_browser_structure(payload: dict) -> str:
    """结构化 DOM 描述器（pass-through）"""
    text = payload.get("text", payload.get("structure", ""))
    if not text:
        return ""
    return f"[页面结构]\n{text[:1000]}"


def _preprocess_audio_stub(payload: dict) -> str:
    """转写器 stub"""
    return "[audio transcription pending]"


def _preprocess_wechat_context(payload: dict) -> str:
    """小程序上下文规整器"""
    page = payload.get("page", "")
    params = payload.get("params", {})
    parts = [f"[小程序上下文] 页面: {page}"]
    if params:
        parts.append(f"参数: {params}")
    return "\n".join(parts)


def _preprocess_im_thread(payload: dict) -> str:
    """群信息脱敏器"""
    group = payload.get("group_name", "(未命名)")
    member_count = payload.get("member_count", 0)
    return f"[IM 上下文] 群: {group}, 成员数: {member_count}"


def _preprocess_im_history(payload: dict) -> str:
    """消息摘要器"""
    messages = payload.get("messages", [])
    if not messages:
        return ""
    recent = messages[-10:]
    lines = ["[IM 最近消息]"]
    for m in recent:
        sender = m.get("sender", "")[:8]
        text = str(m.get("text", ""))[:60]
        lines.append(f"  {sender}: {text}")
    return "\n".join(lines)


def _preprocess_packet_consent(payload: dict) -> str:
    """授权记录注入"""
    consent = payload.get("consent", {})
    if not consent:
        return ""
    return f"[授权记录] {consent}"


def _preprocess_aiot_sensor(payload: dict) -> str:
    """传感规整器"""
    parts = ["[IoT 传感器数据]"]
    for k, v in payload.items():
        if k not in ("device_id", "timestamp", "type"):
            parts.append(f"  {k}: {v}")
    return "\n".join(parts)


def _preprocess_device_status(payload: dict) -> str:
    """设备状态摘要"""
    uptime = payload.get("uptime", 0)
    battery = payload.get("battery", 0)
    signal = payload.get("signal", 0)
    return (
        f"[设备状态] 在线时长: {uptime}s, "
        f"电量: {battery}%, 信号: {signal}dBm"
    )


# ═══════════════════════════════════════════════════════════
# 预处理器注册表（权威真源: packets-api.md §4.2）
# ═══════════════════════════════════════════════════════════

PREPROCESSOR_REGISTRY: dict[str, PreprocessorFn] = {
    "browser_structure": _preprocess_browser_structure,
    "browser_dom": _preprocess_dom,
    "browser_meta": _preprocess_meta,
    "browser_selection": _preprocess_selection,
    "browser_audio": _preprocess_audio_stub,
    "wechat_context": _preprocess_wechat_context,
    "im_thread": _preprocess_im_thread,
    "im_message_history": _preprocess_im_history,
    "packet_consent": _preprocess_packet_consent,
    "aiot_sensor": _preprocess_aiot_sensor,
    "device_status": _preprocess_device_status,
}


def preprocess_packet(packet) -> str:
    """
    按 type 调用预处理器，返回摘要文本。
    无预处理器 → 注入原始 payload 截断版。
    """
    preprocessor = PREPROCESSOR_REGISTRY.get(packet.type)
    if preprocessor is not None:
        try:
            return preprocessor(packet.payload)
        except Exception as e:
            logger.warning(f"Preprocessor failed for type={packet.type}: {e}")
            return _preprocess_fallback(packet)
    return _preprocess_fallback(packet)


def _preprocess_fallback(packet) -> str:
    """无预处理器 → 截断原始 payload"""
    text = str(packet.payload)
    if len(text) > DEFAULT_TRUNCATE_LEN:
        text = text[:DEFAULT_TRUNCATE_LEN] + "..."
    return f"[packet:{packet.type}] {text}"
