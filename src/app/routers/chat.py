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
from ..services.task_chain_executor import TaskChainExecutor
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
task_chain_executor: TaskChainExecutor


def init_services() -> None:
    """初始化服务实例"""
    global session_manager, context_router, tool_dispatcher, downstream_llm, db_writer
    global complexity_classifier, logic_abstractor, model_selector, context_compressor
    global system_prompt_builder, streaming_handler, task_chain_executor

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

    # Phase 4: 任务链执行器
    task_chain_executor = TaskChainExecutor()

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

    # _a 3.6: 相位 chat 路由（显式调用——带 synth_pipeline 字段或相位意图触发）
    if request.synth_pipeline or _is_phase_intent(user_text):
        from ..services.phase_chat_orchestrator import (
            get_phase_orchestrator, PhaseNotTriggeredError,
        )
        try:
            orchestrator = get_phase_orchestrator()
            gw_session_id_for_phase = http_request.headers.get("x-synthloop-session-id") if http_request else None
            phase_response = await orchestrator.handle_chat(
                user_text=user_text,
                synth_pipeline=request.synth_pipeline,
                session_id=gw_session_id_for_phase,
                user_id=getattr(session, "user_id", None),
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
    """chat 级：简单对话，直连下游 LLM（v0_1_1: 语言保持 prompt 注入）"""
    messages = context_router.build_messages(session, current_user_content=current_user_content)
    messages.insert(0, {"role": "system", "content": LANGUAGE_KEEP_PROMPT})
    endpoint_name, model = model_selector.select("chat")
    response = await downstream_llm.chat(
        messages=messages, model=model or request.model, api_key=api_key,
        endpoint_name=endpoint_name,
    )
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
        endpoint_name, model = model_selector.select(complexity, logic_category)

        try:
            response = await downstream_llm.chat(
                messages=messages, model=model or request.model, tools=tools if tools else None,
                api_key=api_key, endpoint_name=endpoint_name,
                temperature=request.temperature, max_tokens=request.max_tokens,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Downstream LLM service unavailable: {str(e)}")

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
    """task_chain 实际执行（v0_1_1: 语言保持 prompt 注入）"""
    if not session.permanent_system_prompt:
        await first_turn_prompt_selection(session, user_text)

    # v0_1_1: 语言保持 prompt 注入（临时追加到 session，executor 内部读取）
    _original_prompt = session.permanent_system_prompt
    session.permanent_system_prompt = f"{LANGUAGE_KEEP_PROMPT}\n\n{_original_prompt}" if _original_prompt else LANGUAGE_KEEP_PROMPT

    strata_match_client = get_strata_match_client()
    chain_result = await task_chain_executor.execute(
        user_ask=user_text,
        session=session,
        downstream_llm=downstream_llm,
        context_router=context_router,
        tool_dispatcher=tool_dispatcher,
        strata_match_client=strata_match_client,
        model_selector=model_selector,
        logic_category=logic_category,
        api_key=api_key,
        max_tokens=request.max_tokens or 4096,
    )

    # 构建响应
    summary = chain_result.get("summary", "")
    steps_text = "\n".join(
        f"{'✅' if s['status']=='completed' else '❌'} Step {s['step_num']}: {s['step_name']}"
        for s in chain_result.get("steps", [])
    )
    if chain_result.get("failed"):
        summary += f"\n\n⚠ Task chain failed at step {chain_result['failed_at_step']}."
        if chain_result.get("pending_steps"):
            summary += f"\nPending steps: {', '.join(chain_result['pending_steps'])}"

    response = {
        "id": f"chain-{chain_result['chain_id']}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model or "task-chain",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": f"{steps_text}\n\n{summary}"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    session.increment_round()
    session.permanent_system_prompt = _original_prompt  # v0_1_1: 恢复原始 prompt
    return JSONResponse(content=response)


async def _handle_streaming(request, session, user_text, complexity, logic_category,
                              current_user_content, client_system_messages, api_key):
    """SSE 流式处理"""
    if not session.permanent_system_prompt:
        await first_turn_prompt_selection(session, user_text)

    messages = context_router.build_messages(session, current_user_content=current_user_content)
    endpoint_name, model = model_selector.select(complexity, logic_category)

    # 将用户消息写入临时历史，保持会话上下文一致性
    session.temp_history.append({"role": "user", "content": current_user_content})
    session.increment_round()

    return StreamingResponse(
        streaming_handler.stream_openai(
            messages=messages,
            model=model or request.model,
            api_base=downstream_llm.api_base,
            api_key=api_key or downstream_llm.default_api_key,
        ),
        media_type="text/event-stream",
        headers={"x-synthloop-session-id": session.session_id},
    )


def _with_session_header(response: JSONResponse, session: Session) -> JSONResponse:
    """为 JSONResponse 注入 x-synthloop-session-id Header"""
    response.headers["x-synthloop-session-id"] = session.session_id
    return response


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


_PHASE_INTENT_PATTERNS = [
    r"用相位",
    r"用管道",
    r"pipeline\s*模式",
    r"分阶段(执行|处理|完成)",
    r"相位(模式|驱动)",
]


def _is_phase_intent(user_text: str) -> bool:
    """_a 3.6: 相位意图识别（规则层，R6——显式表达才触发，普通请求永不自动进相位）"""
    import re
    for pattern in _PHASE_INTENT_PATTERNS:
        if re.search(pattern, user_text, re.IGNORECASE):
            return True
    return False


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


async def _delegate_to_textcli(user_text: str, session, level: str, plan_step: dict = None) -> JSONResponse:
    """v0_1_2: 委托 text-cli --async 执行，不再空转"""
    from ..config import get_config
    from ..database import get_shared_db

    cfg = get_config()
    textcli_cfg = cfg.get("tools", {}).get("textcli", {})
    textcli_url = textcli_cfg.get("default_endpoint", "http://localhost:28050/text-cli/cli")

    # 调 text-cli --async 获取 task_id
    text_cli_task_id = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                textcli_url,
                json={"prompt": f"AI:--async {user_text}", "plan_step": plan_step},
            )
            resp.raise_for_status()
            data = resp.json()
            text_cli_task_id = data.get("task_id", data.get("id"))
    except Exception as e:
        logger.warning(f"_delegate_to_textcli failed for text-cli: {e}")
        text_cli_task_id = None

    # synth-loop tasks 表降为管道级日志
    task_id = f"Task-{uuid4().hex[:8]}-synthloop"
    try:
        db = await get_shared_db()
        await db.execute(
            """INSERT INTO tasks (id, session_id, user_id, input, status, result, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (task_id, session.session_id, getattr(session, 'user_id', None), user_text,
             json.dumps({"text_cli_task_id": text_cli_task_id}) if text_cli_task_id else None),
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to log pipeline task: {e}")

    logger.info(f"Async delegated to text-cli: synth_task={task_id}, text_cli_task={text_cli_task_id}, level={level}")
    template = "The asynchronous task opening code is as follows: {task_id}."
    content = template.format(task_id=text_cli_task_id or task_id)
    return JSONResponse(content={
        "id": f"async-{task_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"fractal-{level}",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "_text_cli_task_id": text_cli_task_id,
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
        endpoint_name, model = model_selector.select("prompt_chat")
        response = await downstream_llm.chat(
            messages=messages, model=model or request.model, api_key=api_key,
            endpoint_name=endpoint_name, max_tokens=800,
        )
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
            return await _delegate_to_textcli(user_text, session, level)

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
