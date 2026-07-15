"""异步数据库写入协程模块"""

import asyncio
from typing import Any, Coroutine

from ..database import save_session_snapshot
from ..models.session import Session


class DBWriter:
    """异步数据库写入器"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Coroutine[Any, Any, None]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """启动写入协程"""
        self._running = True
        self._task = asyncio.create_task(self._process_queue())

    async def stop(self) -> None:
        """停止写入协程"""
        self._running = False
        # 等待队列中的任务完成
        await self._queue.join()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _process_queue(self) -> None:
        """处理写入队列"""
        while self._running:
            try:
                # 等待任务，带超时以便检查 _running 状态
                coro = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                try:
                    await coro
                except Exception as e:
                    # 记录错误但不中断处理
                    print(f"DB Writer error: {e}")
                finally:
                    self._queue.task_done()
            except asyncio.TimeoutError:
                continue

    async def enqueue_snapshot_update(self, session: Session) -> None:
        """将快照更新任务加入队列"""
        # 只保存永久区 + 最后1条交互
        last_interaction = list(session.temp_history)[-2:] if session.temp_history else []

        coro = save_session_snapshot(
            session_id=session.session_id,
            permanent_system_prompt=session.permanent_system_prompt,
            loaded_docs=session.loaded_docs,
            last_interaction=last_interaction,
            last_active_time=session.last_active,
        )
        await self._queue.put(coro)
        session.snapshot_dirty = False

    @property
    def queue_size(self) -> int:
        """获取队列大小"""
        return self._queue.qsize()
