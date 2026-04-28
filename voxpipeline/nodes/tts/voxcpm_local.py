# voxpipeline/nodes/tts/voxcpm_local.py
import asyncio
import numpy as np
from loguru import logger

from voxpipeline.core.base_node import BaseNode
from voxpipeline.core.datatypes import AudioChunk, TextChunk
from voxapi.core.tts_local import get_tts_model, VOICE_ALIASES  # 复用你的模型加载逻辑


class VoxCPMTTSNode(BaseNode):
    def __init__(self, voice_target="speaker"):
        super().__init__(name="VoxCPM_TTS")
        self.model = get_tts_model()
        self.voice_target = voice_target
        # 你可以根据 VOICE_ALIASES 逻辑去拿真实的 wav 路径
        self.reference_wav_path = None

        # 触发合成的断句标点
        self.punctuations = set("。！？；.!?;\n")

    async def process(self, input_stream: asyncio.Queue, output_stream: asyncio.Queue):
        text_buffer = ""
        loop = asyncio.get_running_loop()
        await self.emit_state("ready", "TTS 模型已加载")

        while True:
            try:
                # 1. 监听全局打断信号
                if self._cancel_event.is_set():
                    text_buffer = ""  # 清空还没念出来的文字缓存
                    await asyncio.sleep(0.05)  # 挂起等待管线清洗完成
                    continue

                # 2. 从上游（LLM）获取文本流
                chunk: TextChunk = await input_stream.get()

                if chunk.is_last:
                    # 会话结束，结算最后没标点的残余句子
                    if text_buffer.strip() and not self._cancel_event.is_set():
                        await self._synthesize_sentence(text_buffer, output_stream, loop)
                    await output_stream.put(AudioChunk(data=b"", is_last=True))
                    break

                text_buffer += chunk.text

                # 3. 滑窗断句逻辑
                last_punct_idx = -1
                for i, char in enumerate(text_buffer):
                    if char in self.punctuations:
                        last_punct_idx = i

                if last_punct_idx != -1:
                    sentence = text_buffer[:last_punct_idx + 1]
                    text_buffer = text_buffer[last_punct_idx + 1:]
                    if sentence.strip() and not self._cancel_event.is_set():
                        await self._synthesize_sentence(sentence, output_stream, loop)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TTS 节点异常: {e}")
                break

    async def _synthesize_sentence(self, sentence: str, output_stream: asyncio.Queue, loop):
        """将同步的生成逻辑丢入线程池，防止阻塞事件循环"""
        await self.emit_state("synthesizing", f"正在合成: {sentence}")

        def _run_inference():
            try:
                kwargs = {"text": sentence}
                if self.reference_wav_path:
                    kwargs["reference_wav_path"] = self.reference_wav_path

                # 核心：流式推理生成
                for chunk in self.model.generate_streaming(**kwargs):
                    # 【史诗级防御】在 GPU 推理的 for 循环里监听刹车！
                    # 如果用户打断了，直接 break 抛弃后面的生成，瞬间释放 GPU 算力！
                    if self._cancel_event.is_set():
                        logger.warning(f"✂️ [TTS] GPU 合成被强行熔断: {sentence[:5]}...")
                        break

                    # float32 转 16-bit PCM
                    pcm_bytes = (chunk * 32767).astype(np.int16).tobytes()

                    # 线程安全地推入管线输出队列
                    loop.call_soon_threadsafe(output_stream.put_nowait, AudioChunk(data=pcm_bytes, is_last=False))

            except Exception as e:
                logger.error(f"VoxCPM 推理异常: {e}")

        await asyncio.to_thread(_run_inference)
        await self.emit_state("idle", "合成完毕")