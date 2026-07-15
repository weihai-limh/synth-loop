"""FastAPI 应用入口"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_database
from .middleware.auth import AuthMiddleware
from .routers import chat, health, anthropic_chat, admin, tasks, packets


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_database()

    # 初始化服务
    chat.init_services()

    # 启动 DB Writer
    await chat.db_writer.start()

    yield

    # 关闭时清理资源
    await chat.db_writer.stop()
    await chat.downstream_llm.close()


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="synth-loop",
        description="分形决策编排引擎",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # v0_1_1 Phase 3: Auth 中间件
    app.add_middleware(AuthMiddleware)

    # 注册路由
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(anthropic_chat.router)
    app.include_router(admin.router)
    app.include_router(tasks.router)
    app.include_router(packets.router)  # v0_1_1 Phase 6: packets API

    return app


# 创建应用实例
app = create_app()
