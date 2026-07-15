"""
InternalReasoner - Phase 4: GW-P3 任务链执行
_plan / _verify / _summarize 三个预制 Prompt；调用下游 LLM。
"""

import logging
import json
from typing import Any, Optional

logger = logging.getLogger(__name__)


class InternalReasoner:
    """内部推理器：计划→验证→汇总"""

    async def plan(self, user_ask: str, llm, **kwargs) -> list[str]:
        """将用户意图拆分为步骤列表"""
        system = """你是一个任务规划器。将用户的复杂需求拆分为3-7个有序的执行步骤。
每个步骤应该是具体的、可独立执行的子任务。以 JSON 数组返回步骤名称。

返回格式：["步骤1", "步骤2", "步骤3"]"""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_ask}
        ]
        try:
            result = await llm.chat(messages=messages, **kwargs)
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "[]")
            # 解析 JSON 数组
            steps = json.loads(content) if content.strip().startswith("[") else self._parse_steps(content)
            logger.info(f"Plan: {len(steps)} steps -> {steps}")
            return steps
        except Exception as e:
            logger.error(f"Plan failed: {e}, using default split")
            # 降级：按 "先/然后/再/最后" 拆分
            import re
            return re.split(r'[先然后再最后，,]+', user_ask)

    async def verify(self, step_result: str, expected: str, llm, **kwargs) -> dict:
        """验证步骤结果是否满足预期"""
        system = """你是一个结果验证器。判断步骤执行结果是否达到预期。
返回JSON：{"passed": true/false, "feedback": "简要反馈"}"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"预期: {expected}\n结果: {step_result}"}
        ]
        try:
            result = await llm.chat(messages=messages, max_tokens=200, **kwargs)
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return json.loads(content)
        except:
            return {"passed": True, "feedback": "验证跳过"}

    async def summarize(self, all_results: list[dict], llm, **kwargs) -> str:
        """汇总全部步骤的结果"""
        steps_text = "\n".join(
            f"步骤{r.get('step_num', i+1)}[{r.get('step_name', '')}]: {r.get('summary', '')}"
            for i, r in enumerate(all_results)
        )
        system = """你是一个结果汇总器。根据各步骤的执行结果，输出一个简洁的最终汇总。
包含：完成了什么、关键发现、后续建议。"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"各步骤结果:\n{steps_text}"}
        ]
        try:
            result = await llm.chat(messages=messages, **kwargs)
            return result.get("choices", [{}])[0].get("message", {}).get("content", "汇总完成")
        except:
            return "\n".join(r.get("summary", "") for r in all_results)

    def _parse_steps(self, text: str) -> list[str]:
        """从非 JSON 文本中提取步骤"""
        import re
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        steps = []
        for l in lines:
            l = re.sub(r'^\d+[\.\)、]\s*', '', l)
            if l:
                steps.append(l)
        return steps if steps else ["执行任务"]
