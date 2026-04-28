# audiopipeline/voice_editor.py
import numpy as np
from pydub import AudioSegment
from funasr import AutoModel
from loguru import logger

_VAD_MODEL = None


def get_vad():
    global _VAD_MODEL
    if _VAD_MODEL is None:
        _VAD_MODEL = AutoModel(model="iic/speech_fsmn_vad_zh-cn-16k-common-onnx", device="cpu")
    return _VAD_MODEL


def extract_pure_speech(audio_path: str, save_path: str, min_sec: float = 5.0):
    """利用 VAD 提取纯净人声，不够 5s 就循环拼接，为克隆提供极品参考"""
    audio = AudioSegment.from_file(audio_path).set_frame_rate(16000).set_channels(1)
    samples = np.array(audio.get_array_of_samples()).astype(np.float32) / 32768.0

    segments = get_vad().generate(input=samples)[0].get('value', [])
    if not segments:
        raise ValueError("音频中未检测到人声！")

    pure_speech = AudioSegment.empty()
    for start, end in segments:
        if end - start > 200:
            pure_speech += audio[start:end]

    pure_speech = pure_speech.normalize()

    target_ms = int(min_sec * 1000)
    if len(pure_speech) < target_ms:
        pure_speech = pure_speech.loop((target_ms // len(pure_speech)) + 1)

    pure_speech.export(save_path, format="wav")
    logger.success(f"🧬 高质量参考音频已生成: {save_path}")
    return save_path


def replace_segment(original_path: str, generated_path: str, start_ms: int, end_ms: int, save_path: str):
    """局部交叉淡化替换"""
    original = AudioSegment.from_file(original_path)
    replacement = AudioSegment.from_file(generated_path)

    # 因为 VoxCPM v2 生成的是 48k，我们需要统一双方的采样率才能拼接
    # 统一将原音频提升到 48k 进行高音质拼接
    original = original.set_frame_rate(48000)
    replacement = replacement.set_frame_rate(48000)

    part_pre = original[:start_ms]
    part_post = original[end_ms:]

    combined = part_pre.append(replacement, crossfade=80).append(part_post, crossfade=80)
    combined.export(save_path, format="wav")
    logger.success(f"✂️ 局部替换完成: {save_path}")
    return save_path