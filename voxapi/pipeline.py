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

class SessionPipeline:
    def __init__(self, websocket):
        self.ws = websocket
        self.state = "SLEEPING"

        self.asr = StreamASR()
        self.llm = QwenEngine()
        self.tts = TTSEngine()

        self.llm_task: asyncio.Task | None = None
        self.audio_task: asyncio.Task | None = None
        self.router_task: asyncio.Task | None = None

        self.current_voice = "default"
        self.system_audio_cache = {}
        self._load_system_audios()

    def _load_system_audios(self):
        base_path = "locals/system_audio"
        os.makedirs(base_path, exist_ok=True)
        for key, name in {"shutdown_female": "shutdown_female.wav", "shutdown_male": "shutdown_male.wav"}.items():
            path = os.path.join(base_path, name)
            if os.path.exists(path):
                try:
                    with wave.open(path, 'rb') as wf:
                        self.system_audio_cache[key] = wf.readframes(wf.getnframes())
                except Exception:
                    pass

    async def start(self):
        # 🚀 核心修复：将预加载丢入后台线程！
        # 绝不阻塞 WebSocket 的启动，系统秒进状态，随时可以识别“你好”
        asyncio.create_task(self.tts.preload_local_refs())
        self.router_task = asyncio.create_task(self._message_router())
        logger.info("🧠 [Pipeline] 中枢路由已就绪")

    async def _cancel_output(self):
        if self.llm_task and not self.llm_task.done():
            self.llm_task.cancel()
        if self.audio_task and not self.audio_task.done():
            self.audio_task.cancel()

        asyncio.get_running_loop().run_in_executor(None, self.tts.stop_session)
        await self.ws.send_json({"type": "stop_audio"})

        if self.tts.audio_queue:
            while not self.tts.audio_queue.empty():
                try:
                    self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    async def process_audio(self, audio_data: bytes):
        if not self.asr._running: self.asr.start()
        self.asr.send_audio(audio_data)

    async def process_control(self, control_msg: str):
        try:
            msg = json.loads(control_msg)
            if msg.get("type") == "speech_start" and self.state == "IDLE":
                self.state = "LISTENING"
            elif msg.get("type") == "speech_end" and self.asr._running:
                self.asr.send_audio(b"\x00" * 3200)
        except Exception:
            pass

    async def _message_router(self):
        while True:
            try:
                msg = await self.asr.msg_queue.get()
                await self.ws.send_json(msg)

                if msg["type"] == "asr_partial":
                    text = re.sub(r'[^\w\s]', '', msg.get("text", "")).strip()
                    if len(text) >= 2 and self.state in ["SPEAKING", "THINKING"]:
                        logger.warning(f"🛑 [Pipeline] 语义打断：'{text}'")
                        await self._cancel_output()
                        self.state = "LISTENING"
                    continue

                if msg["type"] != "asr_final": continue

                if self.state in ["SHUTTING_DOWN", "WAKING_UP"]:
                    continue

                text = msg["text"]
                logger.info(f"📝 [ASR] 最终结果: {text!r}")

                if any(w in text for w in ["关机", "休息", "退出"]):
                    await self._cancel_output()
                    self.llm_task = asyncio.create_task(self._execute_shutdown())
                    continue

                if self.state == "SLEEPING":
                    if any(w in text for w in ["百变", "你好", "开机"]):
                        self.state = "WAKING_UP"
                        await self.ws.send_json({"type": "woken_up"})
                        self.llm_task = asyncio.create_task(self._play_system_msg("你好，我已经准备好了。"))
                    continue

                await self._cancel_output()
                self.state = "THINKING"
                self.llm_task = asyncio.create_task(self._run_llm_and_tts(text))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Router Error: {e}")

    async def _execute_shutdown(self):
        self.state = "SHUTTING_DOWN"
        await asyncio.sleep(0.2)

        is_male = any(x in self.current_voice for x in ["leijun", "yizhongtian", "Ethan", "男"])
        cache_key = "shutdown_male" if is_male else "shutdown_female"

        if cache_key in self.system_audio_cache:
            await self.ws.send_json({"type": "llm_text", "text": "好的，那我先休息了。"})
            pcm = self.system_audio_cache[cache_key]
            chunk_size = 4800
            for i in range(0, len(pcm), chunk_size):
                await self.ws.send_bytes(pcm[i:i + chunk_size])
                await asyncio.sleep(0.09)
        else:
            await self._play_system_msg("好的，那我先休息了，随时叫我。")

        await self.ws.send_json({"type": "shutdown"})
        self.state = "SLEEPING"

    async def _play_system_msg(self, text: str):
        try:
            await self.ws.send_json({"type": "llm_text", "text": text})
            await self.tts.start_session(self.current_voice)
            if self.tts.qwen_tts:
                self.audio_task = asyncio.create_task(self._audio_sender())
                await self.tts.send_text(text)
                await self.tts.finish_session()
                await self.audio_task
        finally:
            if self.state == "WAKING_UP": self.state = "IDLE"

    async def _audio_sender(self):
        while True:
            chunk = await self.tts.audio_queue.get()
            if chunk is None: break
            if self.state in ["SPEAKING", "SHUTTING_DOWN", "WAKING_UP"]:
                await self.ws.send_bytes(chunk)

    async def _run_llm_and_tts(self, text: str):
        self.state = "SPEAKING"
        tts_active = False
        try:
            async for chunk in self.llm.generate_stream(text):
                if chunk["type"] == "voice_ctrl":
                    self.current_voice = chunk["target"]
                    await self.ws.send_json({"type": "voice_changed", "voice": self.current_voice})
                elif chunk["type"] == "text_chunk":
                    if not tts_active:
                        await self.tts.start_session(self.current_voice)
                        if not self.tts.qwen_tts: break
                        self.audio_task = asyncio.create_task(self._audio_sender())
                        tts_active = True
                    await self.tts.send_text(chunk["text"])
                    await self.ws.send_json({"type": "llm_text", "text": chunk["text"]})

            if tts_active:
                await self.tts.finish_session()
                if self.audio_task: await self.audio_task
        except asyncio.CancelledError:
            pass
        finally:
            if self.state in ["SPEAKING", "THINKING"]: self.state = "IDLE"

    async def stop(self):
        for t in [self.llm_task, self.audio_task, self.router_task]:
            if t and not t.done(): t.cancel()
        await self.asr.stop()