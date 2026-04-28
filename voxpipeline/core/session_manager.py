# voxpipeline/core/session_manager.py
from typing import Dict
from voxpipeline.core.pipeline import AudioPipeline

class SessionManager:
    def __init__(self):
        # 核心：session_id -> AudioPipeline 实例
        self.sessions: Dict[str, AudioPipeline] = {}

    def get_or_create(self, session_id: str) -> AudioPipeline:
        if session_id not in self.sessions:
            # 动态创建一个全新的管线
            pipeline = AudioPipeline(session_id=session_id)
            # 在这里根据配置添加节点
            self.sessions[session_id] = pipeline
        return self.sessions[session_id]

    async def close_session(self, session_id: str):
        if session_id in self.sessions:
            await self.sessions[session_id].stop()
            del self.sessions[session_id]

# 全局单例
manager = SessionManager()