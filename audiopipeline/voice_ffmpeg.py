# audiopipeline/voice_ffmpeg.py
import subprocess
import os
from loguru import logger


def run_cmd(cmd: list):
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg 报错: {e.stderr}")
        raise e


def extract_assets(video_path: str, temp_dir: str):
    """提取无声视频和 16k/单声道 音频 (16k是为了给ASR和VAD做分析)"""
    os.makedirs(temp_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(video_path))[0]

    v_raw = os.path.join(temp_dir, f"{base}_video_only.mp4")
    a_raw = os.path.join(temp_dir, f"{base}_audio_16k.wav")
    a_hq = os.path.join(temp_dir, f"{base}_audio_hq.wav")

    logger.info("🎬 开始提取视频与音频轨...")
    run_cmd(["ffmpeg", "-y", "-i", video_path, "-an", "-vcodec", "copy", v_raw])
    run_cmd(["ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", a_raw])

    run_cmd(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", a_hq])

    return v_raw, a_raw, a_hq


def merge_final(video_raw: str, audio_final: str, out_path: str):
    """将最终处理好的音频（48k）与无声视频合并"""
    logger.info(f"🎞️ 正在合成最终视频: {out_path}")
    # cmd = [
    #     "ffmpeg", "-y", "-i", video_raw, "-i", audio_final,
    #     "-vcodec", "copy", "-acodec", "aac", "-b:a", "256k",  # 调高码率以匹配 48k 音质
    #     "-shortest", out_path
    # ]
    cmd = [
        "ffmpeg", "-y", "-i", video_raw, "-i", audio_final,
        "-vcodec", "copy", "-acodec", "aac", "-b:a", "256k",  # 调高码率以匹配 48k 音质
        out_path
    ]
    run_cmd(cmd)