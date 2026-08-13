"""_a P3: LLM 层测试——6 场景路由 / llm_gateway 配置 / 模型级降级"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest
import respx

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def router():
    from app.services.execution_router import ExecutionRouter
    return ExecutionRouter(str(_SRC / "model_config.yaml"))


@pytest.fixture
def selector(router):
    from app.services.model_selector import ModelSelector
    return ModelSelector(router)


@pytest.fixture
def llm(router):
    from app.services.downstream_llm import DownstreamLLM
    llm = DownstreamLLM()
    llm.set_execution_router(router)
    return llm


class TestModelSelector:
    """6 场景选型（4→6 扩展）"""

    def test_six_scenarios(self, selector):
        for svc in ["chat", "prompt_chat", "task_chain", "analysis", "planning", "summarize"]:
            ep, model = selector.select(svc)
            assert ep is not None, f"{svc} 应选中端点"
            assert model, f"{svc} 应有模型"

    def test_planning_and_summarize(self, selector):
        """planning/summarize 场景按配置选型（新增场景）"""
        ep_p, m_p = selector.select("planning")
        ep_s, m_s = selector.select("summarize")
        assert m_p  # 规划模型
        assert m_s  # 摘要模型

    def test_unknown_scenario_falls_back_chat(self, selector):
        """缺失场景回退主 LLM（chat）"""
        ep, model = selector.select("unknown_scenario")
        assert ep is not None
        assert model


class TestLLMGatewayConfig:
    """llm_gateway 配置面（enabled=false 零影响）"""

    def test_gateway_config_loaded(self):
        import yaml
        with open(_SRC / "model_config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        gw = cfg.get("llm_gateway", {})
        assert gw.get("enabled") is False  # 默认关
        assert "msllm" in gw.get("gateways", {})
        assert gw["gateways"]["msllm"]["kind"] == "aggregation"

    def test_routing_unchanged_when_disabled(self, router):
        """enabled=false → 既有路由不受影响（chat 仍走 main_gateway）"""
        ep, model = router.resolve_endpoint("chat", "primary")
        assert ep.name == "main_gateway"


class TestModelLevelDegradation:
    """模型级降级（503 切同池 / 502 切端点 / 400 不降级）"""

    def test_503_falls_to_next_level(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        async def run():
            with respx.mock:
                respx.post("https://api.deepseek.com/chat/completions").mock(
                    return_value=httpx.Response(503, json={}))
                respx.post("https://open.bigmodel.cn/api/paas/v4/chat/completions").mock(
                    return_value=httpx.Response(200, json={"choices": [{"message": {"content": "fb-ok"}}]}))
                r = await llm.chat_with_degradation("chat", msgs)
                assert r["choices"][0]["message"]["content"] == "fb-ok"
            return True
        assert asyncio.run(run())

    def test_502_falls_to_next_endpoint(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        async def run():
            with respx.mock:
                respx.post("https://api.deepseek.com/chat/completions").mock(
                    return_value=httpx.Response(502, json={}))
                respx.post("https://open.bigmodel.cn/api/paas/v4/chat/completions").mock(
                    return_value=httpx.Response(200, json={"choices": [{"message": {"content": "fb2"}}]}))
                r = await llm.chat_with_degradation("chat", msgs)
                assert r["choices"][0]["message"]["content"] == "fb2"
            return True
        assert asyncio.run(run())

    def test_400_no_degradation(self, llm):
        """参数错/鉴权败 → 不降级（直接上抛）"""
        msgs = [{"role": "user", "content": "hi"}]
        async def run():
            with respx.mock:
                respx.post("https://api.deepseek.com/chat/completions").mock(
                    return_value=httpx.Response(400, json={}))
                try:
                    await llm.chat_with_degradation("chat", msgs)
                    return False
                except httpx.HTTPStatusError:
                    return True
        assert asyncio.run(run())

    def test_chain_exhausted_raises(self, llm):
        """全链耗尽 → 上抛最后错误"""
        msgs = [{"role": "user", "content": "hi"}]
        async def run():
            with respx.mock:
                respx.post("https://api.deepseek.com/chat/completions").mock(
                    return_value=httpx.Response(503, json={}))
                respx.post("https://open.bigmodel.cn/api/paas/v4/chat/completions").mock(
                    return_value=httpx.Response(503, json={}))
                respx.post("http://localhost:11434/v1/chat/completions").mock(
                    return_value=httpx.Response(503, json={}))
                try:
                    await llm.chat_with_degradation("chat", msgs)
                    return False
                except Exception:
                    return True
        assert asyncio.run(run())
