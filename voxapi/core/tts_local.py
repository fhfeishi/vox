# -*- coding: utf-8 -*-
# voxapi/core/tts_local.py

import os
import io
import wave
import uuid
import asyncio
import numpy as np
import soundfile as sf
from loguru import logger
from voxcpm import VoxCPM
from configs.config import settings

# 全局唯一实例
_GLOBAL_TTS_MODEL = None


def get_tts_model():
    global _GLOBAL_TTS_MODEL
    # model path: voxcpm2_path  voxcpm15_path  voxcpm05_path
    model_path = settings.voxcpm15_path
    if _GLOBAL_TTS_MODEL is None:
        logger.info(f"⏳ [Local TTS] Loading TTS model from {model_path}...")
        _GLOBAL_TTS_MODEL = VoxCPM.from_pretrained(
            model_path,
            load_denoiser=False
        )
        logger.success(f"✅ [Local TTS] Loading TTS model from {model_path} SUCCESS")
    return _GLOBAL_TTS_MODEL


LOCAL_REF_NAMES = ["leijun", "yizhongtian", "shuji", "wuhannvhai"]
VOICE_ALIASES = {
    "雷军": "leijun", "易中天": "yizhongtian", "书记": "shuji", "武汉女孩": "wuhannvhai",
    "我": "speaker", "我的": "speaker", "我自己": "speaker", "我的声音": "speaker",
    # 本地模型不需要区分官方声音，统一映射或使用默认控制指令
}


