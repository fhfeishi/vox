# voxapi/pipeline.py
import os
import wave
import json
import asyncio
import re
from loguru import logger
from voxapi.core.asr_api import StreamASR
from voxapi.core.llm_api import QwenEngine
from voxapi.core.tts_api import TTSEngine

# ─────────────────────────────────────────────────────────────────────────────
# 采集阈值常量
# ─────────────────────────────────────────────────────────────────────────────
PCM_BYTES_PER_SEC = 16000 * 2          # 32 000 bytes / s
ENROLL_TRIGGER_BYTES = PCM_BYTES_PER_SEC * 3   # 至少 3 秒才允许克隆
ENROLL_MAX_BYTES     = PCM_BYTES_PER_SEC * 8   # 滑动窗口上限：只保留最新的 8 秒声音

class SessionPipeline:
    def __init__(self, websocket):
        self.ws = websocket
        self.state = "SLEEPING"

        self.asr = StreamASR()
        self.llm = QwenEngine()
        self.tts = TTSEngine()

        self.router_task: asyncio.Task | None = None
        self.llm_task:    asyncio.Task | None = None
        self.audio_task:  asyncio.Task | None = None

        self.current_voice = "default"

        # ── 用户声纹采集状态 ──────────────────────────────────
        self.speaker_buffer      = bytearray()
        self.is_speaker_enrolled = False
        self._enrollment_pending = False   

        # ── 本地极速音频缓存 ──────────────────────────────────
        self.system_audio_cache = {}
        self._load_system_audios()

    def _load_system_audios(self):
        """将硬盘上的 wav 提示音直接读取为 PCM 内存流，实现 0 延迟播放"""
        base_path = "locals/system_audio"
        os.makedirs(base_path, exist_ok=True)
        files = {
            "shutdown_female": os.path.join(base_path, "shutdown_female.wav"),
            "shutdown_male": os.path.join(base_path, "shutdown_male.wav")
        }
        for key, path in files.items():
            if os.path.exists(path):
                try:
                    with wave.open(path, 'rb') as wf:
                        self.system_audio_cache[key] = wf.readframes(wf.getnframes())
                    logger.info(f"🔈 [LocalAudio] 极速系统语音已就绪: {key}")
                except Exception as e:
                    logger.error(f"❌ [LocalAudio] 加载 {path} 失败: {e}")

    # ── 生命周期 ──────────────────────────────────────────────

    async def start(self):
        await self.tts.preload_local_refs()
        self.router_task = asyncio.create_task(self._message_router())
        logger.info("🧠 [Pipeline] 管线已就绪，进入休眠监听...")

    async def stop(self):
        for task in (self.router_task, self.llm_task, self.audio_task):
            if task and not task.done():
                task.cancel()
        await self.asr.stop()

    # ── 音频 / 控制入口 ───────────────────────────────────────

    async def process_audio(self, audio_data: bytes):
        if not self.asr._running:
            self.asr.start()
        self.asr.send_audio(audio_data)

        # 只在真正聆听时收集高纯度音频
        if self.state == "LISTENING":
            self.speaker_buffer.extend(audio_data)
            if len(self.speaker_buffer) > ENROLL_MAX_BYTES:
                self.speaker_buffer = self.speaker_buffer[-ENROLL_MAX_BYTES:]

    async def process_control(self, control_msg: str):
        try:
            data = json.loads(control_msg)
            msg_type = data.get("type")

            if msg_type == "speech_start":
                if self.state == "SLEEPING": return
                # 暴力打断拦截
                if (self.llm_task and not self.llm_task.done()) or self.state in ["SPEAKING", "THINKING"]:
                    logger.warning("🛑 [Pipeline] 接收到插话信号，强制截断输出。")
                    await self._cancel_output()
                self.state = "LISTENING"
                if not self.asr._running:
                    self.asr.start()

            elif msg_type == "speech_end":
                if self.asr._running:
                    self.asr.send_audio(b"\x00" * 3200)

        except Exception as exc:
            logger.error(f"控制消息处理异常: {exc}")

    async def _cancel_output(self):
        if self.llm_task and not self.llm_task.done():
            self.llm_task.cancel()
        if self.audio_task and not self.audio_task.done():
            self.audio_task.cancel()
        await self.ws.send_json({"type": "stop_audio"})
        if self.tts.audio_queue:
            while not self.tts.audio_queue.empty():
                try: self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty: break

    # ── 核心路由 ──────────────────────────────────────────────

    async def _message_router(self):
        while True:
            try:
                msg = await self.asr.msg_queue.get()
                await self.ws.send_json(msg)
                self.asr.msg_queue.task_done()

                # 语义级防误打断
                if msg["type"] == "asr_partial":
                    text = msg.get("text", "")
                    clean_text = re.sub(r'[^\w\s]', '', text).strip()
                    if len(clean_text) >= 1 and self.state in ["SPEAKING", "THINKING"]:
                        logger.warning(f"🛑 [Pipeline] 语义打断生效：确认听到人类语音 '{clean_text}'")
                        await self._cancel_output()
                        self.state = "LISTENING"
                    continue

                if msg["type"] != "asr_final": continue

                text: str = msg["text"]
                logger.info(f"📝 [ASR] 识别结果: {text!r}")

                # 后台静默克隆
                if (not self.is_speaker_enrolled and not self._enrollment_pending 
                    and len(self.speaker_buffer) >= ENROLL_TRIGGER_BYTES):
                    self._enrollment_pending = True
                    asyncio.create_task(self._enroll_current_speaker(force_reclone=False))

                # 唤醒词
                if self.state == "SLEEPING":
                    if any(w in text for w in ["百变", "你好", "开机"]):
                        logger.success("⏰ [Pipeline] 检测到唤醒词！")
                        self.state = "IDLE"
                        await self.ws.send_json({"type": "woken_up"})
                        welcome = "你好啊，我是百变！我已经准备好了，你可以让我模仿雷军、易中天，或者你自己的声音哦。"
                        self.llm_task = asyncio.create_task(self._play_system_message(welcome))
                    continue

                # 关机词 (修复了旧版的自杀 Bug)
                if any(w in text for w in ["关机", "退出", "休息"]):
                    if self.llm_task and not self.llm_task.done():
                        self.llm_task.cancel()
                    self.llm_task = asyncio.create_task(self._execute_shutdown())
                    continue

                # 正常对话
                self.state = "THINKING"
                if self.llm_task and not self.llm_task.done():
                    self.llm_task.cancel()
                self.llm_task = asyncio.create_task(self._run_llm_and_tts(text))

            except asyncio.CancelledError: break
            except Exception as exc: logger.error(f"Router 异常: {exc}")

    # ── 用户声纹克隆 ──────────────────────────────────────────

    async def _enroll_current_speaker(self, force_reclone: bool = False):
        if len(self.speaker_buffer) < ENROLL_TRIGGER_BYTES:
            self._enrollment_pending = False
            return
            
        logger.info(f"🎤 [Pipeline] 提交用户声纹更新...")
        pcm_snapshot = bytes(self.speaker_buffer)
        voice_id = await self.tts.enroll_voice(pcm_snapshot, "speaker", force_reclone=force_reclone)
        
        if voice_id:
            self.is_speaker_enrolled = True
            await self.ws.send_json({"type": "voice_enrolled", "name": "speaker"})
            logger.success("✅ [Pipeline] 用户实时声纹已就绪！")
        else:
            logger.warning("⚠️  [Pipeline] 用户声纹克隆失败。")
        self._enrollment_pending = False

    async def _audio_sender(self):
        while True:
            try:
                chunk = await self.tts.audio_queue.get()
                if chunk is None: break
                if self.state == "SPEAKING":
                    await self.ws.send_bytes(chunk)
            except asyncio.CancelledError: break

    async def _play_system_message(self, text: str):
        self.state = "SPEAKING"
        try:
            await self.ws.send_json({"type": "llm_text", "text": text})
            self.tts.start_session(self.current_voice)
            self.audio_task = asyncio.create_task(self._audio_sender())
            self.tts.send_text(text)
            self.tts.finish_session()
            await self.audio_task
        except asyncio.CancelledError: pass
        finally: self.state = "IDLE"

    # ── 关机流程 (本地缓存极速响应) ──────────────────────────────────

    async def _execute_shutdown(self):
        # 先安全停止音频队列
        if self.audio_task and not self.audio_task.done():
            self.audio_task.cancel()
        await self.ws.send_json({"type": "stop_audio"})
        if self.tts.audio_queue:
            while not self.tts.audio_queue.empty():
                try: self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty: break
        await asyncio.sleep(0.2)
        
        male_voices = ["男声", "男的", "男生", "龙老铁", "雷军", "leijun", "易中天", "yizhongtian", "书记", "shuji"]
        is_male = self.current_voice in male_voices
        cache_key = "shutdown_male" if is_male else "shutdown_female"
        
        if cache_key in self.system_audio_cache:
            logger.info(f"⚡ [Pipeline] 命中内存音频池，极速播放关机音: {cache_key}")
            self.state = "SPEAKING"
            await self.ws.send_json({"type": "llm_text", "text": "好的，百变这就去休息啦。随时叫我，拜拜！"})
            pcm_bytes = self.system_audio_cache[cache_key]
            chunk_size = 4800 
            for i in range(0, len(pcm_bytes), chunk_size):
                await self.ws.send_bytes(pcm_bytes[i:i+chunk_size])
                await asyncio.sleep(0.09) 
            self.state = "IDLE"
        else:
            logger.warning("🐌 [Pipeline] 未找到本地关机音频，走在线 TTS...")
            await self._play_system_message("好的，百变这就去休息啦。随时叫我，拜拜！")

        # 播完后立刻下发指令，倒计时交给前端 AudioContext 算
        await self.ws.send_json({"type": "shutdown"})
        self.state = "SLEEPING"
        logger.info("💤 [Pipeline] 已下发关机指令，进入休眠监听...")

    # ── LLM + TTS 联动 ───────────────────────────────────────

    async def _run_llm_and_tts(self, text: str):
        self.state = "SPEAKING"
        tts_started = False

        async def _generate():
            async for chunk in self.llm.generate_stream(text):
                yield chunk

        try:
            # 15秒大模型防卡死看门狗
            async with asyncio.timeout(15.0):
                async for chunk in _generate():
                    ctype = chunk.get("type")

                    if ctype == "voice_ctrl":
                        target = chunk["target"]
                        self.current_voice = target
                        await self.ws.send_json({"type": "voice_changed", "voice": target})
                        logger.info(f"🔀 [Pipeline] 收到音色切换指令 → {target}")
                        
                        if target in ["speaker", "我", "我的声音", "我自己"]:
                            await self._enroll_current_speaker(force_reclone=True)

                    elif ctype == "text_chunk":
                        if not tts_started:
                            self.tts.start_session(self.current_voice)
                            self.audio_task = asyncio.create_task(self._audio_sender())
                            tts_started = True
                        self.tts.send_text(chunk["text"])
                        await self.ws.send_json({"type": "llm_text", "text": chunk["text"]})

            if tts_started:
                self.tts.finish_session()
                if self.audio_task: await self.audio_task

        except TimeoutError:
            logger.error("🚨 [Pipeline] 大模型 API 响应超时！")
            await self.ws.send_json({"type": "llm_text", "text": "不好意思，刚才网络开小差了，能再说一遍吗？"})
            if self.audio_task and not self.audio_task.done(): self.audio_task.cancel()
        except asyncio.CancelledError:
            if self.audio_task and not self.audio_task.done(): self.audio_task.cancel()
        except Exception as exc:
            logger.error(f"LLM/TTS 运行异常: {exc}")
            await self.ws.send_json({"type": "llm_text", "text": "哎呀，我的大脑出了一点小故障，请稍后再试。"})
        finally:
            self.state = "IDLE"