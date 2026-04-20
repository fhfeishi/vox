# voxapi/core/tts_api.py
import os
import io
import wave
import json
import time
import base64
import asyncio
import requests
import dashscope
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat
from loguru import logger
from configs.config import settings

dashscope.api_key = settings.dashscope_api_key

# ──────────────────────────────────────────────────────────────
# 官方预设音色表
# ──────────────────────────────────────────────────────────────
OFFICIAL_VOICES: dict[str, str] = {
    "default": "Cherry",        
    "晓燕":   "Siqi",           
    "龙老铁": "Ethan",          
    "亚男":   "Chelsie",        
    "硕硕":   "Yifan",          
    "书欣":   "Stella",         
    "飞飞":   "Luna",           
    "老铁":   "Asher",          
}

LOCAL_REF_NAMES = ["leijun", "yizhongtian", "shuji", "wuhannvhai"]
VOICE_CACHE_FILE = os.path.join("locals", "voice_cache.json")

# 🚀 核心优化：全方位别名映射阵列，解决同音识别错误
VOICE_ALIASES = {
    "雷军": "leijun",
    "易中天": "yizhongtian",
    "书记": "shuji",
    "武汉女孩": "wuhannvhai",
    # 克隆用户本人
    "我": "speaker",
    "我的": "speaker",
    "我自己": "speaker",
    "我的声音": "speaker",
    # 泛指男声
    "男声": "龙老铁",
    "男的": "龙老铁",
    "男生": "龙老铁",
    "男孩": "龙老铁",
    "男人": "龙老铁",
    "小哥哥": "龙老铁",
    # 泛指女声
    "女声": "default",
    "女的": "default",
    "女生": "default",
    "女孩": "default",
    "女人": "default",
    "小姐姐": "default"
}