class LocalTTSEngine:
    # 全局字典保存音色映射：preferred_name -> 本地 wav 绝对路径
    _global_enrolled_voices = {}
    _global_locks = {}

    def __init__(self):
        self.audio_queue = None
        self.text_queue = None
        self._loop = None
        self._worker_task = None
        self._is_running = False

        # 延迟加载模型，确保服务启动时不卡顿
        self.model = get_tts_model()
        self.current_reference_path = None

    @property
    def enrolled_voices(self):
        return LocalTTSEngine._global_enrolled_voices

    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)
        return buf.getvalue()

    async def enroll_voice(self, audio_source: str | bytes, preferred_name: str,
                           force_reclone: bool = False) -> str | None:
        """
        本地克隆逻辑：将参考音频保存到本地磁盘，并记录路径。
        返回本地文件路径作为 "voice_id"。
        """
        if preferred_name not in LocalTTSEngine._global_locks:
            LocalTTSEngine._global_locks[preferred_name] = asyncio.Lock()

        async with LocalTTSEngine._global_locks[preferred_name]:
            if not force_reclone and preferred_name in self.enrolled_voices:
                return self.enrolled_voices[preferred_name]

            logger.info(f"🔄 [Local TTS] 注册参考音色: 『{preferred_name}』")
            try:
                save_dir = os.path.join("locals", "refs", "cloned_voices")
                os.makedirs(save_dir, exist_ok=True)

                # 如果传入的是路径，直接记录
                if isinstance(audio_source, str):
                    if not os.path.exists(audio_source):
                        logger.error(f"❌ [Local TTS] 找不到参考音频文件: {audio_source}")
                        return None
                    file_path = os.path.abspath(audio_source)

                # 如果传入的是二进制(流/上传文件)，保存为 wav
                else:
                    wav_bytes = self._pcm_to_wav(audio_source)
                    file_name = f"{preferred_name}_{uuid.uuid4().hex[:8]}.wav"
                    file_path = os.path.abspath(os.path.join(save_dir, file_name))
                    with open(file_path, "wb") as f:
                        f.write(wav_bytes)

                LocalTTSEngine._global_enrolled_voices[preferred_name] = file_path
                logger.success(f"✅ [Local TTS] 『{preferred_name}』注册成功: {file_path}")
                return file_path
            except Exception as exc:
                logger.error(f"❌ [Local TTS] 音色注册异常: {exc}")
            return None

    async def preload_local_refs(self):
        tasks = []
        for name in LOCAL_REF_NAMES:
            path = os.path.join("locals", "refs", f"ref_{name}.wav")
            if os.path.exists(path):
                tasks.append(self.enroll_voice(path, name))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop_session(self):
        self._is_running = False
        if self.text_queue:
            try:
                self.text_queue.put_nowait(None)
            except Exception:
                pass

    async def start_session(self, voice_target: str):
        self._loop = asyncio.get_running_loop()
        self.audio_queue = asyncio.Queue()
        self.text_queue = asyncio.Queue()
        self._is_running = True

        # 解析音色路径
        internal_target = VOICE_ALIASES.get(voice_target, voice_target)
        self.current_reference_path = self.enrolled_voices.get(internal_target)

        # 启动后台文本处理线程（断句 + 推理）
        self._worker_task = asyncio.create_task(self._process_text_loop())
        logger.info(f"🎙️ [Local TTS] Session Started. Voice: {internal_target}")

    async def send_text(self, text: str):
        """前端/大模型传来的文本流"""
        if self._is_running and text.strip():
            await self.text_queue.put(text)

    async def finish_session(self):
        """文本流结束信号"""
        if self._is_running:
            await self.text_queue.put(None)

    async def _process_text_loop(self):
        """后台异步循环：负责累积文本、断句并送入模型"""
        text_buffer = ""
        # 用于触发合成的标点符号
        punctuations = set("。！？；.!?;\n")

        while self._is_running:
            try:
                text_chunk = await self.text_queue.get()
            except Exception:
                break

            if text_chunk is None:
                # 收到结束信号，合成缓冲区内剩余的所有文本
                if text_buffer.strip():
                    await self._synthesize_and_stream(text_buffer)
                # 向下游发送音频结束信号
                self.audio_queue.put_nowait(None)
                break

            text_buffer += text_chunk

            # 寻找最后一个标点符号进行断句
            last_punct_idx = -1
            for i, char in enumerate(text_buffer):
                if char in punctuations:
                    last_punct_idx = i

            if last_punct_idx != -1:
                # 提取完整句子送去合成
                sentence = text_buffer[:last_punct_idx + 1]
                text_buffer = text_buffer[last_punct_idx + 1:]
                if sentence.strip():
                    await self._synthesize_and_stream(sentence)

    async def _synthesize_and_stream(self, sentence: str):
        """包装 PyTorch 推理过程，防止阻塞主事件循环"""

        def _run_inference():
            try:
                kwargs = {"text": sentence}
                if self.current_reference_path and os.path.exists(self.current_reference_path):
                    kwargs["reference_wav_path"] = self.current_reference_path

                logger.debug(f"▶️ [Local TTS] Synthesizing: {sentence}")

                # VoxCPM 返回 numpy 数组块
                for chunk in self.model.generate_streaming(**kwargs):
                    if not self._is_running:
                        break
                    # 将 float numpy 数组 [-1.0, 1.0] 转换为 16-bit PCM 二进制数据
                    # 以保持与原 tts_api.py 完全一致的下游对接格式
                    pcm_bytes = (chunk * 32767).astype(np.int16).tobytes()

                    # 线程安全地推入异步队列
                    self._loop.call_soon_threadsafe(self.audio_queue.put_nowait, pcm_bytes)
            except Exception as e:
                logger.error(f"❌ [Local TTS] 推理异常: {e}")

        # 使用 asyncio.to_thread 将同步的深度学习模型推理丢到线程池执行
        await asyncio.to_thread(_run_inference)


