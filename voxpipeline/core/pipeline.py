# voxpipeline/core/pipeline.py
import asyncio
from typing import List
from voxpipeline.core.base_node import BaseNode
from loguru import logger


class AudioPipeline:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.nodes: List[BaseNode] = []
        self.queues: List[asyncio.Queue] = []
        self._tasks: List[asyncio.Task] = []

    def add_node(self, node: BaseNode):
        self.nodes.append(node)
        return self

    def _setup_queues(self):
        """根据节点的数量，创建 N+1 个队列将它们串联"""
        self.queues = [asyncio.Queue() for _ in range(len(self.nodes) + 1)]

    async def run(self):
        """启动整条管线"""
        if not self.nodes:
            raise ValueError("Pipeline 中没有节点！")

        self._setup_queues()
        logger.info(f"[Pipeline {self.session_id}] 正在启动，包含 {len(self.nodes)} 个节点...")

        # 为每个节点创建一个并发任务
        for i, node in enumerate(self.nodes):
            in_q = self.queues[i]
            out_q = self.queues[i + 1]
            task = asyncio.create_task(node.process(input_stream=in_q, output_stream=out_q))
            self._tasks.append(task)

        # 注意：这里我们不 await tasks，而是让它们在后台一直跑，
        # 外部程序通过往 self.queues[0] 塞数据来驱动管线。

    async def interrupt_and_flush(self):
        """
        【新增】全局打断与清洗机制 (The Big Flush)
        """
        logger.warning(f"🌪️ [Pipeline {self.session_id}] 触发全局打断！正在清洗管线...")

        # 1. 向所有下游节点广播打断信号
        for node in self.nodes:
            # VAD 和 ASR 通常是听觉节点，不需要打断（它们正在听用户的新指令）
            # 我们主要打断思考（LLM）和表达（TTS）节点
            if "LLM" in node.name or "TTS" in node.name:
                node.trigger_cancel()

        # 2. 清空所有连接节点的 Queue（极其关键！）
        # 如果不清空，LLM 被打断前生成的最后半句话，还会被 TTS 捡起来读掉。
        for q in self.queues:
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                except asyncio.QueueEmpty:
                    break

        # 3. 稍作等待，让节点内部彻底退出当前的计算循环
        await asyncio.sleep(0.1)

        # 4. 松开刹车，恢复管线接收新数据的能力
        for node in self.nodes:
            node.clear_cancel()

        logger.success(f"✨ [Pipeline {self.session_id}] 管线清洗完毕，准备就绪。")


    async def stop(self):
        """优雅关闭管线"""
        logger.info(f"[Pipeline {self.session_id}] 正在停止...")
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    @property
    def entry_queue(self) -> asyncio.Queue:
        """获取管线的第一级输入队列（外部送入 PCM 数据的地方）"""
        return self.queues[0]

    @property
    def exit_queue(self) -> asyncio.Queue:
        """获取管线的最后一级输出队列（提取最终结果的地方）"""
        return self.queues[-1]