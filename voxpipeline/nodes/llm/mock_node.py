# voxpipeline/nodes/llm/mock_node.py
import asyncio
from voxpipeline.core.base_node import BaseNode
from voxpipeline.core.datatypes import TextChunk


class MockLLMNode(BaseNode):
    def __init__(self):
        super().__init__(name="Mock_LLM")

    async def process(self, input_stream: asyncio.Queue, output_stream: asyncio.Queue):
        while True:
            chunk: TextChunk = await input_stream.get()

            if chunk.is_last:
                await output_stream.put(chunk)
                break

            if chunk.text.strip():
                await self.emit_state("thinking", "大模型正在生成长篇大论...")

                # 模拟 LLM 吐出很长的一段话
                long_reply = f"我已经听到了你说的：“{chunk.text}”。关于这个问题，我想给你背诵一首长诗。白日依山尽，黄河入海流。欲穷千里目，更上一层楼。春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少。"

                # 模拟流式一个字一个字吐出
                for char in long_reply:
                    if self._cancel_event.is_set():
                        break  # 如果被打断，立马闭嘴
                    await output_stream.put(TextChunk(text=char, is_last=False))
                    await asyncio.sleep(0.05)  # 模拟推理延迟

                # 结算
                await output_stream.put(TextChunk(text="", is_last=False))