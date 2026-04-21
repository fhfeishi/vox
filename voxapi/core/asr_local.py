# -*- coding: utf-8 -*-
# voxapi/core/asr_local.py
import asyncio
import numpy as np
from funasr import AutoModel
from loguru import logger

from configs.config import settings


# 全局单例模型，避免每次 WebSocket 连接都重新加载几百MB的模型
_GLOBAL_ASR_MODEL = None

def get_asr_model():
    global _GLOBAL_ASR_MODEL
    if _GLOBAL_ASR_MODEL is None:
        # 你可以把 "paraformer-zh-streaming" 替换为你本地的模型绝对路径
        model_path = r"D:\local_models\iic--paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
        logger.info(f"⏳ 正在加载本地 FunASR 模型: {model_path} ...")
        _GLOBAL_ASR_MODEL = AutoModel(
            model=model_path,
            device="cuda:0", # 如果没有 GPU，请改为 "cpu"
            disable_update=False,
            trust_remote_code=True
        )
        logger.success("✅ 本地 FunASR 模型加载完成！")
    return _GLOBAL_ASR_MODEL

class StreamASR:
    def __init__(self, debug_audio: bool = False):
        self.loop = asyncio.get_running_loop()
        self.msg_queue = asyncio.Queue()  # 吐给 pipeline 的结果队列
        self._audio_queue = asyncio.Queue() # 接收前端音频的内部队列
        
        self.model = None
        self._running = False
        self._process_task = None
        
        # 流式状态
        self.cache = {}
        self.chunk_size = [0, 10, 5]
        self._model_chunk_stride = self.chunk_size[1] * 960
        self._audio_buffer = np.array([], dtype=np.float32)
        self._full_text = ""

    def start(self):
        if self._running: return
        self.model = get_asr_model()
        
        # 初始化状态
        self.cache = {}
        self._audio_buffer = np.array([], dtype=np.float32)
        self._full_text = ""
        
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        logger.success("✅ 本地 ASR 引擎已启动，等待音频流...")

    def send_audio(self, audio_data: bytes):
        if not self._running: return
        if not audio_data: return
        
        # 拦截前端 VAD 传来的 speech_end 信号 (管线里写死的是 3200 字节的 \x00)
        is_final = (audio_data == b"\x00" * 3200)
        self._audio_queue.put_nowait((audio_data, is_final))

    async def stop(self):
        if not self._running: return
        self._running = False
        if self._process_task:
            self._process_task.cancel()
        logger.info("🛑 本地 ASR 引擎已停止")

    async def _process_loop(self):
        """后台异步处理队列中的音频，防止拥塞"""
        while self._running:
            try:
                audio_data, is_final = await self._audio_queue.get()
                
                # 将密集的 CPU/GPU 推理抛入线程池，释放主事件循环
                partial_text, is_done = await asyncio.to_thread(self._infer_chunk, audio_data, is_final)
                
                # 如果有新字蹦出来，立刻推给前端显示
                if partial_text:
                    await self.msg_queue.put({"type": "asr_partial", "text": self._full_text})
                    
                # 如果收到静音断句，结算整句话
                if is_done and self._full_text.strip():
                    await self.msg_queue.put({"type": "asr_final", "text": self._full_text})
                    self._full_text = ""  # 重置，准备听下一句
                    self.cache = {}       # 清理模型状态记忆
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ASR 处理异常: {e}")

    def _infer_chunk(self, audio_data: bytes, is_final: bool):
        """真正的底层模型推理"""
        if audio_data and not is_final:
            if len(audio_data) % 2 != 0: audio_data = audio_data[:-1]
            frame = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            self._audio_buffer = np.concatenate([self._audio_buffer, frame])

        current_chunk_text = ""
        is_done = False
        
        while self._audio_buffer.size >= self._model_chunk_stride or (is_final and self._audio_buffer.size > 0):
            if is_final and self._audio_buffer.size < self._model_chunk_stride:
                input_chunk = self._audio_buffer
                self._audio_buffer = np.array([], dtype=np.float32)
            else:
                input_chunk = self._audio_buffer[: self._model_chunk_stride]
                self._audio_buffer = self._audio_buffer[self._model_chunk_stride:]

            current_is_final = is_final and (self._audio_buffer.size == 0)

            try:
                res = self.model.generate(
                    input=input_chunk,
                    cache=self.cache,
                    is_final=current_is_final,
                    chunk_size=self.chunk_size,
                    encoder_chunk_look_back=2,
                    decoder_chunk_look_back=1,
                )
                if res and isinstance(res, list) and len(res) > 0 and "text" in res[0]:
                    new_text = res[0]["text"].strip()
                    if new_text:
                        current_chunk_text += new_text
                        self._full_text += new_text
            except Exception as e:
                logger.error(f"FunASR 推理出错: {e}")
                break
                
            if current_is_final:
                is_done = True
                
        # 兜底：如果纯静音没有触发循环，但传了 is_final
        if is_final and self._audio_buffer.size == 0:
            is_done = True
            
        return current_chunk_text, is_done


