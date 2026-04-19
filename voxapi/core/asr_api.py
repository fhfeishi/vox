# voxapi/core/asr_api.py
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from configs.config import settings
from loguru import logger
import os, asyncio
from typing import Optional

dashscope.api_key = settings.dashscope_api_key

class ASRCallback(RecognitionCallback):
    def __init__(self, msg_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.msg_queue = msg_queue
        self.loop = loop  # 获取 FastAPI 的主事件循环
        self._closed = False

    def on_event(self, result: RecognitionResult):
        if self._closed: return
        try:
            sentence = result.get_sentence()
            if not sentence or 'text' not in sentence: return

            text = sentence['text'].strip()
            if not text: return

            # ✅ 安全解析：优先 is_final，降级用 end_time
            is_final = sentence.get('is_final', False)
            if not is_final and sentence.get('end_time') is not None:
                is_final = True

            msg = {
                "type": "asr_final" if is_final else "asr_partial",
                "text": text
            }
            # 🚀 跨线程通信最佳实践：将同步线程的数据安全推入异步队列
            self.loop.call_soon_threadsafe(self.msg_queue.put_nowait, msg)
            
        except Exception as e:
            # ⚠️ 必须捕获！否则会杀死 SDK 后台接收线程
            logger.error(f"ASR 回调异常: {e}")

    def on_close(self):
        self._closed = True
        logger.debug("🔌 ASR 连接已关闭")

    def on_error(self, message: str):
        self._closed = True
        logger.error(f"❌ ASR 错误: {message}")

class StreamASR:
    # 默认 debug_audio=False，防止长时间录音撑爆本地磁盘
    def __init__(self, debug_audio: bool = False):
        self.loop = asyncio.get_running_loop()
        self.msg_queue = asyncio.Queue()  # 纯粹的输出队列
        self.callback = ASRCallback(self.msg_queue, self.loop)
        self.recognition: Optional[Recognition] = None
        self._running = False
        
        self._debug_audio = debug_audio
        self._debug_bytes = 0
        self._debug_path = "locals/ref/debug_capture.pcm"
        self._debug_file = None

    def start(self):
        if self._running: return
        
        self._debug_bytes = 0
        self._debug_file = None
        if self._debug_audio:
            os.makedirs(os.path.dirname(self._debug_path), exist_ok=True)
            self._debug_file = open(self._debug_path, 'wb')
            logger.info(f"🎙️ 调试音频录制已开启 -> {self._debug_path}")

        try:
            self.recognition = Recognition(
                model='paraformer-realtime-v2',
                format='pcm',
                sample_rate=16000,
                callback=self.callback,
                enable_intermediate_result=True,  # 🔑 必须开启，否则收不到 partial
                enable_punctuation_prediction=True,
                enable_inverse_text_normalization=True,
            )
            self.recognition.start()
            self._running = True
            logger.success("✅ ASR 引擎已启动，等待音频流...")
        except Exception as e:
            logger.error(f"🚨 启动 ASR 失败: {e}")
            self._running = False
            raise

    def send_audio(self, audio_data: bytes):
        if not self._running or not self.recognition: return
        if not audio_data: return
        
        # ✅ 关键确认：打印首帧长度，验证 WS 二进制流是否通畅
        if self._debug_bytes < 100: 
            logger.info(f"📥 首次收到音频帧 | 长度: {len(audio_data)} bytes")
        self._debug_bytes += len(audio_data)

        if self._debug_file:
            try:
                self._debug_file.write(audio_data)
                self._debug_file.flush()
            except Exception as e:
                logger.error(f"💾 调试文件写入失败: {e}")

        try:
            self.recognition.send_audio_frame(audio_data)
        except Exception as e:
            logger.warning(f"⚠️ send_audio_frame 异常: {e}")
            self._running = False

    async def stop(self):
        if not self._running: return
        self._running = False
        self.callback._closed = True

        if self.recognition:
            try: self.recognition.stop()
            except Exception as e: pass
            finally: self.recognition = None
            
        logger.info("🛑 ASR 引擎已停止")