# voxpipeline/nodes/asr/paraformer_node.py
import asyncio
from voxpipeline.core.base_node import BaseNode
from voxpipeline.core.datatypes import AudioChunk, TextChunk
from voxapi.core.asr_local import StreamASR  # 导入你写好的引擎


class ParaformerASRNode(BaseNode):
    def __init__(self):
        super().__init__(name="Local_Paraformer_ASR")
        self.asr_engine = StreamASR()

    async def process(self, input_stream: asyncio.Queue, output_stream: asyncio.Queue):
        # 1. 启动底层引擎
        self.asr_engine.start()
        await self.emit_state("ready", "ASR 模型已就绪")

        # 2. 消费者任务：从底层的 msg_queue 获取识别结果，转换为标准 TextChunk 推向管线下一级
        async def _consume_results():
            while True:
                try:
                    msg = await self.asr_engine.msg_queue.get()
                    if msg["type"] == "asr_partial":
                        await self.emit_state("recognizing", msg["text"])
                    elif msg["type"] == "asr_final":
                        await self.emit_state("recognized", msg["text"])
                        # 只有最终确定的句子，才推入管线交给下游（比如 LLM 或 TTS）
                        await output_stream.put(TextChunk(text=msg["text"], is_last=False))
                except asyncio.CancelledError:
                    break

        consumer_task = asyncio.create_task(_consume_results())

        # 3. 生产者循环：从管线上游接收 AudioChunk，喂给底层引擎
        try:
            while True:
                chunk: AudioChunk = await input_stream.get()

                # 触发底层引擎推理
                self.asr_engine.send_audio(chunk.data)

                if chunk.is_last:
                    # 模拟发送 VAD 结束信号
                    self.asr_engine.send_audio(b"\x00" * 3200)
                    # 通知下游，流结束了
                    await output_stream.put(TextChunk(text="", is_last=True))
                    break
        finally:
            consumer_task.cancel()
            await self.asr_engine.stop()
            await self.emit_state("stopped", "ASR 节点已关闭")