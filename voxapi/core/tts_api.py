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
# 官方预设音色表（✅ 已对齐 qwen3-tts-flash-realtime 模型）
# ──────────────────────────────────────────────────────────────
OFFICIAL_VOICES: dict[str, str] = {
    "default": "Cherry",        # 默认女声（官方推荐，清晰稳定）
    "晓燕":   "Siqi",           # 活泼女声
    "龙老铁": "Ethan",          # 沉稳男声
    "亚男":   "Chelsie",        # 知性女声
    "硕硕":   "Yifan",          # 磁性男声
    "书欣":   "Stella",         # 温柔女声
    "飞飞":   "Luna",           # 活力女声
    "老铁":   "Asher",          # 浑厚男声
}

# ──────────────────────────────────────────────────────────────
# 本地克隆音色的逻辑名 → wav 路径映射
# 启动时自动扫描 locals/refs/ref_{name}.wav
# ──────────────────────────────────────────────────────────────
LOCAL_REF_NAMES = ["leijun", "yizhongtian", "shuji", "wuhannvhai"]

# ──────────────────────────────────────────────────────────────
# 克隆音色本地缓存文件（避免每次连接重复克隆）
# ──────────────────────────────────────────────────────────────
VOICE_CACHE_FILE = os.path.join("locals", "voice_cache.json")


