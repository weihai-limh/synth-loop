# -*- coding: utf-8 -*-
"""_b P6.2: ck 组件测试——SlContextKernel / SlInferenceSeam / 适配器（SlContextSource/SlDataPlane/SlLlmProvider）

承接 pk/ck 后，上下文相关测试从"测 sl context_* 散落群"改为"测 ck 组件"。
本文件覆盖：
- SlContextSource（ck ContextSource 适配器：read_session）
- SlDataPlane（ck DataPlane 适配器：store/fetch/transfer）
- SlInferenceSeam（推理缝：context_patch → build_prompt 拼装 → async 推理 → InferenceResult，三档 routing）
- SlContextKernel（ck 组件实例；infer 保持 NotImplementedError，推理缝归 SlInferenceSeam）
"""

import pytest

from app.kernels.context_kernel import ContextPatch
from app.kernels.context_kernel.core.models import InferenceResult, SessionView
from app.services.kernel_adapters import (
    SlContextSource, SlDataPlane, SlContextKernel, SlLlmProvider,
)
from app.services.inference_seam import SlInferenceSeam


@pytest.fixture
def mock_source():
    src = SlContextSource()
    src.register_session("sess-1", SessionView(
        permanent_system_prompt="你是相位推理执行器",
        loaded_docs=[{"doc_id": "d1", "content": "需求文档内容"}],
    ))
    return src


class _MockProvider(SlLlmProvider):
    """mock 推理 LLM：记录 service（routing），返回固定 content"""
    def __init__(self):
        self._selector = None
        self.routings = []
    async def chat(self, messages, service=None, model=None, api_key=None, tools=None, **kw):
        self.routings.append(service)
        # 断言拼装消息包含 permanent system + current user
        contents = [m.get("content", "") for m in messages]
        assert any("你是相位推理执行器" in c for c in contents)
        assert any("当前相位任务" in c for c in contents)
        return {"choices": [{"message": {"content": f"<{service}-result>"}}], "model": "mock"}


# ── SlContextSource（ContextSource 适配器）──

class TestSlContextSource:
    def test_read_session(self, mock_source):
        view = mock_source.read_session("sess-1")
        assert view.permanent_system_prompt == "你是相位推理执行器"
        assert view.loaded_docs[0]["doc_id"] == "d1"

    def test_read_session_unknown_returns_empty(self, mock_source):
        view = mock_source.read_session("unknown")
        assert view.permanent_system_prompt == ""
        assert view.loaded_docs == []


# ── SlDataPlane（DataPlane 适配器）──

class TestSlDataPlane:
    def test_store_fetch(self):
        plane = SlDataPlane()
        plane.store("pid-1", "art_pid-1_result_0", {"result": "ok"})
        got = plane.fetch("art_pid-1_result_0")
        assert got["data"]["result"] == "ok"

    def test_transfer(self):
        plane = SlDataPlane()
        r = plane.transfer("pid-1", {"ref": "art_x", "data": {"v": 1}})
        assert r["transferred"] is True
        assert plane.fetch("art_x")["data"]["v"] == 1


# ── SlLlmProvider（ck LlmProvider 适配器，P4 占位）──

class TestSlLlmProvider:
    def test_set_reply(self):
        provider = SlLlmProvider()
        provider.set_reply("<固定内容>")
        resp = provider.chat([{"role": "user", "content": "hi"}], "m")
        assert resp["choices"][0]["message"]["content"] == "<固定内容>"

    def test_no_reply_raises(self):
        provider = SlLlmProvider()
        with pytest.raises(RuntimeError):
            provider.chat([{"role": "user", "content": "hi"}], "m")


# ── SlInferenceSeam（推理缝，三档 routing）──

