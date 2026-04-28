# 尝试 p 一下声音
from loguru import logger
from voxcpm import VoxCPM
import soundfile as sf

# 声音克隆
model_path = r"D:/local_models/tts/VoxCPM2"
src_voice =  r"D:/code/vox/temp/bowuguan/audio_b.wav"
tgt_voice = r"D:/code/vox/temp/bowuguan/audio_b4.wav"

trans_text: str = "大家好，欢迎来到兵马俑展厅，请随我一起看看这些古代战士的风采。"

model = VoxCPM.from_pretrained(
  model_path,
  load_denoiser=False,
)

wav = model.generate(
    text=f"(语气温柔、轻快活泼){trans_text}",
    reference_wav_path=src_voice,
    cfg_value=2.0,
    inference_timesteps=30,
)
sf.write(tgt_voice, wav, model.tts_model.sample_rate)
