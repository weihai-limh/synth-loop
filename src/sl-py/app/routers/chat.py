"""聊天补全路由 - v0_1_1: Header 重命名 + 消息前置检查 + Dispatch 决策链 + SSE"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import get_section, get_session_memory_settings
from ..database import get_task
from ..models.schemas import ChatCompletionRequest
from ..models.session import Session
from ..services.context_router import ContextRouter, extract_client_system_messages, extract_user_content
from ..services.db_writer import DBWriter
from ..services.downstream_llm import DownstreamLLM
from ..services.session_manager import SessionManager
from ..services.tool_dispatcher import ToolDispatcher
from ..services.system_prompt_builder import SystemPromptBuilder
from ..services.complexity_classifier import ComplexityClassifier
from ..services.logic_abstractor import LogicAbstractor
from ..services.model_selector import ModelSelector
from ..services.context_compressor import ContextCompressor
from ..services.streaming_handler import StreamingHandler
from ..services.execution_router import get_execution_router
from ..services.context_manager import MANAGE_CONTEXT_DEFINITION, handle_manage_context
from ..tools import (
    LOAD_DOCUMENT_DEFINITION,
    SELECT_SYSTEM_PROMPT_DEFINITION,
    UNLOAD_DOCUMENT_DEFINITION,
    handle_load_document,
    handle_select_system_prompt,
    handle_unload_document,
)
from ..tools.discover_textcli import DISCOVER_TEXTCLI_DEFINITION, handle_discover_textcli
from ..tools.call_textcli import CALL_TEXTCLI_DEFINITION, handle_call_textcli
from ..services.strata_match_client import get_strata_match_client
from ..services.asset_consumer import get_asset_consumer
from ..services.degradation_manager import get_degradation_manager, DegradationLevel
from ..services.packet_store import get_packet_store
from ..services.preprocessors import preprocess_packet
from ..services.sl_llm_provider import get_sl_llm_provider
from ..config import get_packets_settings

router = APIRouter(tags=["chat"])

# 全局服务实例（在 main.py 中初始化）
session_manager: SessionManager
context_router: ContextRouter
tool_dispatcher: ToolDispatcher
downstream_llm: DownstreamLLM
db_writer: DBWriter
complexity_classifier: ComplexityClassifier
logic_abstractor: LogicAbstractor
model_selector: ModelSelector
context_compressor: ContextCompressor
system_prompt_builder: SystemPromptBuilder
streaming_handler: StreamingHandler


def init_services() -> None:
    """初始化服务实例"""
    global session_manager, context_router, tool_dispatcher, downstream_llm, db_writer
    global complexity_classifier, logic_abstractor, model_selector, context_compressor
    global system_prompt_builder, streaming_handler

    session_manager = SessionManager()
    context_router = ContextRouter()

    # 工具调度器
    tools_config = get_section("tools")
    cb_config = tools_config.get("circuit_breaker", {})
    tool_dispatcher = ToolDispatcher(
        failure_threshold=cb_config.get("failure_threshold", 3),
        recovery_timeout=cb_config.get("recovery_timeout", 30),
    )

    # 注册内置工具
    tool_dispatcher.register(
        "select_system_prompt",
        handle_select_system_prompt,
        SELECT_SYSTEM_PROMPT_DEFINITION,
    )
    tool_dispatcher.register(
        "load_document_to_context",
        handle_load_document,
        LOAD_DOCUMENT_DEFINITION,
    )
    tool_dispatcher.register(
        "unload_document_from_context",
        handle_unload_document,
        UNLOAD_DOCUMENT_DEFINITION,
    )
    
    # 注册 text-cli 元工具
    tools_config = get_section("tools")
    textcli_config = tools_config.get("textcli", {})
    if textcli_config.get("enabled", True):
        tool_dispatcher.register(
            "discover_textcli",
            handle_discover_textcli,
            DISCOVER_TEXTCLI_DEFINITION,
        )
        tool_dispatcher.register(
            "call_textcli",
            handle_call_textcli,
            CALL_TEXTCLI_DEFINITION,
        )

    downstream_llm = DownstreamLLM()
    db_writer = DBWriter()

    # Phase 3: 初始化 Dispatch 相关服务
    from ..config import load_config, SRC_DIR
    cfg = load_config()
    model_config_path = cfg.get("model_config_path", None)
    if model_config_path is None:
        model_config_path = str(SRC_DIR / "model_config.yaml")
    try:
        router_inst = get_execution_router(model_config_path)
        downstream_llm.set_execution_router(router_inst)
        logger.info("ExecutionRouter loaded successfully")
    except Exception as e:
        logger.warning(f"ExecutionRouter init failed: {e}, using default endpoints")

    complexity_classifier = ComplexityClassifier(
        str(SRC_DIR / "complexity_rules.yaml")
    )
    logic_abstractor = LogicAbstractor()
    model_selector = ModelSelector()
    context_compressor = ContextCompressor()
    system_prompt_builder = SystemPromptBuilder()
    streaming_handler = StreamingHandler()

    # Phase 4: 注册 manage_context 工具
    tool_dispatcher.register(
        "manage_context",
        handle_manage_context,
        MANAGE_CONTEXT_DEFINITION,
    )
    
    # v0_1_2: FRACTAL_SYSTEM_PROMPT 配置化——从文件加载
    global FRACTAL_SYSTEM_PROMPT
    from ..config import load_fractal_prompt
    FRACTAL_SYSTEM_PROMPT = load_fractal_prompt()

    # _b P5.2: 主路径过闸——注入 ck 内核到 sl_llm_provider（开闸时所有 chat 上下文可被 ck 闸优化）
    try:
        from ..services.kernel_adapters import build_sl_context_kernel
        _ck = build_sl_context_kernel()
        get_sl_llm_provider().set_ck(_ck)
        logger.info("sl_llm_provider ck kernel injected (main path gate-ready)")
    except Exception as e:
        logger.warning(f"sl_llm_provider ck injection failed (degraded, no gate): {e}")

    logger.info(f"Registered tools: {list(tool_dispatcher.registry.keys())}")
    logger.info(f"Tool definition count: {len(tool_dispatcher.definitions)}")


def _inject_dynamic_tools(tools: list[dict[str, Any]]) -> None:
    """
    注入动态工具到工具调度器
    
    Args:
        tools: strata-match 返回的工具列表
    """
    from ..services.strata_match_tool_adapter import get_tool_adapter
    
    adapter = get_tool_adapter()
    
    for tool in tools:
        name = tool.get("name", "")
        if not name:
            continue
        
        # 适配工具格式
        adapted = adapter.adapt(tool)
        if not adapted:
            logger.warning(f"Unable to adapt tool: {name}")
            continue
        
        # 提取元数据
        meta = adapter.extract_meta(adapted)
        
        # 注册到工具调度器
        tool_dispatcher.register_dynamic_tool(name, meta, adapted)
        logger.info(f"Injected dynamic tool: {name} (type: {meta.get('subtype')})")


async def first_turn_prompt_selection(session: Session, user_query: str) -> None:
    """首轮人设选择子流程（集成 strata-match + 三级降级）"""
    prompt_config = get_section("prompt_service")
    default_system_prompt = prompt_config.get("default_system_prompt", "你是一个有帮助的AI助手。")
    append_system_prompt = prompt_config.get("append_system_prompt", "")
    
    # 使用降级管理器获取策略
    degradation_manager = get_degradation_manager()
    strata_match_client = get_strata_match_client()
    
    prompt_text, degradation_level, result = await degradation_manager.get_strategy(
        strata_match_client=strata_match_client,
        user_query=user_query,
        default_prompt=default_system_prompt
    )
    
    # 合并追加的系统提示
    if append_system_prompt:
        prompt_text = f"{prompt_text}\n\n{append_system_prompt}"
        logger.info(f"Appended system prompt: {append_system_prompt}")
    
    # 获取工具和资源
    tools = result.get("tools", [])
    assets = result.get("assets", [])
    
    # 资源消费分析
    if tools and assets:
        asset_consumer = get_asset_consumer()
        processed_tools, independent_assets = asset_consumer.consume(tools, assets)
        
        # 注入处理后的工具（包含嵌入的资源）
        if processed_tools:
            _inject_dynamic_tools(processed_tools)
        
        # 将独立资源注入到上下文
        if independent_assets:
            assets_context = asset_consumer.format_assets_for_context(independent_assets)
            prompt_text = f"{prompt_text}\n\n{assets_context}"
            logger.info(f"Injected {len(independent_assets)} independent assets into context")
    elif tools:
        # 只有工具，没有资源
        _inject_dynamic_tools(tools)
    elif assets:
        # 只有资源，没有工具，全部独立注入
        asset_consumer = get_asset_consumer()
        assets_context = asset_consumer.format_assets_for_context(assets)
        prompt_text = f"{prompt_text}\n\n{assets_context}"
        logger.info(f"Injected {len(assets)} assets into context")
    
    # 记录降级状态
    if degradation_level == DegradationLevel.DEGRADED:
        logger.warning(f"Using degraded mode: {result.get('degradation_reason', 'unknown reason')}")
    elif degradation_level == DegradationLevel.FAILURE:
        logger.error(f"Using failure mode: {result.get('degradation_reason', 'system failure')}")
    
    session.permanent_system_prompt = prompt_text
    logger.info(f"Using strata-match strategy (level: {degradation_level}): {prompt_text[:100]}...")


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: Optional[str] = Header(None),
    http_request: Request = None,
) -> Any:
    """
    聊天补全接口（OpenAI 兼容） - Phase 3: Dispatch 决策链 + 上游过滤 + SSE 流式
    """
    # 1. 提取 API Key
    api_key = None
    if authorization:
        api_key = authorization.replace("Bearer ", "")

    # 2. 获取或创建 Session（支持 x-synthloop-session-id 复用）
    gw_session_id = http_request.headers.get("x-synthloop-session-id") if http_request else None
    session = await session_manager.get_or_create(gw_session_id)

    # 3. 提取消息
    current_user_content = extract_user_content(request.messages)
    client_system_messages = extract_client_system_messages(request.messages)
    user_text = current_user_content if isinstance(current_user_content, str) else str(current_user_content)

    # 3.5 v0_1_1 Phase 2: 消息前置检查层
    pre_check_response = await _handle_message_pre_check(user_text, session)
    if pre_check_response is not None:
        return _with_session_header(pre_check_response, session)

    # 规则2: user-memory 提取 + 清洗（非终点）
    cleaned = _extract_user_memory(user_text, session)
    if cleaned is not None:
        user_text = cleaned
        # 同步更新 current_user_content 用于后续构建 messages
        current_user_content = cleaned

    # 3.6 v0_1_1 Phase 6: packets 上下文注入
    packets_context, _expired = await _inject_packets(request)
    if packets_context:
        client_system_messages.insert(0, {"role": "system", "content": packets_context})

    # _b 相位标签触发（取代中文关键词）：解析 <tc-phase> / <tc-phase-chain> 得 mode + 目标
    phase_mode, phase_goal = _parse_phase_tag(user_text)
    if request.synth_pipeline or phase_mode is not None:
        from ..services.phase_chat_orchestrator import (
            get_phase_orchestrator, PhaseNotTriggeredError,
        )
        try:
            orchestrator = get_phase_orchestrator()
            gw_session_id_for_phase = http_request.headers.get("x-synthloop-session-id") if http_request else None
            # 标签剥除：相位目标用标签内文本（无标签时用原 user_text，用于 synth_pipeline 回传）
            phase_user_text = phase_goal if phase_goal else user_text
            phase_response = await orchestrator.handle_chat(
                user_text=phase_user_text,
                synth_pipeline=request.synth_pipeline,
                session_id=gw_session_id_for_phase,
                user_id=getattr(session, "user_id", None),
                mode=phase_mode,
            )
            # 包装为 OpenAI 格式响应（content + synth_pipeline 字段）
            payload = {
                "id": f"chatcmpl-phase-{phase_response['synth_pipeline']['id']}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": phase_response["content"]},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "synth_pipeline": phase_response["synth_pipeline"],
            }
            return _with_session_header(JSONResponse(content=payload), session)
        except PhaseNotTriggeredError:
            pass  # 未触发相位 → 走普通路径

    # 4. Phase 3: Dispatch 决策链
    complexity = complexity_classifier.classify(user_text)
    logic_category = logic_abstractor.abstract(user_text)
    session.set_complexity(complexity, logic_category)
    logger.info(f"Dispatch: complexity={complexity}, logic={logic_category}")

    # 5. Phase 3: 上游前置过滤
    system_content = "\n".join(m.get("content", "") for m in client_system_messages)
    if system_content:
        filter_result = context_compressor.process(system_content, complexity)
        if filter_result["action"] == "drop":
            client_system_messages = []  # 丢弃过大的 system 消息
        elif filter_result["action"] == "compress":
            client_system_messages = [{"role": "system", "content": filter_result["content"]}]

    # 6. SSE 流式分支
    if request.stream:
        return await _handle_streaming(
            request, session, user_text, complexity, logic_category,
            current_user_content, client_system_messages, api_key
        )

    # 7. 按 Dispatch 级别处理
    if complexity == "chat":
        response = await _handle_chat_level(request, session, user_text, current_user_content, client_system_messages, api_key)
        return _with_session_header(response, session)
    elif complexity == "task_chain":
        response = await _handle_task_chain_placeholder(request, session, user_text, logic_category, current_user_content, client_system_messages, api_key)
        return _with_session_header(response, session)
    elif complexity == "fractal":
        response = await _handle_fractal_dispatch(request, session, user_text, logic_category, current_user_content, client_system_messages, api_key)
        return _with_session_header(response, session)
    else:
        # prompt_chat 级别：调 strata-match
        response = await _handle_prompt_chat_level(request, session, user_text, complexity, logic_category,
                                                current_user_content, client_system_messages, api_key)
        return _with_session_header(response, session)


async def _handle_chat_level(request, session, user_text, current_user_content, client_system_messages, api_key):
    """chat 级：简单对话，经 sl_llm_provider 唯一推理落点（_b P5.2，主路径过闸）"""
    messages = context_router.build_messages(session, current_user_content=current_user_content)
    messages.insert(0, {"role": "system", "content": LANGUAGE_KEEP_PROMPT})
    # 归并进 build_messages 收束点：经 sl_llm_provider（唯一推理落点 + ck 闸）
    provider = get_sl_llm_provider()
    response = await provider.chat(
        messages=messages, service="chat", model=request.model,
        api_key=api_key, session_id=session.session_id,
    )
    # 开闸：返回 pending（带 context_id），等 ck 闸干预（peek/amend）后出结果
    if isinstance(response, dict) and response.get("gate") == "pending":
        return _gate_pending_response(response, session)
    choice = response.get("choices", [{}])[0]
    session.temp_history.append({"role": "user", "content": current_user_content})
    session.temp_history.append(choice.get("message", {}))
    session.increment_round()
    return JSONResponse(content=response)


async def _handle_prompt_chat_level(request, session, user_text, complexity, logic_category,
                                     current_user_content, client_system_messages, api_key):
    """prompt_chat 级：调 strata-match → 注入专家 Prompt → 下游 LLM（v0_1_1: 语言保持 prompt 注入）"""
    if not session.permanent_system_prompt:
        await first_turn_prompt_selection(session, user_text)

    tools_config = get_section("tools")
    max_loop = tools_config.get("max_loop", 10)
    final_response = None

    # 将用户消息提前写入 temp_history，确保工具循环中 LLM 能看到原始问题
    session.temp_history.append({"role": "user", "content": current_user_content})

    for loop in range(max_loop):
        messages = context_router.build_messages(
            session,
            current_user_content=current_user_content if loop == 0 else None,
            client_system_messages=client_system_messages if loop == 0 else None,
        )
        # v0_1_1: 语言保持 prompt 注入
        if loop == 0:
            messages.insert(0, {"role": "system", "content": LANGUAGE_KEEP_PROMPT})
        tools = tool_dispatcher.merge_client_tools(request.tools)

        # _b P5.2：经 sl_llm_provider 唯一推理落点（service=complexity + 主路径过闸）
        provider = get_sl_llm_provider()
        try:
            response = await provider.chat(
                messages=messages, service=complexity, model=request.model,
                tools=tools if tools else None, api_key=api_key,
                session_id=session.session_id,
                temperature=request.temperature, max_tokens=request.max_tokens,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Downstream LLM service unavailable: {str(e)}")

        # 开闸：返回 pending（带 context_id），等 ck 闸干预
        if isinstance(response, dict) and response.get("gate") == "pending":
            return _gate_pending_response(response, session)

        choice = response.get("choices", [{}])[0]
        finish_reason = choice.get("finish_reason", "")

        if finish_reason == "stop":
            session.temp_history.append(choice.get("message", {}))
            final_response = response
            break
        elif finish_reason == "tool_calls":
            session.temp_history.append(choice.get("message", {}))
            for tool_call in choice.get("message", {}).get("tool_calls", []):
                result = await tool_dispatcher.execute(tool_call, session)
                if result is not None:
                    session.temp_history.append({
                        "role": "tool", "tool_call_id": tool_call.get("id", ""),
                        "content": json.dumps(result, ensure_ascii=False),
                    })
        else:
            final_response = response
            break

    session.increment_round()
    if session.round_counter % session_manager.snapshot_interval == 0:
        await session_manager.save_snapshot(session)

    if final_response is None:
        raise HTTPException(status_code=500, detail="Unknown error occurred while processing the request")
    return JSONResponse(content=final_response)


async def _handle_task_chain_placeholder(request, session, user_text, logic_category, current_user_content, client_system_messages, api_key):
    """task_chain 路由入口（v0_1_2_d M4：新 TaskChainService 驱动）。

    Phase 4 占位已替换为真实执行：委托 TaskChainService 经 text-cli 编排，
    写 tasks 表（G3 落库责任承接），并返回 OpenAI 格式响应。
    """
    from ..services.task_chain_service import TaskChainService

    level = getattr(request, "fractal_level", None) or "task_chain"
    service = TaskChainService()
    try:
        result = await service.run(
            user_text=user_text,
            session=session,
            level=level,
            logic_category=logic_category,
            api_key=api_key,
        )
    except Exception as e:
        logger.error(f"task_chain dispatch failed: {e}")
        return JSONResponse(status_code=500, content={
            "id": f"chain-err-{session.session_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model or "task-chain",
            "choices": [{"index": 0, "message": {"role": "assistant",
                "content": f"⚠ task_chain 执行失败：{e}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })
    return JSONResponse(content=result)


async def _handle_streaming(request, session, user_text, complexity, logic_category,
                              current_user_content, client_system_messages, api_key):
    """SSE 流式处理"""
    if not session.permanent_system_prompt:
        await first_turn_prompt_selection(session, user_text)

    messages = context_router.build_messages(session, current_user_content=current_user_content)

    # 将用户消息写入临时历史，保持会话上下文一致性
    session.temp_history.append({"role": "user", "content": current_user_content})
    session.increment_round()

    # _b P5.2：经 sl_llm_provider 流式唯一推理落点
    provider = get_sl_llm_provider()
    return StreamingResponse(
        provider.chat_stream(
            messages=messages,
            service=complexity,
            model=request.model,
            api_key=api_key,
        ),
        media_type="text/event-stream",
        headers={"x-synthloop-session-id": session.session_id},
    )


def _with_session_header(response: JSONResponse, session: Session) -> JSONResponse:
    """为 JSONResponse 注入 x-synthloop-session-id Header"""
    response.headers["x-synthloop-session-id"] = session.session_id
    return response


def _gate_pending_response(pending: dict, session: Session) -> JSONResponse:
    """_b P5.2：开闸（ck gate_mode=auto）时主路径返回 pending（带 context_id，等 ck 闸干预）。

    上下文已 park（可经 GET /chatgate/{context_id} peek / POST amend），由外挂改进服务
    或调用方 peek/amend 后再经 gate_set 出结果——为未来上下文自动化优化留可能。
    """
    import time
    payload = {
        "id": f"chatcmpl-gate-{pending.get('context_id', '')[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gate-pending",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant",
                        "content": "上下文已提交推理闸（gate=pending），可经 /chatgate/{context_id} 干预后放行。"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "gate": "pending",
        "context_id": pending.get("context_id"),
        "context": pending.get("context", {}),
    }
    return _with_session_header(JSONResponse(content=payload), session)


# ═══════════════════════════════════════════════════════════
# v0_1_1 Phase 2: 消息前置检查层
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# v0_1_1 Phase 6: packets 上下文注入
# ═══════════════════════════════════════════════════════════

async def _inject_packets(request) -> tuple[str | None, list[str]]:
    """
    从请求中提取 packets[] 和 inline_data[]，预处理后返回注入文本。

    Returns:
        (context_text, expired_packet_ids)
        - context_text: 拼装好的 system prompt 摘要文本，无数据时返回 None
        - expired_packet_ids: 已过期的 packet ID 列表（供响应 meta 标记）
    """
    packets_config = get_packets_settings()
    if not packets_config.enabled:
        return None, []

    summaries: list[str] = []
    expired_ids: list[str] = []

    # ── 处理 packets[] ──
    packet_ids = request.packets
    if packet_ids:
        if len(packet_ids) > packets_config.max_packets_per_request:
            packet_ids = packet_ids[:packets_config.max_packets_per_request]

        try:
            store = get_packet_store()
            valid_packets, expired = store.get_batch(packet_ids)
            expired_ids = expired

            for pkt in valid_packets:
                try:
                    text = preprocess_packet(pkt)
                    if text:
                        summaries.append(f"[{pkt.type}/{pkt.source}] {text}")
                except Exception:
                    logger.warning(f"Packet preprocessing skipped: {pkt.packet_id}")
        except Exception as e:
            logger.warning(f"PacketStore exception, skipping packet injection: {e}")

    # ── 处理 inline_data[] ──
    inline_list = request.inline_data
    if inline_list:
        if len(inline_list) > packets_config.max_inline_data_per_request:
            inline_list = inline_list[:packets_config.max_inline_data_per_request]

        for item in inline_list:
            ptype = item.get("type", "unknown")
            payload = item.get("payload", {})
            payload_str = str(payload)
            if len(payload_str) > 5 * 1024 * 1024:  # 5MB per item
                summaries.append("[skipped_oversize]")
                continue
            if len(payload_str) <= 200:
                summaries.append(f"[inline:{ptype}] {payload_str}")
            else:
                summaries.append(f"[inline:{ptype}] {payload_str[:200]}...")

    if not summaries:
        return None, expired_ids

    context_text = "[上下文数据包]\n" + "\n".join(summaries)
    logger.info(f"Injecting {len(summaries)} packet summaries, {len(expired_ids)} expired")
    return context_text, expired_ids


TASK_ID_PATTERN = re.compile(r"Task-(.+?)-synthloop")
USER_MEMORY_PATTERN = re.compile(r"<user-memory>(.*?)</user-memory>", re.DOTALL)


# _b 相位标签触发（取代中文关键词）：<tc-phase>（结构分形 structural）/ <tc-phase-chain>（链式分形 chain）
_PHASE_TAG_CHAIN = re.compile(r"<tc-phase-chain>(.*?)</tc-phase-chain>", re.DOTALL)
_PHASE_TAG_STRUCT = re.compile(r"<tc-phase>(.*?)</tc-phase>", re.DOTALL)


def _parse_phase_tag(user_text: str) -> tuple[Optional[str], Optional[str]]:
    """解析相位标签，返回 (mode, goal)。

    - `<tc-phase-chain>目标</tc-phase-chain>` → ("chain", 标签内目标)
    - `<tc-phase>目标</tc-phase>`           → ("structural", 标签内目标)
    - 无标签 → (None, None)
    链式标签优先（更具体）。标签剥除后，标签内文本作为相位目标传给 handle_chat。
    """
    m = _PHASE_TAG_CHAIN.search(user_text)
    if m:
        return "chain", m.group(1).strip()
    m2 = _PHASE_TAG_STRUCT.search(user_text)
    if m2:
        return "structural", m2.group(1).strip()
    return None, None


def _extract_user_memory(text: str, session: Session) -> str | None:
    """
    规则2: <user-memory> 标签提取
    返回: 清洗后的 content（如果匹配），否则 None
    """
    mem_settings = get_session_memory_settings()
    if not mem_settings.enabled:
        return None

    match = USER_MEMORY_PATTERN.search(text)
    if not match:
        return None

    memory_content = match.group(1)
    if memory_content:  # 非空才写入
        prefix = "\n[User Memory]\n" if session.permanent_system_prompt else "[User Memory]\n"
        session.permanent_system_prompt += f"{prefix}{memory_content}"
        session.snapshot_dirty = True
        logger.info(f"<user-memory> extracted: {memory_content[:50]}")

    # 清洗 content——移除标签
    return USER_MEMORY_PATTERN.sub("", text).strip()


async def _handle_message_pre_check(user_text: str, session: Session) -> JSONResponse | None:
    """
    消息前置检查层——在 dispatch 之前执行。
    优先级：规则1 (Task-ID) > 规则2 (user-memory)

    Returns:
        JSONResponse → 终点响应（规则1 命中），调用方需直接返回
        None → 继续 dispatch
    """
    # ── 规则1: Task-ID 查询（终点） ──
    task_match = TASK_ID_PATTERN.search(user_text)
    if task_match:
        full_id = task_match.group(0)
        task = await get_task(full_id)
        if task:
            status = task.get("status", "unknown")
            if status == "completed":
                result_content = task.get("result", "")
                content = result_content or "Task completed."
            elif status in ("failed", "cancelled"):
                content = task.get("error", "") or f"Task {status}."
            elif status in ("queued", "running"):
                content = f"Task is {status}. Please check later."
            else:
                content = f"Task status: {status}"
        else:
            content = "Task not found."
        return JSONResponse(content={
            "id": f"task-query-{full_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "pre-check",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    # ── 规则2: user-memory 提取（非终点，继续 dispatch） ──
    # 由调用方在 pre-check 之后处理清洗
    return None


# ====== v0_1_1 Phase 5: 语言保持 prompt ======

LANGUAGE_KEEP_PROMPT = "Always use the same language as the user's latest message unless user explicitly asks."

# ====== v0_1_2: 6 级分形 Prompt 配置化 ======
# FRACTAL_SYSTEM_PROMPT 从 config/fractal_prompt.txt 加载
# 此变量由 init_services() 在启动时赋值
FRACTAL_SYSTEM_PROMPT = ""


def _classify_by_fractal(response_text: str) -> str:
    """
    解析分形 LLM 响应 (v0_1_1: 6 级 a-f)
    返回: complexity 级别字符串
    """
    text = response_text.strip().lower()
    # 兼容裸字母和 <E>X</E> 标签两种格式
    tag_match = re.search(r'<E>([a-f])</E>', text, re.IGNORECASE)
    if tag_match:
        return tag_match.group(1)
    # 尝试提取第一个字母
    letter_match = re.search(r'[a-f]', text)
    if letter_match:
        return letter_match.group(0)
    # 无法解析 → 回退到 chat
    return "a"


# 6 级 → 路由映射
FRACTAL_ROUTE_MAP = {
    "a": "chat",
    "b": "strata_match",
    "c": "strata_match",
    "d": "strata_match",  # async branch when enabled
    "e": "task_chain",    # async branch when enabled
    "f": "task_chain",
}

ASYNC_LEVELS = {"d", "e"}


async def _delegate_via_async_service(user_text: str, session, level: str) -> JSONResponse:
    """v0_1_2_d (M1): 统一经 AsyncDelegationService 委托 text-cli --async。

    废弃旧 _delegate_to_textcli 自建 httpx 实现（G3 闭环：写 tasks 表责任转移至
    Phase 8 新 TaskChainService，本 Phase 仅删除旧实现，不在此处写表，避免真空）。
    桥接：把 user_text/level 转成 path_json 最小信封 → delegate → poll → 回写响应。
    """
    from ..services.async_delegation import AsyncDelegationService

    # 最小信封（路径级），与 text-cli --async 协议对齐
    path_json = {
        "prompt": user_text,
        "level": level,
        "session_id": session.session_id,
        "mode": "async",
    }

    service = AsyncDelegationService()
    # [委托] 结构化日志（含 task_id / 阶段标记，为后续闸留观测基础）
    logger.info(f"[M1-DELEGATE] level={level} session={session.session_id} delegating to text-cli")
    try:
        text_cli_task_id = await service.delegate_to_textcli(
            step_name=f"fractal-{level}", path_json=path_json
        )
        logger.info(f"[M1-DELEGATE] ok task_id={text_cli_task_id} level={level}")
    except Exception as e:
        logger.error(f"[M1-DELEGATE] failed level={level} session={session.session_id}: {e}")
        return JSONResponse(status_code=502, content={
            "id": f"async-err-{uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"fractal-{level}",
            "choices": [{"index": 0, "message": {"role": "assistant",
                "content": f"⚠ 异步委托失败：{e}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    # [轮询] 结构化日志
    logger.info(f"[M1-POLL] task_id={text_cli_task_id} level={level} polling...")
    try:
        result_data = await service.poll_textcli_task(text_cli_task_id)
        logger.info(f"[M1-POLL] ok task_id={text_cli_task_id} level={level}")
    except Exception as e:
        logger.error(f"[M1-POLL] failed task_id={text_cli_task_id} level={level}: {e}")
        return JSONResponse(status_code=504, content={
            "id": f"async-poll-{uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"fractal-{level}",
            "choices": [{"index": 0, "message": {"role": "assistant",
                "content": f"⚠ 异步任务轮询失败：{e}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    # [回写] 结构化日志 + 响应构造
    logger.info(f"[M1-WRITE-BACK] task_id={text_cli_task_id} level={level} building response")
    template = "The asynchronous task opening code is as follows: {task_id}."
    content = template.format(task_id=text_cli_task_id)
    return JSONResponse(content={
        "id": f"async-{text_cli_task_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"fractal-{level}",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "_text_cli_task_id": text_cli_task_id,
        "_result": result_data,
    })


async def _check_concurrency_limit(user_id: str) -> bool:
    """v0_1_2: 检查用户并发是否超限（真实计数）"""
    from ..config import get_async_task_settings
    from ..database import get_shared_db
    settings = get_async_task_settings()
    max_per_user = settings.max_per_user
    try:
        db = await get_shared_db()
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE user_id = ? AND status IN ('queued', 'running')",
            (user_id,),
        )
        row = await cursor.fetchone()
        count = row[0] if row else 0
        return count < max_per_user
    except Exception:
        return True  # DB 不可用时降级放行


async def _handle_fractal_dispatch(request, session, user_text, logic_category,
                                    current_user_content, client_system_messages, api_key):
    """分形 Prompt (v0_1_1: 6 级 a-f) + async 判定"""
    from ..config import get_async_task_settings
    async_settings = get_async_task_settings()

    messages = context_router.build_messages(
        session,
        current_user_content=current_user_content,
        override_system=FRACTAL_SYSTEM_PROMPT.format(user_message=user_text),
    )

    try:
        # _b P5.2：经 sl_llm_provider 唯一推理落点（service=prompt_chat + 主路径过闸）
        provider = get_sl_llm_provider()
        response = await provider.chat(
            messages=messages, service="prompt_chat", model=request.model,
            api_key=api_key, session_id=session.session_id, max_tokens=800,
        )
        if isinstance(response, dict) and response.get("gate") == "pending":
            return _gate_pending_response(response, session)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        level = _classify_by_fractal(content)
        logger.info(f"Fractal: level={level}")

        # async 判定: d/e + enabled=true → 异步创建
        if level in ASYNC_LEVELS and async_settings.enabled:
            # 并发上限检查
            user_id = getattr(session, 'user_id', None)
            if not await _check_concurrency_limit(user_id):
                return JSONResponse(content={
                    "id": f"limit-{uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": "pre-check",
                    "choices": [{"index": 0, "message": {"role": "assistant",
                        "content": "There are currently {max} asynchronous tasks in progress. Please try again after one of them is completed.".format(max=async_settings.max_per_user)},
                        "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                })
            # v0_1_2_d (M1): 统一经 AsyncDelegationService，废弃旧 _delegate_to_textcli 自建 httpx
            return await _delegate_via_async_service(user_text, session, level)

        # 同步路由
        route = FRACTAL_ROUTE_MAP.get(level, "strata_match")
        if route == "chat":
            return await _handle_chat_level(request, session, user_text,
                                             current_user_content, client_system_messages, api_key)
        elif route == "strata_match":
            return await _handle_prompt_chat_level(request, session, user_text, "prompt_chat",
                                                    logic_category, current_user_content,
                                                    client_system_messages, api_key)
        else:  # task_chain
            return await _handle_task_chain_placeholder(request, session, user_text,
                                                         logic_category, current_user_content,
                                                         client_system_messages, api_key)

    except Exception as e:
        logger.error(f"Fractal dispatch failed: {e}, fallback to prompt_chat")
        return await _handle_prompt_chat_level(request, session, user_text, "prompt_chat",
                                                logic_category, current_user_content,
                                                client_system_messages, api_key)
