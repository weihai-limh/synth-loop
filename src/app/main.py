"""FastAPI 应用入口"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_database, get_shared_db, close_shared_db
from .middleware.auth import AuthMiddleware
from .routers import chat, health, anthropic_chat, admin, tasks, packets, pipeline, runtime_endpoints, artifacts


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_database()

    # _a P2.1: 运行时表种子灌入（幂等）
    from .config import get_config
    from .services.runtime_endpoints import seed_runtime_endpoints
    await seed_runtime_endpoints(get_config())

    # v0_1_2: 初始化全局共享 DB 连接
    await get_shared_db()

    # 初始化服务
    chat.init_services()

    # 启动 DB Writer
    await chat.db_writer.start()

    yield

    # 关闭时清理资源
    await chat.db_writer.stop()
    await chat.downstream_llm.close()
    await close_shared_db()


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="synth-loop",
        description="Fractal decision orchestration engine",
        version="0.1.2",
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
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
    app.include_router(pipeline.router)  # v0_1_2 Phase 4: pipeline API
    app.include_router(runtime_endpoints.router)  # _a P2.1: 运行时表管理 API
    app.include_router(artifacts.router)  # _a P4.3: 数据面下行（相位产物）

    return app


# 创建应用实例
app = create_app()
