# -*- coding: utf-8 -*-
# voxapi/core/tts_local.py

from voxcpm import VoxCPM

from configs.config import settings

# tts model 全局唯一实例
_GLOBAL_TTS_MODEL = None


vox_model = VoxCPM.from_pretrained(settings.VOXCPM2_PATH, load_denoiser=False)





