# audiopipeline/scripts/task_auto_replace.py
import os
import sys

from audiopipeline import voice_ffmpeg, voice_editor, voice_clone, voice_asr_processor

# --- 配置区 ---
VIDEO_IN = "../temp/bad_interview.mp4"
OLD_TEXT = "我觉得这个项目不太行"
NEW_TEXT = "我觉得这个项目大有可为"
MODEL_DIR = "你的/voxcpm-v2/路径"
TEMP_DIR = "../temp"
OUT_VIDEO = "../temp/good_interview.mp4"


# -------------

def main():
    # 1. 拆解视听
    v_raw, a_16k = voice_ffmpeg.extract_assets(VIDEO_IN, TEMP_DIR)

    # 2. 定位旧台词的时间戳
    start_ms, end_ms = voice_asr_processor.find_target_time(a_16k, OLD_TEXT)
    if start_ms is None: return

    # 3. 从原音频中榨取至少 5s 的纯净人声，供大模型克隆使用
    ref_hq = os.path.join(TEMP_DIR, "ref_hq.wav")
    voice_editor.extract_pure_speech(a_16k, ref_hq)

    # 4. 生成 48k 新台词
    gen_48k = os.path.join(TEMP_DIR, "generated_48k.wav")
    voice_clone.generate_voice(NEW_TEXT, ref_hq, gen_48k, MODEL_DIR)

    # 5. 音频手术缝合 (将生成的 48k 音频嵌入，并统一输出为 48k)
    final_audio = os.path.join(TEMP_DIR, "final_audio.wav")
    voice_editor.replace_segment(a_16k, gen_48k, start_ms, end_ms, final_audio)

    # 6. 合并最终视频
    voice_ffmpeg.merge_final(v_raw, final_audio, OUT_VIDEO)

    print("✅ 自动化魔法替换完毕！")


if __name__ == "__main__":
    main()