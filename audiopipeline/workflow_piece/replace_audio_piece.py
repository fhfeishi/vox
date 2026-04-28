# my_magic_workflow.py

from audiopipeline import voice_ffmpeg, voice_editor, voice_clone, voice_asr_processor
import os

res_root: str = "audiopipeline/temp"


def main():
    # 1. 拆解视听 (拿到高质量底包 a_hq)
    v_raw, a_16k, a_hq = voice_ffmpeg.extract_assets(VIDEO_IN, TEMP_DIR)

    # 2. 定位 (用 a_16k 识别，因为 ASR 模型固定需要 16k)
    start_ms, end_ms = voice_asr_processor.find_target_time(a_16k, OLD_TEXT)
    if start_ms is None: return

    # 3. 提纯 (用 a_hq 提纯，给克隆模型最好的参考音质)
    ref_hq = os.path.join(TEMP_DIR, "ref_hq.wav")
    voice_editor.extract_pure_speech(a_hq, ref_hq)

    # 4. 生成新台词
    gen_48k = os.path.join(TEMP_DIR, "generated_48k.wav")
    voice_clone.generate_voice(NEW_TEXT, ref_hq, gen_48k, MODEL_DIR)

    # 5. 音频手术缝合 (对 a_hq 动刀，而不是 a_16k)
    final_audio = os.path.join(TEMP_DIR, "final_audio.wav")
    voice_editor.replace_segment(a_hq, gen_48k, start_ms, end_ms, final_audio)

    # 6. 合并
    voice_ffmpeg.merge_final(v_raw, final_audio, OUT_VIDEO)