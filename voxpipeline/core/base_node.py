# voxpipeline/core/base_node.py
import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional
from loguru import logger


class BaseNode(ABC):
    def __init__(self, name: str):
        self.name = name
        self.state_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

        # 【新增】打断信号标志位
        self._cancel_event = asyncio.Event()

    def set_state_callback(self, callback):
        self.state_callback = callback

    async def emit_state(self, status: str, message: str = ""):
        if self.state_callback:
            await self.state_callback(self.name, status, message)

    def trigger_cancel(self):
        """【新增】拉下急刹车，向节点内部发出打断信号"""
        logger.warning(f"🛑 [{self.name}] 收到全局打断信号！")
        self._cancel_event.set()

    def clear_cancel(self):
        """【新增】松开刹车，准备迎接下一轮对话"""
        self._cancel_event.clear()

    @abstractmethod
    async def process(self, input_stream: asyncio.Queue, output_stream: asyncio.Queue):
        pass