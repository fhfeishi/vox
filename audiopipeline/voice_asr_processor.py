# audiopipeline/voice_asr_processor.py
from funasr import AutoModel
from loguru import logger

_ASR_MODEL = None


def get_asr():
    global _ASR_MODEL
    if _ASR_MODEL is None:
        _ASR_MODEL = AutoModel(model="paraformer-zh", vad_model="fsmn-vad", punc_model="ct-punc", device="cpu")
    return _ASR_MODEL


def find_target_time(audio_path: str, target_phrase: str):
    """识别音频并返回要替换句子的 start_ms 和 end_ms"""
    logger.info(f"🔍 正在音频中定位: '{target_phrase}'")
    res = get_asr().generate(input=audio_path, batch_size_s=300)

    if not res: return None, None

    text_no_punc = res[0].get('text', '').replace('，', '').replace('。', '').replace('？', '')
    timestamps = res[0].get('timestamp', [])

    target_no_punc = target_phrase.replace('，', '').replace('。', '').replace('？', '')
    start_idx = text_no_punc.find(target_no_punc)

    if start_idx == -1:
        logger.error("❌ 音频中未找到该句话！")
        return None, None

    end_idx = start_idx + len(target_no_punc) - 1

    start_ms = timestamps[start_idx][0]
    end_ms = timestamps[end_idx][1]

    logger.info(f"🎯 找到替换区间: {start_ms}ms -> {end_ms}ms")
    return start_ms, end_ms