class TTSEngine:
    def __init__(self):
        self.official_voices: dict[str, str] = OFFICIAL_VOICES.copy()
        self.enrolled_voices: dict[str, str] = {}
        self.audio_queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.qwen_tts: QwenTtsRealtime | None = None
        self._load_voice_cache()

    def _load_voice_cache(self):
        if os.path.exists(VOICE_CACHE_FILE):
            try:
                with open(VOICE_CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                self.enrolled_voices = {k: v for k, v in cached.items() if v}
                if self.enrolled_voices:
                    logger.info(f"📂 [TTS] 从缓存加载 {len(self.enrolled_voices)} 个克隆音色: {list(self.enrolled_voices.keys())}")
            except Exception as exc:
                logger.warning(f"⚠️  [TTS] 缓存读取失败: {exc}")

    def _save_voice_cache(self):
        try:
            os.makedirs(os.path.dirname(VOICE_CACHE_FILE), exist_ok=True)
            # 🚀 核心修复：把 speaker 剔除出磁盘缓存！保证每次重启服务都是新声纹
            to_save = {k: v for k, v in self.enrolled_voices.items() if k != "speaker"}
            with open(VOICE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(to_save, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"⚠️  [TTS] 缓存写入失败: {exc}")

    def _ensure_queue(self):
        if self.audio_queue is None:
            self._loop = asyncio.get_running_loop()
            self.audio_queue = asyncio.Queue()

    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)
        return buf.getvalue()

    # 🚀 增加 force_reclone 参数
    async def enroll_voice(self, audio_source: str | bytes, preferred_name: str, force_reclone: bool = False) -> str | None:
        # 如果不是强制重写，且已经存在，则跳过
        if not force_reclone and preferred_name in self.enrolled_voices:
            vid = self.enrolled_voices[preferred_name]
            logger.info(f"✅ [TTS] 『{preferred_name}』已在缓存中 → {vid}，跳过 API 克隆。")
            return vid

        logger.info(f"🔄 [TTS] 正在向远端提交{'更新' if force_reclone else '创建'}请求: 『{preferred_name}』 ...")
        try:
            if isinstance(audio_source, str):
                if not os.path.exists(audio_source):
                    return None
                with open(audio_source, "rb") as f: raw = f.read()
                wav_bytes = raw if audio_source.lower().endswith(".wav") else self._pcm_to_wav(raw)
            else:
                wav_bytes = self._pcm_to_wav(audio_source)

            b64 = base64.b64encode(wav_bytes).decode()
            data_uri = f"data:audio/wav;base64,{b64}"

            url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
            payload = {
                "model": "qwen-voice-enrollment",
                "input": {
                    "action": "create",
                    "target_model": "qwen3-tts-vc-realtime-2026-01-15", 
                    "preferred_name": preferred_name,
                    "audio": {"data": data_uri},
                },
            }
            headers = {"Authorization": f"Bearer {settings.dashscope_api_key}", "Content-Type": "application/json"}

            resp = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=60)

            if resp.status_code == 200:
                data = resp.json()
                output = data.get("output", {})
                voice_id = output.get("voice")

                if not voice_id and output.get("task_id"):
                    voice_id = await self._poll_clone_task(output["task_id"], preferred_name)

                if voice_id:
                    self.enrolled_voices[preferred_name] = voice_id
                    self._save_voice_cache() # (speaker 会被 _save 自动过滤掉不落盘)
                    logger.success(f"✅ [TTS] 『{preferred_name}』克隆完毕 → voice_id={voice_id}")
                    return voice_id
            else:
                try: resp_json = resp.json()
                except Exception: resp_json = {}

                error_code = resp_json.get("code", "")
                if error_code in ("VoiceAlreadyExist", "AlreadyExists", "Conflict", "DataExist", "Duplicate"):
                    # 远端已存在，查询并返回
                    voice_id = await self._query_existing_voice(preferred_name)
                    if voice_id:
                        self.enrolled_voices[preferred_name] = voice_id
                        self._save_voice_cache()
                        return voice_id

                logger.error(f"❌ [TTS] 克隆报错 [{resp.status_code}]: {resp.text[:200]}")

        except Exception as exc:
            logger.error(f"❌ [TTS] 克隆过程异常: {exc}")
        return None

    async def _poll_clone_task(self, task_id: str, preferred_name: str, max_wait: int = 120) -> str | None:
        url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = {"Authorization": f"Bearer {settings.dashscope_api_key}", "Content-Type": "application/json"}
        payload = {"model": "qwen-voice-enrollment", "input": {"action": "query", "task_id": task_id}}

        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            try:
                resp = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    output = resp.json().get("output", {})
                    if output.get("task_status") == "SUCCEEDED":
                        return output.get("voice")
            except Exception: pass
        return None

    async def _query_existing_voice(self, preferred_name: str) -> str | None:
        url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = {"Authorization": f"Bearer {settings.dashscope_api_key}", "Content-Type": "application/json"}
        payload = {"model": "qwen-voice-enrollment", "input": {"action": "query"}}
        try:
            resp = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200:
                voices = resp.json().get("output", {}).get("voices", [])
                for v in voices:
                    if v.get("preferred_name") == preferred_name: return v.get("voice")
        except Exception: pass
        return None

    async def preload_local_refs(self):
        base_path = "locals/refs"
        tasks = []
        for name in LOCAL_REF_NAMES:
            if name in self.enrolled_voices: continue
            path = os.path.join(base_path, f"ref_{name}.wav")
            if os.path.exists(path):
                logger.info(f"📂 [TTS] 发现本地音频: {path}")
                tasks.append(self.enroll_voice(path, name))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def start_session(self, voice_target: str):
        self._ensure_queue()
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except asyncio.QueueEmpty: break

        internal_target = VOICE_ALIASES.get(voice_target, voice_target)
        is_cloned_voice = internal_target in self.enrolled_voices
        
        if is_cloned_voice:
            voice_id = self.enrolled_voices[internal_target]
            engine_model = "qwen3-tts-vc-realtime-2026-01-15" 
        else:
            voice_id = self.official_voices.get(internal_target, self.official_voices["default"])
            engine_model = "qwen3-tts-flash-realtime"         

        logger.info(f"🎙️ [TTS] 开启会话 | 发音人: {voice_target} -> {internal_target} (ID={voice_id}) | 引擎: {engine_model}")

        callback = TTSCallback(self.audio_queue, self._loop)
        self.qwen_tts = QwenTtsRealtime(model=engine_model, callback=callback)
        self.qwen_tts.connect()
        
        self.qwen_tts.update_session(
            voice=voice_id,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="server_commit",
        )

    def send_text(self, text: str):
        if self.qwen_tts: self.qwen_tts.append_text(text)

    def finish_session(self):
        if self.qwen_tts: self.qwen_tts.finish()

class TTSCallback(QwenTtsRealtimeCallback):
    def __init__(self, audio_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.audio_queue = audio_queue
        self.loop = loop

    def on_event(self, response: dict) -> None:
        try:
            event_type = response.get("type", "")
            if event_type == "response.audio.delta":
                audio_data = base64.b64decode(response["delta"])
                self.loop.call_soon_threadsafe(self.audio_queue.put_nowait, audio_data)
            elif event_type == "session.finished":
                self.loop.call_soon_threadsafe(self.audio_queue.put_nowait, None)
        except Exception as exc:
            logger.error(f"TTS 回调异常: {exc}")

    def on_error(self, error):
        logger.error(f"TTS 报错: {error}")
        self.loop.call_soon_threadsafe(self.audio_queue.put_nowait, None)