# -*- coding: utf-8 -*-
# voxapi/core/asr_local.py
import asyncio
import numpy as np
from dashscope.audio.asr import Recognition
from funasr import AutoModel
from loguru import logger

from configs.config import settings


# 全局单例模型，避免每次 WebSocket 连接都重新加载几百MB的模型
_GLOBAL_ASR_MODEL = None

def get_asr_model():
    global _GLOBAL_ASR_MODEL
    if _GLOBAL_ASR_MODEL is None:
        model_path = settings.paraformer_path
        logger.info(f"⏳ 正在加载本地 asr/tts 模型: {model_path} ...")
        _GLOBAL_ASR_MODEL = AutoModel(
            model=model_path,
            device="cuda:0", # 如果没有 GPU，请改为 "cpu"
            disable_update=True,
            # trust_remote_code=True
        )
        logger.success("✅ 本地 asr/tts 模型加载完成！")
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


if __name__ == "__main__":
    import wave
    import time
    import os


    async def main():
        # 1. 实例化并启动 ASR
        logger.info("正在初始化 StreamASR...")
        asr = StreamASR()
        asr.start()

        # 2. 启动一个后台消费者任务，专门接收并打印 ASR 的识别结果
        async def receive_results():
            while True:
                try:
                    msg = await asr.msg_queue.get()
                    if msg["type"] == "asr_partial":
                        # 使用 \r 实现单行刷新，模拟流式打字效果
                        print(f"\r[部分识别中]: {msg['text']} \033[K", end="")
                    elif msg["type"] == "asr_final":
                        print(f"\r[最终识别结果]: {msg['text']} \033[K\n")
                except asyncio.CancelledError:
                    break

        receiver_task = asyncio.create_task(receive_results())

        # 3. 模拟前端流式发送音频 (读取本地 WAV 文件)
        test_audio_path = "./locals/refs/lja.wav"

        if os.path.exists(test_audio_path):
            logger.info(f"🎤 开始模拟流式发送音频: {test_audio_path}")
            with wave.open(test_audio_path, "rb") as wf:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()

                if sample_rate != 16000 or sampwidth != 2:
                    logger.warning(
                        f"⚠️ 建议使用 16kHz, 16-bit 的音频文件进行测试！当前采样率: {sample_rate}, 位深: {sampwidth * 8}")

                # 模拟每次发送 0.1 秒的音频数据 (16000 Hz * 2 bytes * 1 channel * 0.1s = 3200 bytes)
                chunk_size = int(sample_rate * sampwidth * channels * 0.1)

                while True:
                    data = wf.readframes(chunk_size // sampwidth)  # readframes 的参数是采样点数
                    if not data:
                        break

                    # 将音频片段送入 ASR 队列
                    asr.send_audio(data)

                    # 模拟真实语速：睡眠 0.1 秒
                    await asyncio.sleep(0.1)
        else:
            logger.warning(f"⚠️ 未找到测试文件 {test_audio_path}，将发送随机静音数据进行逻辑测试。")
            # 模拟 2 秒钟的空流（不会有识别结果，但能验证程序不崩溃）
            for _ in range(20):
                # 构造符合要求大小的无声 byte
                asr.send_audio(b"\x00" * 1600)
                await asyncio.sleep(0.1)

        # 4. 发送前端 VAD 拦截到的 speech_end 信号 (你的代码里写死的是 3200 字节的 \x00)
        logger.info("⏹ 发送 VAD 结束信号 (speech_end)...")
        asr.send_audio(b"\x00" * 3200)

        # 5. 给后台一点时间结算最后一句
        await asyncio.sleep(1.5)

        # 6. 平滑关闭并清理
        await asr.stop()
        receiver_task.cancel()
        logger.success("🎉 测试流程结束！")


    # 运行异步事件循环
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户手动中断程序")


