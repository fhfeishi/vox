# conigs/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    
    # dashscope 
    dashscope_api_key: str = ""
    
    # class Config:
    #     env_file="configs/.env"
    #     env_file_encoding="utf-8"
    model_config = SettingsConfigDict(
        env_file='configs/.env',
        env_file_encoding='utf-8',
        extra='allow'  # ✅ 允许任意额外字段
    )
    # .env info:
    # DASHSCOPE_API_KEY=sk-12356xxxx
    

# 全局唯一实例
settings = Settings()

