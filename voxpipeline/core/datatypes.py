# voxpipeline/datatypes.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class AudioChunk(BaseModel):
    # 允许传入任意类型，我们用它来装 bytes
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: bytes = Field(..., description="PCM 字节流数据")
    is_last: bool = Field(False, description="是否是流的最后一块")


class TextChunk(BaseModel):
    text: str = Field(..., description="文本片段内容")
    is_last: bool = Field(False, description="是否是整个文本流的最后一块 (EOF信号)")

    # --- 以下是你未来为了“更专业”可以随时拓展的字段 ---
    # language: str = Field("zh", description="语种")
    # emotion: Optional[str] = Field(None, description="情感标签，比如 'happy', 'sad'")
    speaker_id: Optional[str] = Field(None, description="指定这句文本应该用哪个音色播报")


class TaskState(BaseModel):
    task_id: str
    status: str = Field(..., description="例如: queued, processing, completed, failed")
    message: Optional[str] = None