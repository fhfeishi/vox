# test_asr_direct.py
import time
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from loguru import logger
import wave, os

import os 
from dotenv import load_dotenv
load_dotenv(dotenv_path="configs/.env")

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY") # 替换或从 env 读取

class TestCallback(RecognitionCallback):
    def on_event(self, result: RecognitionResult):
        try:
            sentence = result.get_sentence()
            if not sentence:
                return  # 心跳包或无有效句段时直接跳过
            
            text = sentence.get('text', '').strip()
            if not text:
                return

            # ✅ 正确取法：is_final 在 sentence 字典内
            is_final = sentence.get('is_final', False)
            
            # 🔒 兜底策略：部分 SDK 版本不返回 is_final，但有 end_time 即代表 VAD 已断句
            if not is_final and sentence.get('end_time') is not None:
                is_final = True

            logger.info(f"{'✅ 最终结果' if is_final else '🔄 中间结果'}: {text}")
            
        except Exception as e:
            # ⚠️ 回调运行在独立线程，异常必须捕获，否则会杀死 ASR 接收线程
            logger.error(f"🔍 回调解析异常: {e}")

    def on_close(self): 
        logger.debug("🔌 ASR 连接关闭")
    
    def on_error(self, msg): 
        logger.error(f"❌ ASR 错误: {msg}")

def send_pcm_file(recog, pcm_path):
    logger.info(f"📤 开始推送 PCM 文件: {pcm_path}")
    with open(pcm_path, 'rb') as f:
        while True:
            chunk = f.read(3200) # 每次 3200 bytes (约 100ms @ 16kHz/16bit)
            if not chunk: break
            recog.send_audio_frame(chunk)
            time.sleep(0.1) # 模拟真实流速
    logger.info("📤 音频推送完毕")

if __name__ == "__main__":
    # 1. 准备一个测试 PCM (可用 ffmpeg 生成: ffmpeg -i test.wav -f s16le -ac 1 -ar 16000 test.pcm)
    pcm_file = "locals/refs/zhonglin.pcm"
    if not os.path.exists(pcm_file):
        logger.error("⚠️ 请先准备一个 16k/16bit/mono 的 PCM 文件放到 locals/refs/ 下")
        exit(1)

    cb = TestCallback()
    recog = Recognition(
        model='paraformer-realtime-v2', format='pcm', sample_rate=16000,
        callback=cb, enable_intermediate_result=True
    )
    recog.start()
    time.sleep(0.5)
    
    send_pcm_file(recog, pcm_file)
    
    # 等 VAD 断句
    time.sleep(2)
    recog.stop()
    logger.success("🎉 直连测试完成，请检查上方是否输出识别文本")
