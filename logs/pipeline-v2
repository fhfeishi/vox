import json
import asyncio
from loguru import logger
from voxapi.core.asr_api import StreamASR
from voxapi.core.llm_api import QwenEngine
from voxapi.core.tts_api import TTSEngine

# ─────────────────────────────────────────────────────────────────────────────
# 采集阈值常量
# 16000 Hz × 2 bytes × 秒数
# ─────────────────────────────────────────────────────────────────────────────
PCM_BYTES_PER_SEC = 16000 * 2          # 32 000 bytes / s
ENROLL_TRIGGER_BYTES = PCM_BYTES_PER_SEC * 5   # 5 秒 → 触发克隆（API 要求 ≥3s，推荐 5s）
ENROLL_MAX_BYTES     = PCM_BYTES_PER_SEC * 10  # 最多保存 10 秒


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
        self.collecting_audio    = True
        self.is_speaker_enrolled = False
        self._enrollment_pending = False   # ★ 新增：防止重复提交 & 支撑失败重试

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

        if self.collecting_audio and len(self.speaker_buffer) < ENROLL_MAX_BYTES:
            self.speaker_buffer.extend(audio_data)

    async def process_control(self, control_msg: str):
        try:
            data = json.loads(control_msg)
            msg_type = data.get("type")

            if msg_type == "speech_start":
                if self.state == "SLEEPING":
                    return
                if (self.llm_task and not self.llm_task.done()) or self.state == "SPEAKING":
                    logger.warning("🛑 [Pipeline] 用户插话，打断当前输出。")
                    await self._cancel_output()
                self.state = "LISTENING"
                if not self.asr._running:
                    self.asr.start()

            elif msg_type == "speech_end":
                if self.asr._running:
                    self.asr.send_audio(b"\x00" * 3200)

        except Exception as exc:
            logger.error(f"控制消息处理异常: {exc}")

    # ── 内部：打断辅助 ────────────────────────────────────────

    async def _cancel_output(self):
        if self.llm_task and not self.llm_task.done():
            self.llm_task.cancel()
        if self.audio_task and not self.audio_task.done():
            self.audio_task.cancel()
        await self.ws.send_json({"type": "stop_audio"})
        if self.tts.audio_queue:
            while not self.tts.audio_queue.empty():
                try:
                    self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    # ── 核心路由 ──────────────────────────────────────────────

    async def _message_router(self):
        while True:
            try:
                msg = await self.asr.msg_queue.get()
                await self.ws.send_json(msg)
                self.asr.msg_queue.task_done()

                if msg["type"] != "asr_final":
                    continue

                text: str = msg["text"]
                logger.info(f"📝 [ASR] 识别结果: {text!r}")

                # ① 首次完整识别后，尝试异步克隆用户声音
                # ★ 修复：加上 _enrollment_pending 防重；不再在此处关闭 collecting_audio
                if (self.collecting_audio
                        and not self._enrollment_pending
                        and len(self.speaker_buffer) >= ENROLL_TRIGGER_BYTES):
                    self._enrollment_pending = True
                    asyncio.create_task(self._enroll_current_speaker())

                # ② 唤醒词拦截
                if self.state == "SLEEPING":
                    if any(w in text for w in ["百变", "你好", "开机"]):
                        logger.success("⏰ [Pipeline] 检测到唤醒词！")
                        self.state = "IDLE"
                        await self.ws.send_json({"type": "woken_up"})
                        welcome = (
                            "你好啊，我是百变！我已经准备好了，"
                            "你可以让我模仿雷军、易中天，或者你自己的声音哦。"
                        )
                        self.llm_task = asyncio.create_task(self._play_system_message(welcome))
                    continue

                # ③ 关机词拦截
                if any(w in text for w in ["关机", "退出", "休息"]):
                    self.llm_task = asyncio.create_task(self._execute_shutdown())
                    continue

                # ④ 正常对话
                self.state = "THINKING"
                if self.llm_task and not self.llm_task.done():
                    self.llm_task.cancel()
                self.llm_task = asyncio.create_task(self._run_llm_and_tts(text))

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Router 异常: {exc}")

    # ── 用户声纹克隆 ──────────────────────────────────────────

    async def _enroll_current_speaker(self):
        """将已积累的 PCM buffer 打包提交克隆，成功后注册为 'speaker' 音色。"""
        logger.info(
            f"🎤 [Pipeline] 提交用户声纹克隆 "
            f"({len(self.speaker_buffer) / PCM_BYTES_PER_SEC:.1f} 秒)..."
        )
        pcm_snapshot = bytes(self.speaker_buffer)
        voice_id = await self.tts.enroll_voice(pcm_snapshot, "speaker")
        if voice_id:
            self.is_speaker_enrolled = True
            self.collecting_audio = False     # ★ 只在成功时关闭采集
            self._enrollment_pending = False
            await self.ws.send_json({"type": "voice_enrolled", "name": "speaker"})
            logger.success("✅ [Pipeline] 用户声纹克隆完成，可用 'speaker' 音色。")
        else:
            self._enrollment_pending = False  # ★ 失败时重置，允许下次重试
            logger.warning("⚠️  [Pipeline] 用户声纹克隆失败，等待更多语音后重试。")

    # ── TTS 音频发送 ──────────────────────────────────────────

    async def _audio_sender(self):
        while True:
            try:
                chunk = await self.tts.audio_queue.get()
                if chunk is None:
                    break
                if self.state == "SPEAKING":
                    await self.ws.send_bytes(chunk)
            except asyncio.CancelledError:
                break

    # ── 系统消息播放 ──────────────────────────────────────────

    async def _play_system_message(self, text: str):
        self.state = "SPEAKING"
        try:
            await self.ws.send_json({"type": "llm_text", "text": text})
            self.tts.start_session(self.current_voice)
            self.audio_task = asyncio.create_task(self._audio_sender())
            self.tts.send_text(text)
            self.tts.finish_session()
            await self.audio_task
        except asyncio.CancelledError:
            pass
        finally:
            self.state = "IDLE"

    # ── 关机流程 ──────────────────────────────────────────────

    async def _execute_shutdown(self):
        await self._play_system_message("好的，百变这就去休息啦。想我的时候随时叫我开机哦，拜拜！")
        await asyncio.sleep(3.5)
        await self.ws.send_json({"type": "shutdown"})
        self.state = "SLEEPING"
        logger.info("💤 [Pipeline] 进入休眠，等待唤醒词...")

    # ── LLM + TTS 联动 ───────────────────────────────────────

    async def _run_llm_and_tts(self, text: str):
        self.state = "SPEAKING"
        tts_started = False
        try:
            async for chunk in self.llm.generate_stream(text):
                ctype = chunk.get("type")

                if ctype == "voice_ctrl":
                    target = chunk["target"]
                    self.current_voice = target
                    await self.ws.send_json({"type": "voice_changed", "voice": target})
                    logger.info(f"🔀 [Pipeline] 切换音色 → {target}")

                elif ctype == "text_chunk":
                    if not tts_started:
                        self.tts.start_session(self.current_voice)
                        self.audio_task = asyncio.create_task(self._audio_sender())
                        tts_started = True
                    self.tts.send_text(chunk["text"])
                    await self.ws.send_json({"type": "llm_text", "text": chunk["text"]})

            if tts_started:
                self.tts.finish_session()
                if self.audio_task:
                    await self.audio_task

        except asyncio.CancelledError:
            if self.audio_task and not self.audio_task.done():
                self.audio_task.cancel()
        except Exception as exc:
            logger.error(f"LLM/TTS 运行异常: {exc}")
        finally:
            self.state = "IDLE"