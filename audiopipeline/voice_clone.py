# audiopipeline/voice_clone.py
import os
import wave
import numpy as np
from loguru import logger
from voxcpm import VoxCPM

_CLONE_MODEL = None


def get_cloner(model_dir: str):
    global _CLONE_MODEL
    if _CLONE_MODEL is None:
        logger.info(f"⏳ 正在加载 VoxCPM v2: {model_dir}")
        # _CLONE_MODEL = VoxCPM.from_pretrained(model_dir, load_denoiser=False)
        _CLONE_MODEL = VoxCPM.from_pretrained(model_dir)
    return _CLONE_MODEL


def generate_voice(text: str, ref_wav: str, save_path: str, model_dir: str):
    """调用 VoxCPM v2 进行 48k 非流式高质量克隆"""
    model = get_cloner(model_dir)
    # v2 版本默认采样率通常是 48000
    sample_rate = getattr(model.tts_model, 'sample_rate', 48000)

    result_audio = model.generate(text=text, reference_wav_path=ref_wav)

    # 防爆音 & 精度转换
    safe_audio = np.clip(result_audio, -1.0, 1.0)
    pcm_data = (safe_audio * 32767).astype(np.int16)

    with wave.open(save_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data.tobytes())

    logger.success(f"🎙️ AI 音频(48kHz)已生成: {save_path}")
    return save_path


if __name__ == '__main__':
    from configs.config import settings
    vox_path = settings.voxcpm15_path
    # vox_path = "mlx-community/VoxCPM2-8bit"
    model_ = get_cloner(vox_path)






