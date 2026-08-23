# -*- coding: utf-8 -*-
"""统一闸 gate_manager HTTP 钩子面（_b P3）

对外暴露（供 sl 之外的外挂改进服务消费；sl 内部 gate_manager 走组件形态）：
  GET  /gate-manager/config    闸组合注册表 + 各闸开关状态 + ck/pk 挂载态
  PATCH /gate-manager/config   切换 active combo / meta 闸 on/off/auto

ck 推理闸（/chatgate）与 pk 人闸（/pipelines/.../gate）代理端点依赖 ck/pk 内核，
Phase 4 vendored 后补充（本文件 P3 阶段只暴露 gate_manager 自身配置面）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from ..services.gate_manager import get_gate_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gate"])


@router.get("/gate-manager/config", summary="Gate manager config")
async def get_gate_config() -> dict:
    """查询闸组合注册表 + 各闸开关状态 + ck/pk 挂载态"""
    return get_gate_manager().get_config()


@router.patch("/gate-manager/config", summary="Gate manager config update")
async def patch_gate_config(payload: dict[str, Any]) -> dict:
    """切换 active combo / meta 闸开关

    payload:
      {"active_combo": "decision_approval"}  → 切换闸组合
      {"meta_gate": "on"|"off"|"auto"}        → 控制 ck 闸开关
    """
    gm = get_gate_manager()
    if "active_combo" in payload:
        try:
            gm.set_active_combo(payload["active_combo"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if "meta_gate" in payload:
        resp = gm.set_meta_gate(payload["meta_gate"])
        if resp.verdict == "invalid":
            raise HTTPException(status_code=400, detail=resp.reason)
    return gm.get_config()
