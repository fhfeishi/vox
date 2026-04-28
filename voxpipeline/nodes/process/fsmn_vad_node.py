# voxpipeline/nodes/process/vad_node.py
import asyncio
import numpy as np
from loguru import logger
from funasr import AutoModel

from voxpipeline.core.base_node import BaseNode
from voxpipeline.core.datatypes import AudioChunk

from configs.config import settings

# 全局单例，避免多次实例化 ONNX Runtime
_GLOBAL_VAD_MODEL = None


def get_vad_model():
    global _GLOBAL_VAD_MODEL
    if _GLOBAL_VAD_MODEL is None:
        logger.info("⏳ 正在加载本地 VAD 模型 (ONNX)...")
        _GLOBAL_VAD_MODEL = AutoModel(
            model=settings.fsmn_vad_path,
            # model_revision="v2.0.4",
            disable_update=True,
            device="cpu"  # VAD 极度轻量，强制用 CPU 即可，省下显存
        )
        logger.success("✅ 本地 VAD 模型加载完成！")
    return _GLOBAL_VAD_MODEL


class FsmnVADNode(BaseNode):
    def __init__(self):
        super().__init__(name="FSMN_VAD")
        self.vad_model = None

        # 状态机变量
        self.is_speaking = False
        self.cache = {}  # FunASR 流式推理必须维护的上下文缓存

    async def process(self, input_stream: asyncio.Queue, output_stream: asyncio.Queue):
        self.vad_model = get_vad_model()
        self.cache = {}
        self.is_speaking = False

        while True:
            try:
                chunk: AudioChunk = await input_stream.get()

                if chunk.is_last:
                    # 收到全局结束信号，清理并透传
                    await output_stream.put(chunk)
                    break

                # 1. 转换数据类型：FunASR 期望 float32 的波形数据 ( -1.0 到 1.0 )
                # 这里我们假设 chunk.data 是 16-bit PCM bytes
                audio_array = np.frombuffer(chunk.data, dtype=np.int16).astype(np.float32) / 32768.0

                # 2. 调用 VAD 推理 (扔进线程池，防止阻塞 Asyncio 事件循环)
                res = await asyncio.to_thread(
                    self.vad_model.generate,
                    input=audio_array,
                    cache=self.cache,
                    is_final=False,
                    chunk_size=200  # 标准 200ms 步进
                )

                # 3. 解析 FunASR FSMN-VAD 的输出状态
                # res 的典型结构: [{'value': [[start_ms, end_ms], ...]}]
                # 流式模式下，如果识别到人声开始，会返回 [start, -1]
                # 如果人声结束，会返回 [start, end]

                vad_segments = res[0].get("value", []) if res else []

                # 状态机判断逻辑
                current_speaking = self._check_speaking_state(vad_segments)

                if current_speaking:
                    if not self.is_speaking:
                        # 【状态跳变】静音 -> 人声
                        self.is_speaking = True
                        await self.emit_state("vad_start", "🎤 检测到人声，开始录音")

                    # 人声期间：无条件透传音频给 ASR 节点
                    await output_stream.put(chunk)

                else:
                    if self.is_speaking:
                        # 【状态跳变】人声 -> 静音 (断句触发点！)
                        self.is_speaking = False
                        await self.emit_state("vad_end", "⏹️ 人声结束，触发 ASR 结算")

                        # 核心动作：向 ASR 注入一段特殊的 "纯静音 Chunk"，强制 ASR 吐出最终识别结果
                        stop_chunk = AudioChunk(data=b"\x00" * 3200, is_last=False)
                        await output_stream.put(stop_chunk)
                    else:
                        # 持续静音中：直接丢弃音频块，节省 ASR 算力！
                        pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VAD 节点处理异常: {e}")
                break

    def _check_speaking_state(self, segments) -> bool:
        """
        解析 FunASR 流式输出，判断当前是否有人声。
        如果有未闭合的区间 (如 [start, -1])，说明正在说话。
        """
        if not segments:
            return self.is_speaking  # 维持上一次的状态

        # 获取最后一个分段
        last_segment = segments[-1]

        # -1 表示这句话还没说完
        if last_segment[1] == -1:
            return True
        else:
            # 已经闭合，说明静音了
            return False