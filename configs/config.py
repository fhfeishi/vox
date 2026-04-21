# conigs/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    
    # dashscope 
    dashscope_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file='configs/.env',
        env_file_encoding='utf-8',
        extra='allow'
    )
    # .env examples:
    # DASHSCOPE_API_KEY=sk-12356xxxx
    

# 全局唯一实例
settings = Settings()