if __name__ == "__main__":
    async def run_tests():
        logger.info("========== 启动本地 TTS 接口全量测试 ==========")
        engine = LocalTTSEngine()

        # ==========================================
        # 0. 准备阶段：生成测试用的 16kHz Dummy WAV 参考音频
        # ==========================================
        dummy_wav_path = "./locals/refs/lja.wav"
        if not os.path.exists(dummy_wav_path):
            logger.info("创建测试用的 16kHz 参考音频文件...")
            t = np.linspace(0, 1, 16000, endpoint=False)
            # 生成 440Hz 正弦波
            audio_data = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
            with wave.open(dummy_wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_data.tobytes())

        # ==========================================
        # 1. 测试接口: enroll_voice (文件路径模式 & 字节流模式)
        # ==========================================
        logger.info("\n--- [Test 1] 测试音色注册 (enroll_voice) ---")

        # 1.1 文件路径注册
        path_id = await engine.enroll_voice(dummy_wav_path, "test_voice_path")
        assert path_id and os.path.exists(path_id), "❌ 路径模式注册失败！"

        # 1.2 二进制字节流注册 (模拟前端上传或网络流)
        with open(dummy_wav_path, "rb") as f:
            bytes_data = f.read()
        bytes_id = await engine.enroll_voice(bytes_data, "test_voice_bytes")
        assert bytes_id and os.path.exists(bytes_id), "❌ 字节流模式注册失败！"

        # ==========================================
        # 2. 测试接口: preload_local_refs
        # ==========================================
        logger.info("\n--- [Test 2] 测试预加载 (preload_local_refs) ---")
        await engine.preload_local_refs()
        logger.success(f"当前已注册音色列表: {list(engine.enrolled_voices.keys())}")

        # ==========================================
        # 3. 测试接口: Session 生命周期与流式推理
        # start_session -> send_text -> finish_session
        # ==========================================
        logger.info("\n--- [Test 3] 测试流式合成管道 ---")
        await engine.start_session("test_voice_path")

        # 创建后台消费者协程：模拟 WebSocket 客户端接收音频二进制流
        async def audio_consumer():
            frames = []
            while True:
                chunk = await engine.audio_queue.get()
                if chunk is None:  # 明确收到 EOF 信号
                    logger.success("🎧 [Consumer] 收到音频结束信号 (None)")
                    break
                frames.append(chunk)
                logger.debug(f"🎧 [Consumer] 收到音频数据块，大小: {len(chunk)} bytes")
            return b"".join(frames)

        consumer_task = asyncio.create_task(audio_consumer())

        # 模拟前端逐字传入文本（测试标点符号断句机制）
        test_text = "Hello! 这是一个流式文本测试。你听得出断句吗？"
        logger.info(f"发送流式文本: {test_text}")
        for char in test_text:
            await engine.send_text(char)
            await asyncio.sleep(0.02)  # 模拟网络与打字延迟

        logger.info("文本发送完毕，触发 finish_session...")
        await engine.finish_session()

        # 挂起主线程，等待所有音频块处理和接收完毕
        final_pcm_data = await consumer_task

        # 验证结果并导出，方便人工检查听感
        output_wav = "test_streaming_output.wav"
        if final_pcm_data:
            # 获取当前模型的真实采样率以确保保存的 Wav 不变调
            sample_rate = engine.model.tts_model.sample_rate if hasattr(engine.model, 'tts_model') else 24000
            with wave.open(output_wav, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(final_pcm_data)
            logger.success(f"✅ 流式测试通过！完整音频已保存至: {output_wav} (SR: {sample_rate})")
        else:
            logger.error("❌ 测试失败：未能从队列获取到任何音频数据！")

        # ==========================================
        # 4. 测试接口: 紧急中断 (stop_session)
        # ==========================================
        logger.info("\n--- [Test 4] 测试会话强制打断 (stop_session) ---")
        await engine.start_session("test_voice_bytes")
        await engine.send_text("这段话还没有说完，就会被系统直接...")

        # 模拟用户强行打断
        engine.stop_session()

        # 验证队列状态
        assert engine._is_running is False, "❌ _is_running 标志位未能正确重置！"
        logger.success("✅ stop_session 成功熔断后台任务！")

        # 清理生成的临时测试文件（可选）
        if os.path.exists(dummy_wav_path):
            os.remove(dummy_wav_path)
        logger.info("========== 所有接口测试完成 ==========")


    # 运行事件循环
    asyncio.run(run_tests())