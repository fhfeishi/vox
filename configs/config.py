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
    voxcpm05_path: str=""

    # Pydantic V2 的标准配置写法
    model_config = SettingsConfigDict(
        env_file='configs/.env',
        env_file_encoding='utf-8',
        extra='ignore'  # 建议改成 ignore，如果有未定义的变量直接忽略，不报错
        # case_sensitive=False # 默认就是 False，不需要写，这样才能让小写的 key 匹配大写的 ENV
    )
    
# 全局唯一实例
settings = Settings()