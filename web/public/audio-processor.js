// web/public/audio-processor.js
class AudioCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
      super();
      this.isSpeaking = false;
      this.silenceThreshold = 0.008; // 能量阈值（可调）
      this.silenceFrames = 0;
      this.SILENCE_LIMIT = 25; // 约 0.5s 静音触发断句 (128 samples/frame @ 16kHz)
    }
  
    process(inputs) {
      const input = inputs[0]?.[0];
      if (!input) return true;
  
      // 1. 简单 VAD：计算 RMS 能量
      let sum = 0;
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
      const rms = Math.sqrt(sum / input.length);
      const isVoice = rms > this.silenceThreshold;
  
      // 2. 状态机控制
      if (isVoice) {
        if (!this.isSpeaking) {
          this.isSpeaking = true;
          this.silenceFrames = 0;
          this.port.postMessage({ event: 'speech_start' });
        }
        this.silenceFrames = 0;
      } else {
        this.silenceFrames++;
        if (this.isSpeaking && this.silenceFrames > this.SILENCE_LIMIT) {
          this.isSpeaking = false;
          this.port.postMessage({ event: 'speech_end' });
        }
      }
  
      // 3. Float32 [-1,1] -> Int16 PCM (16bit)
      const int16 = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        int16[i] = Math.round(s < 0 ? s * 32768 : s * 32767);
      }
  
      // 4. 发送音频块（使用 Transferable 零拷贝）
      this.port.postMessage({ event: 'audio_chunk', data: int16 }, [int16.buffer]);
      return true;
    }
  }
  
  registerProcessor('audio-capture-processor', AudioCaptureProcessor);
  