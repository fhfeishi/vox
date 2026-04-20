// web/src/hooks/useVADRecorder.ts
import { useState, useRef, useCallback } from 'react';

interface VADOptions {
  onAudioChunk: (chunk: Float32Array) => void;
  onSpeechEvent: (eventType: 'speech_start' | 'speech_end') => void;
}

export function useVADRecorder({ onAudioChunk, onSpeechEvent }: VADOptions) {
  const [isRecording, setIsRecording] = useState(false);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: { 
          channelCount: 1, 
          sampleRate: 16000, 
          echoCancellation: true, 
          noiseSuppression: true,
          autoGainControl: true
        } 
      });
      mediaStreamRef.current = stream;
      
      const audioCtx = new window.AudioContext({ sampleRate: 16000 });
      await audioCtx.audioWorklet.addModule('/audio-processor.js');
      
      const source = audioCtx.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioCtx, 'audio-capture-processor');
      workletNodeRef.current = workletNode;

      workletNode.port.onmessage = (event) => {
        const { event: type, data } = event.data;
        if (type === 'audio_chunk') onAudioChunk(data);
        else onSpeechEvent(type as 'speech_start' | 'speech_end');
      };

      source.connect(workletNode);
      setIsRecording(true);
    } catch (err) {
      console.error('麦克风启动失败:', err);
    }
  };

  const stop = useCallback(() => {
    workletNodeRef.current?.disconnect();
    mediaStreamRef.current?.getTracks().forEach(t => t.stop());
    setIsRecording(false);
  }, []);

  return { isRecording, start, stop };
}