class TTSEngine:
    def __init__(self):
        # 官方预设（始终可用）
        self.official_voices: dict[str, str] = OFFICIAL_VOICES.copy()

        # 克隆成功后的映射：逻辑名 → 阿里云返回的 voice_id
        self.enrolled_voices: dict[str, str] = {}

        # 异步音频队列 & 事件循环
        self.audio_queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self.qwen_tts: QwenTtsRealtime | None = None

        # 启动时从磁盘缓存恢复已克隆音色
        self._load_voice_cache()

    # ── 缓存持久化 ────────────────────────────────────────────

    def _load_voice_cache(self):
        """从本地 JSON 文件加载已克隆的 voice_id 映射。"""
        if os.path.exists(VOICE_CACHE_FILE):
            try:
                with open(VOICE_CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                # 只保留有效条目
                self.enrolled_voices = {k: v for k, v in cached.items() if v}
                if self.enrolled_voices:
                    logger.info(
                        f"📂 [TTS] 从缓存加载 {len(self.enrolled_voices)} 个克隆音色: "
                        f"{list(self.enrolled_voices.keys())}"
                    )
            except Exception as exc:
                logger.warning(f"⚠️  [TTS] 缓存读取失败，将重新克隆: {exc}")
                self.enrolled_voices = {}

    def _save_voice_cache(self):
        """将 enrolled_voices 持久化到本地 JSON 文件。"""
        try:
            os.makedirs(os.path.dirname(VOICE_CACHE_FILE), exist_ok=True)
            with open(VOICE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.enrolled_voices, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"⚠️  [TTS] 缓存写入失败: {exc}")

    # ── 内部工具 ──────────────────────────────────────────────

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

    # ── 声音克隆 ─────────────────────────────────────────────

    async def enroll_voice(self, audio_source: str | bytes, preferred_name: str) -> str | None:
        if preferred_name in self.enrolled_voices:
            vid = self.enrolled_voices[preferred_name]
            logger.info(f"✅ [TTS] 『{preferred_name}』已缓存 → {vid}，跳过克隆。")
            return vid

        logger.info(f"🔄 [TTS] 正在提交克隆请求: 『{preferred_name}』 ...")
        try:
            if isinstance(audio_source, str):
                if not os.path.exists(audio_source):
                    logger.warning(f"⚠️  文件不存在: {audio_source}")
                    return None
                with open(audio_source, "rb") as f:
                    raw = f.read()
                wav_bytes = raw if audio_source.lower().endswith(".wav") else self._pcm_to_wav(raw)
            else:
                wav_bytes = self._pcm_to_wav(audio_source)

            b64 = base64.b64encode(wav_bytes).decode()
            data_uri = f"data:audio/wav;base64,{b64}"

            # 🔑 核心修复：必须使用官方规定的复刻路由标识
            url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
            payload = {
                "model": "qwen-voice-enrollment",           # ← 固定值，不可改
                "input": {
                    "action": "create",
                    "target_model": "qwen3-tts-flash-realtime", # ← 修复：对齐 start_session 的模型名
                    "preferred_name": preferred_name,
                    "audio": {"data": data_uri},
                },
            }
            headers = {
                "Authorization": f"Bearer {settings.dashscope_api_key}",
                "Content-Type": "application/json",
            }

            resp = await asyncio.to_thread(
                requests.post, url, json=payload, headers=headers, timeout=60
            )

            if resp.status_code == 200:
                data = resp.json()
                output = data.get("output", {})
                voice_id = output.get("voice")

                if not voice_id and output.get("task_id"):
                    voice_id = await self._poll_clone_task(output["task_id"], preferred_name)

                if voice_id:
                    self.enrolled_voices[preferred_name] = voice_id
                    self._save_voice_cache()
                    logger.success(f"✅ [TTS] 『{preferred_name}』克隆成功 → voice_id={voice_id}")
                    return voice_id
                else:
                    logger.error(f"❌ [TTS] 克隆响应中无有效 voice_id: {data}")

            else:
                try:
                    resp_json = resp.json()
                except Exception:
                    resp_json = {}

                error_code = resp_json.get("code", "")
                if error_code in ("VoiceAlreadyExist", "AlreadyExists", "Conflict",
                                  "DataExist", "Duplicate"):
                    logger.warning(f"⚠️  [TTS] 『{preferred_name}』已在远端存在，尝试查询...")
                    voice_id = await self._query_existing_voice(preferred_name)
                    if voice_id:
                        self.enrolled_voices[preferred_name] = voice_id
                        self._save_voice_cache()
                        logger.success(f"✅ [TTS] 查询到已有音色 『{preferred_name}』 → {voice_id}")
                        return voice_id

                logger.error(f"❌ [TTS] 克隆接口返回错误 [{resp.status_code}]: {resp.text[:500]}")

        except Exception as exc:
            logger.error(f"❌ [TTS] 克隆过程异常: {exc}")

        return None

    # ── 异步克隆轮询 ──────────────────────────────────────────

    async def _poll_clone_task(
        self, task_id: str, preferred_name: str, max_wait: int = 120
    ) -> str | None:
        url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        # 🔑 轮询也必须使用 qwen-voice-enrollment 路由
        payload = {
            "model": "qwen-voice-enrollment",
            "input": {"action": "query", "task_id": task_id},
        }

        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            try:
                resp = await asyncio.to_thread(
                    requests.post, url, json=payload, headers=headers, timeout=30
                )
                if resp.status_code == 200:
                    output = resp.json().get("output", {})
                    status = output.get("task_status", "")
                    if status == "SUCCEEDED":
                        vid = output.get("voice")
                        if vid: return vid
                    elif status in ("FAILED", "UNKNOWN"):
                        logger.error(f"❌ [TTS] 克隆任务失败: {resp.text[:300]}")
                        return None
                else:
                    logger.warning(f"⚠️  [TTS] 轮询返回 [{resp.status_code}]，继续等待...")
            except Exception as exc:
                logger.warning(f"⚠️  [TTS] 轮询请求异常: {exc}")

        logger.error(f"❌ [TTS] 克隆任务超时 ({max_wait}s)")
        return None

    # ── 查询已有克隆音色 ──────────────────────────────────────

    async def _query_existing_voice(self, preferred_name: str) -> str | None:
        url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        # 🔑 查询列表同样使用标准路由标识
        payload = {
            "model": "qwen-voice-enrollment",
            "input": {"action": "query"},
        }
        try:
            resp = await asyncio.to_thread(
                requests.post, url, json=payload, headers=headers, timeout=30
            )
            if resp.status_code == 200:
                voices = resp.json().get("output", {}).get("voices", [])
                for v in voices:
                    if v.get("preferred_name") == preferred_name:
                        return v.get("voice")
                logger.warning(f"⚠️  [TTS] 远端音色列表中未找到 『{preferred_name}』")
            else:
                logger.warning(f"⚠️  [TTS] 查询远端音色失败 [{resp.status_code}]")
        except Exception as exc:
            logger.error(f"❌ [TTS] 查询已有音色异常: {exc}")
        return None

    # ── 预加载本地参考音色 ────────────────────────────────────

    async def preload_local_refs(self):
        """
        启动时并发克隆所有本地参考音色。
        已缓存的跳过，未缓存的提交克隆。
        """
        base_path = "locals/refs"
        tasks = []
        for name in LOCAL_REF_NAMES:
            # 缓存已有 → 跳过
            if name in self.enrolled_voices:
                logger.info(f"✅ [TTS] 『{name}』已缓存，跳过克隆")
                continue

            path = os.path.join(base_path, f"ref_{name}.wav")
            if os.path.exists(path):
                logger.info(f"📂 [TTS] 发现本地音频: {path}")
                tasks.append(self.enroll_voice(path, name))
            else:
                logger.warning(f"⚠️  [TTS] 未找到本地音频: {path}，跳过")

        if tasks:
            logger.info(f"⏳ [TTS] 并发提交 {len(tasks)} 个克隆任务...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            succeeded = sum(1 for r in results if isinstance(r, str))
            logger.info(
                f"✅ [TTS] 本地参考音色加载完毕 "
                f"({succeeded}/{len(tasks)} 成功)，"
                f"当前克隆库: {list(self.enrolled_voices.keys())}"
            )
        else:
            logger.info(
                f"✅ [TTS] 所有本地音色均已缓存，无需克隆。"
                f"当前克隆库: {list(self.enrolled_voices.keys())}"
            )

    # ── 音色解析 ──────────────────────────────────────────────

    def resolve_voice_id(self, voice_target: str) -> str:
        """
        按优先级解析 voice_target → 实际 voice_id：
        1. 已克隆库（enrolled_voices）   —— 本地克隆 / 用户 speaker
        2. 官方预设库（official_voices）  —— 内置免克隆音色
        3. 兜底 default
        """
        if voice_target in self.enrolled_voices:
            vid = self.enrolled_voices[voice_target]
            logger.debug(f"🎭 [TTS] 使用克隆音色 '{voice_target}' → {vid}")
            return vid
        if voice_target in self.official_voices:
            vid = self.official_voices[voice_target]
            logger.debug(f"🎭 [TTS] 使用官方音色 '{voice_target}' → {vid}")
            return vid
        vid = self.official_voices["default"]
        logger.warning(f"⚠️  [TTS] 未知音色 '{voice_target}'，回退到 default → {vid}")
        return vid

    # ── TTS 会话 ──────────────────────────────────────────────

    def start_session(self, voice_target: str):
        self._ensure_queue()

        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        voice_id = self.resolve_voice_id(voice_target)
        logger.info(f"🎙️  [TTS] 开启会话 | 发音人: {voice_target} (id={voice_id})")

        callback = TTSCallback(self.audio_queue, self._loop)
        # qwen3-tts-vc-realtime-2026-01-15 qwen3-tts-flash-realtime
        self.qwen_tts = QwenTtsRealtime(model="qwen3-tts-vc-realtime-2026-01-15", callback=callback)
        self.qwen_tts.connect()
        self.qwen_tts.update_session(
            voice=voice_id,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="server_commit",
        )

    def send_text(self, text: str):
        if self.qwen_tts:
            self.qwen_tts.append_text(text)

    def finish_session(self):
        if self.qwen_tts:
            self.qwen_tts.finish()


# ──────────────────────────────────────────────────────────────

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