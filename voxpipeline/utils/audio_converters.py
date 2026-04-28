# utils/audio_converters.py
import numpy as np
# 未来如果需要，可以 import torch
from voxpipeline.core.datatypes import AudioChunk


class AudioConverter:
    """音频格式转换工厂/工具类"""

    @staticmethod
    def chunk_to_numpy(chunk: AudioChunk) -> np.ndarray:
        """将 PCM AudioChunk 转换为 numpy 数组，供传统 ML 模型使用"""
        # zero-copy 转换
        return np.frombuffer(chunk.data, dtype=np.int16)

    # @staticmethod
    # def chunk_to_tensor(chunk: AudioChunk): # -> torch.Tensor
    #     """未来如果接入 PyTorch 模型，直接加在这里"""
    #     numpy_array = AudioConverter.chunk_to_numpy(chunk)
    #     return torch.from_numpy(numpy_array)

    @staticmethod
    def bytes_to_wav(pcm_data: bytes, sample_rate: int) -> bytes:
        """如果需要把处理完的 PCM 重新打包成 WAV 发送给客户端"""
        # 这里写 PCM 拼凑 WAV Header 的逻辑
        pass