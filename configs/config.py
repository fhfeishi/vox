# conigs/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    
    # dashscope 
    dashscope_api_key: str = ""

    # local
    # ------ asr  -----------
    ## paraformer
    paraformer_path: str=""
    # ------ tts  ------------
    ## voxcpm
    voxcpm2_path : str=""
    voxcpm15_path: str=""

    class Config:
        case_sensitive = True

    model_config = SettingsConfigDict(
        env_file='configs/.env',
        env_file_encoding='utf-8',
        extra='allow'
    )
    # .env examples:
    # DASHSCOPE_API_KEY=sk-12356xxxx
    

# 全局唯一实例
settings = Settings()

