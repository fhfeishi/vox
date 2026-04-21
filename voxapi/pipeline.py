# voxapi/pipeline.py
import os
import wave
import json
import asyncio
import re
from loguru import logger
from voxapi.core.asr_api import StreamASR
from voxapi.core.llm_api import QwenEngine
from voxapi.core.tts_api import TTSEngine, VOICE_ALIASES

PCM_BYTES_PER_SEC = 16000 * 2          
ENROLL_TRIGGER_BYTES = PCM_BYTES_PER_SEC * 3   
ENROLL_MAX_BYTES     = PCM_BYTES_PER_SEC * 8   

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

        self.speaker_buffer      = bytearray()
        self.is_speaker_enrolled = False
        self._enrollment_pending = False   

        self.system_audio_cache = {}
        self._load_system_audios()

    def _load_system_audios(self):
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
                except Exception as e:
                    logger.error(f"❌ [LocalAudio] 加载 {path} 失败: {e}")

    async def start(self):
        await self.tts.preload_local_refs()
        self.router_task = asyncio.create_task(self._message_router())
        logger.info("🧠 [Pipeline] 管线已就绪，进入休眠监听...")

    async def stop(self):
        for task in (self.router_task, self.llm_task, self.audio_task):
            if task and not task.done():
                task.cancel()
        await self.asr.stop()

    async def process_audio(self, audio_data: bytes):
        if not self.asr._running:
            self.asr.start()
        self.asr.send_audio(audio_data)

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
                if self.state == "IDLE":
                    self.state = "LISTENING"
                if not self.asr._running:
                    self.asr.start()

            elif msg_type == "speech_end":
                if self.asr._running:
                    self.asr.send_audio(b"\x00" * 3200)

        except Exception as exc:
            logger.error(f"控制消息处理异常: {exc}")

    async def _cancel_output(self):
        logger.debug("🧹 [Pipeline] 强制清理当前输出管线...")
        if self.llm_task and not self.llm_task.done():
            self.llm_task.cancel()
        if self.audio_task and not self.audio_task.done():
            self.audio_task.cancel()
            
        asyncio.get_running_loop().run_in_executor(None, self.tts.stop_session)
            
        await self.ws.send_json({"type": "stop_audio"})
        if self.tts.audio_queue:
            while not self.tts.audio_queue.empty():
                try: self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty: break

    async def _message_router(self):
        while True:
            try:
                msg = await self.asr.msg_queue.get()
                await self.ws.send_json(msg)
                self.asr.msg_queue.task_done()

                # 语义打断
                if msg["type"] == "asr_partial":
                    text = msg.get("text", "")
                    clean_text = re.sub(r'[^\w\s]', '', text).strip()
                    # 🚀 只在正常的说话/思考状态允许打断，开机关机状态绝对免疫！
                    if len(clean_text) >= 2 and self.state in ["SPEAKING", "THINKING"]:
                        logger.warning(f"🛑 [Pipeline] 语义打断生效：听到人类语音 '{clean_text}'")
                        await self._cancel_output()
                        self.state = "LISTENING"
                    continue

                if msg["type"] != "asr_final": continue

                # 🚀 屏蔽无意义追问：如果系统正在关机或开机中，丢弃干扰指令
                if self.state in ["SHUTTING_DOWN", "WAKING_UP"]:
                    continue

                text: str = msg["text"]
                logger.info(f"📝 [ASR] 识别结果: {text!r}")

                if (not self.is_speaker_enrolled and not self._enrollment_pending 
                    and len(self.speaker_buffer) >= ENROLL_TRIGGER_BYTES):
                    self._enrollment_pending = True
                    asyncio.create_task(self._enroll_current_speaker(force_reclone=False))

                if self.state == "SLEEPING":
                    if any(w in text for w in ["百变", "你好", "开机"]):
                        logger.success("⏰ [Pipeline] 检测到唤醒词！")
                        self.state = "WAKING_UP" # 🚀 开启开机护盾
                        await self.ws.send_json({"type": "woken_up"})
                        welcome = "你好啊，我是百变！我已经准备好了，你可以让我模仿雷军、易中天，或者你自己的声音哦。"
                        self.llm_task = asyncio.create_task(self._play_system_message(welcome))
                    continue

                if any(w in text for w in ["关机", "退出", "休息"]):
                    logger.info("🛑 [Pipeline] 收到关机指令，准备休眠...")
                    # 🚀 绝对修复：把清理动作放在任务启动【前】，防止关机任务自杀
                    await self._cancel_output()
                    self.llm_task = asyncio.create_task(self._execute_shutdown())
                    continue

                await self._cancel_output()
                self.state = "THINKING"
                self.llm_task = asyncio.create_task(self._run_llm_and_tts(text))

            except asyncio.CancelledError: break
            except Exception as exc: logger.error(f"Router 异常: {exc}")

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
                # 🚀 允许过渡态（护盾状态）向前端发送音频
                if self.state in ["SPEAKING", "SHUTTING_DOWN", "WAKING_UP"]:
                    await self.ws.send_bytes(chunk)
            except asyncio.CancelledError: break

    async def _play_system_message(self, text: str):
        try:
            await self.ws.send_json({"type": "llm_text", "text": text})
            await self.tts.start_session(self.current_voice)
            if self.tts.qwen_tts:
                self.audio_task = asyncio.create_task(self._audio_sender())
                await self.tts.send_text(text)
                await self.tts.finish_session()
                await self.audio_task
        except asyncio.CancelledError: pass
        finally: 
            if self.state == "WAKING_UP":
                self.state = "IDLE"

    async def _execute_shutdown(self):
        # 🚀 绝不在这里调用 self._cancel_output()！
        self.state = "SHUTTING_DOWN" # 开启关机护盾
        await asyncio.sleep(0.2)
        
        male_voices = ["男声", "男的", "男生", "龙老铁", "雷军", "leijun", "易中天", "yizhongtian", "书记", "shuji"]
        is_male = self.current_voice in male_voices
        cache_key = "shutdown_male" if is_male else "shutdown_female"
        
        if cache_key in self.system_audio_cache:
            await self.ws.send_json({"type": "llm_text", "text": "好的，百变这就去休息啦。随时叫我，拜拜！"})
            pcm_bytes = self.system_audio_cache[cache_key]
            chunk_size = 4800 
            for i in range(0, len(pcm_bytes), chunk_size):
                await self.ws.send_bytes(pcm_bytes[i:i+chunk_size])
                await asyncio.sleep(0.09) 
        else:
            try:
                await self.ws.send_json({"type": "llm_text", "text": "好的，百变这就去休息啦。随时叫我，拜拜！"})
                await self.tts.start_session(self.current_voice)
                if self.tts.qwen_tts:
                    self.audio_task = asyncio.create_task(self._audio_sender())
                    await self.tts.send_text("好的，百变这就去休息啦。随时叫我，拜拜！")
                    await self.tts.finish_session()
                    await self.audio_task
            except asyncio.CancelledError: pass

        await self.ws.send_json({"type": "shutdown"})
        self.state = "SLEEPING"

    async def _run_llm_and_tts(self, text: str):
        self.state = "SPEAKING"
        tts_started = False

        async def _generate():
            async for chunk in self.llm.generate_stream(text):
                yield chunk

        try:
            async for chunk in _generate():
                ctype = chunk.get("type")

                if ctype == "voice_ctrl":
                    target = chunk["target"]
                    self.current_voice = target
                    await self.ws.send_json({"type": "voice_changed", "voice": target})
                    
                    if target in ["speaker", "我", "我的声音", "我自己"]:
                        await self._enroll_current_speaker(force_reclone=True)

                elif ctype == "text_chunk":
                    if not tts_started:
                        await self.tts.start_session(self.current_voice)
                        if self.tts.qwen_tts is None:
                            logger.warning("⚠️ [Pipeline] TTS 引擎暂不可用，已放弃本次音频投递。")
                            break
                        self.audio_task = asyncio.create_task(self._audio_sender())
                        tts_started = True
                        
                    await self.tts.send_text(chunk["text"])
                    await self.ws.send_json({"type": "llm_text", "text": chunk["text"]})

            if tts_started and self.tts.qwen_tts:
                await self.tts.finish_session()
                if self.audio_task: await self.audio_task

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"LLM/TTS 运行异常: {exc}")
            await self.ws.send_json({"type": "llm_text", "text": "哎呀，我的大脑出了一点小故障，请稍后再试。"})
        finally:
            if self.state in ["SPEAKING", "THINKING"]:
                self.state = "IDLE"