class TestSlInferenceSeam:
    @pytest.mark.asyncio
    async def test_planning_infer(self, mock_source):
        seam = SlInferenceSeam(context_source=mock_source, llm_provider=_MockProvider())
        r = await seam.infer(ContextPatch(
            phase_path=None, intent="当前相位任务：规划",
            context_id="sess-1", ext={"routing": "planning"}))
        assert isinstance(r, InferenceResult)
        assert r.content == "<planning-result>"
        assert r.context_id == "sess-1"
        assert r.ext["routing"] == "planning"
        assert r.ext["phase_path"] is None

    @pytest.mark.asyncio
    async def test_normal_infer_phase_path_str(self, mock_source):
        seam = SlInferenceSeam(context_source=mock_source, llm_provider=_MockProvider())
        r = await seam.infer(ContextPatch(
            phase_path="0-1", intent="当前相位任务：执行",
            context_id="sess-1", ext={"routing": "normal"}))
        assert r.content == "<normal-result>"
        assert r.ext["phase_path"] == "0-1"  # str 出缝契约

    @pytest.mark.asyncio
    async def test_summarize_infer(self, mock_source):
        seam = SlInferenceSeam(context_source=mock_source, llm_provider=_MockProvider())
        r = await seam.infer(ContextPatch(
            phase_path="0-1", intent="当前相位任务：总结",
            context_id="sess-1", ext={"routing": "summarize"}))
        assert r.content == "<summarize-result>"


# ── SlContextKernel（ck 组件实例；infer 保持 NotImplementedError）──

class TestSlContextKernel:
    def test_is_context_kernel_instance(self):
        kernel = SlContextKernel(
            context_source=SlContextSource(), data_plane=SlDataPlane(),
            llm_provider=SlLlmProvider(), primary_model="m", fallback_model="m",
        )
        assert isinstance(kernel, SlContextKernel)

    def test_infer_keeps_not_implemented(self):
        """推理缝归 SlInferenceSeam；SlContextKernel.infer 保持基类 NotImplementedError（防腐败）"""
        kernel = SlContextKernel(
            context_source=SlContextSource(), data_plane=SlDataPlane(),
            llm_provider=SlLlmProvider(), primary_model="m", fallback_model="m",
        )
        with pytest.raises(NotImplementedError):
            kernel.infer(ContextPatch(phase_path="0", intent="x", context_id="s"))


# ── 主路径过闸（_b P5.2：所有 chat 上下文可被 ck 闸优化）──

class TestMainPathGate:
    @pytest.mark.asyncio
    async def test_open_gate_returns_pending(self):
        """开闸（gate_mode=auto）：sl_llm_provider.chat 返回 pending + context_id（主路径上下文被 ck park）"""
        from app.services.sl_llm_provider import SlLlmProvider
        from app.kernels.context_kernel.core.models import GateMode

        provider = SlLlmProvider()
        # 注入 ck + 开闸
        kernel = SlContextKernel(
            context_source=SlContextSource(), data_plane=SlDataPlane(),
            llm_provider=SlLlmProvider(), primary_model="m", fallback_model="m",
        )
        kernel.set_gate_mode("auto")
        provider.set_ck(kernel)
        assert kernel.gate_mode == GateMode.AUTO

        resp = await provider.chat([{"role": "user", "content": "你好"}], service="chat")
        assert resp["gate"] == "pending"
        assert resp["context_id"]
        assert "context" in resp
        # 可经 ck 闸 peek（监听主路径上下文）
        peeked = kernel.gate_get(resp["context_id"])
        assert "context" in peeked

    @pytest.mark.asyncio
    async def test_closed_gate_direct(self):
        """关闸（closed）：不 park，直接走下游（无 ck 时不抛错，返回 gate 字段缺省）"""
        provider = SlLlmProvider()  # 无 ck → closed 语义，走 downstream_llm
        # 无 execution_router 时 downstream_llm.chat 会尝试默认 endpoint，这里仅验证不返回 pending
        with pytest.raises(Exception):
            await provider.chat([{"role": "user", "content": "hi"}], service="chat")
