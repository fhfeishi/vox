// web/src/App.tsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useVADRecorder } from './hooks/useVADRecorder';

// ─── 状态颜色系统 ────────────────────────────────────────────────
const STATE_CONFIG = {
  IDLE:      { color: '#4a5568', glow: '#4a5568', label: '待机' },
  SLEEPING:  { color: '#2d3748', glow: '#2d3748', label: '休眠' },
  LISTENING: { color: '#00f5a0', glow: '#00f5a0', label: '聆听' },
  THINKING:  { color: '#00d2ff', glow: '#00d2ff', label: '思考' },
  SPEAKING:  { color: '#f093fb', glow: '#f093fb', label: '播报' },
};

// ─── 核心光球组件 ────────────────────────────────────────────────
const VoiceOrb = ({ volume, state }: { volume: number; state: string }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const smoothedVolume = useRef(0);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;

    const particles = Array.from({ length: 80 }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: Math.random() * 3 + 0.5,
      orbitOffset: Math.random() * 30 - 15,
      speed: (Math.random() * 0.008 + 0.004) * (Math.random() > 0.5 ? 1 : -1),
      phase: Math.random() * Math.PI * 2,
    }));

    const render = () => {
      ctx.clearRect(0, 0, W, H);
      smoothedVolume.current += (volume - smoothedVolume.current) * 0.12;
      const v = smoothedVolume.current;

      const cfg = STATE_CONFIG[state as keyof typeof STATE_CONFIG] ?? STATE_CONFIG.IDLE;
      const color = cfg.color;

      let baseR: number;
      const t = Date.now();

      if (state === 'LISTENING') {
        baseR = 72 + v * 55;
      } else if (state === 'THINKING') {
        baseR = 72 + Math.sin(t / 180) * 12 + Math.sin(t / 290) * 6;
      } else if (state === 'SPEAKING') {
        baseR = 76 + v * 70;
      } else {
        baseR = 68 + Math.sin(t / 1200) * 5;
      }

      const far = ctx.createRadialGradient(cx, cy, baseR * 0.2, cx, cy, baseR * 3.2);
      far.addColorStop(0, `${color}28`);
      far.addColorStop(0.5, `${color}10`);
      far.addColorStop(1, 'transparent');
      ctx.fillStyle = far;
      ctx.beginPath();
      ctx.arc(cx, cy, baseR * 3.2, 0, Math.PI * 2);
      ctx.fill();

      const mid = ctx.createRadialGradient(cx, cy, baseR * 0.6, cx, cy, baseR * 1.8);
      mid.addColorStop(0, `${color}50`);
      mid.addColorStop(0.6, `${color}22`);
      mid.addColorStop(1, 'transparent');
      ctx.fillStyle = mid;
      ctx.beginPath();
      ctx.arc(cx, cy, baseR * 1.8, 0, Math.PI * 2);
      ctx.fill();

      ctx.save();
      ctx.shadowBlur = 40;
      ctx.shadowColor = color;
      const core = ctx.createRadialGradient(cx - baseR * 0.25, cy - baseR * 0.25, 0, cx, cy, baseR);
      core.addColorStop(0, `${color}ff`);
      core.addColorStop(0.5, `${color}cc`);
      core.addColorStop(1, `${color}44`);
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, baseR, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.shadowBlur = 0;
      const hl = ctx.createRadialGradient(
        cx - baseR * 0.3, cy - baseR * 0.3, 0,
        cx - baseR * 0.3, cy - baseR * 0.3, baseR * 0.4
      );
      hl.addColorStop(0, 'rgba(255,255,255,0.5)');
      hl.addColorStop(1, 'transparent');
      ctx.fillStyle = hl;
      ctx.beginPath();
      ctx.arc(cx - baseR * 0.3, cy - baseR * 0.3, baseR * 0.4, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.shadowBlur = 8;
      ctx.shadowColor = color;
      particles.forEach((p) => {
        p.angle += p.speed * (1 + v * 8);
        const orbitR = baseR * 1.45 + p.orbitOffset + Math.sin(t / 400 + p.phase) * 8 + v * 40;
        const px = cx + Math.cos(p.angle) * orbitR;
        const py = cy + Math.sin(p.angle) * orbitR;
        const alpha = 0.4 + Math.sin(t / 300 + p.phase) * 0.3;
        ctx.fillStyle = `${color}${Math.round(alpha * 255).toString(16).padStart(2, '0')}`;
        ctx.beginPath();
        ctx.arc(px, py, p.radius, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.restore();

      if (state === 'THINKING') {
        ctx.save();
        ctx.strokeStyle = `${color}66`;
        ctx.lineWidth = 1.5;
        ctx.shadowBlur = 12;
        ctx.shadowColor = color;
        const scanAngle = (t / 800) % (Math.PI * 2);
        ctx.beginPath();
        ctx.arc(cx, cy, baseR * 1.9, scanAngle, scanAngle + Math.PI * 0.6);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(cx, cy, baseR * 2.3, scanAngle + Math.PI, scanAngle + Math.PI + Math.PI * 0.4);
        ctx.stroke();
        ctx.restore();
      }

      frameRef.current = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(frameRef.current);
  }, [volume, state]);

  return (
    <canvas
      ref={canvasRef}
      width={500}
      height={500}
      style={{ width: '320px', height: '320px', filter: 'contrast(1.05)' }}
    />
  );
};

// ─── 休眠屏幕 (保持深邃神秘) ──────────────────────────────────────────
const SleepScreen = ({ onWake }: { onWake: () => void }) => (
  <div className="sleep-screen" onClick={onWake}>
    <div className="sleep-inner">
      <div className="sleep-ring" />
      <div className="sleep-ring delay1" />
      <div className="sleep-ring delay2" />
      <div className="sleep-title">百变</div>
      <div className="sleep-sub">说「你好」或「百变开机」以唤醒</div>
      <div className="sleep-tap">点击屏幕任意处强制唤醒</div>
    </div>
    <div className="scanline" />
  </div>
);

// ─── 关机屏幕 (高级待机舱风格) ────────────────────────────────────────
const ShutdownScreen = () => (
  <div className="shutdown-screen">
    <div className="shutdown-inner">
      <div className="shutdown-orb" />
      <div className="shutdown-text">System Offline</div>
      <div className="shutdown-sub">百变已进入深度休眠</div>
      
      <div className="shutdown-hint">
        💡 想要再次交流？<br/>
        请直接对我说：<span className="highlight">「百变开机」</span>或<span className="highlight">「你好」</span>
      </div>
    </div>
  </div>
);

// ─── 状态指示器 ──────────────────────────────────────────────────
const StatusDot = ({ state }: { state: string }) => {
  const cfg = STATE_CONFIG[state as keyof typeof STATE_CONFIG] ?? STATE_CONFIG.IDLE;
  return (
    <div className="status-row">
      <span className="status-dot" style={{ background: cfg.color, boxShadow: `0 0 8px ${cfg.glow}` }} />
      <span className="status-label">{cfg.label}</span>
    </div>
  );
};

// ─── 主应用 ──────────────────────────────────────────────────────
function App() {
  const [userLines, setUserLines] = useState<string[]>([]);
  const [aiLines, setAiLines] = useState<string[]>([]);
  const [currentUserLine, setCurrentUserLine] = useState('');
  const [currentAiLine, setCurrentAiLine] = useState('');
  const [currentVoice, setCurrentVoice] = useState('default');
  const [isSleeping, setIsSleeping] = useState(true);
  const [isShutDown, setIsShutDown] = useState(false);
  const [visualVolume, setVisualVolume] = useState(0);
  const [systemState, setSystemState] = useState('IDLE');

  const playCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  // 🚀 新增：关机定时器引用，用于随时拦截
  const shutdownTimerRef = useRef<NodeJS.Timeout | null>(null);
  
  // 音色别名反向映射 (用于前端展示)
  const VOICE_NAMES: Record<string, string> = {
    default: '默认女声 (Cherry)',
    leijun: '雷军',
    yizhongtian: '易中天',
    shuji: '书记',
    wuhannvhai: '武汉女孩',
    speaker: '我的专属声音',
    男声: '默认男声 (Ethan)',
    女声: '默认女声 (Cherry)',
  };

  const playAudioChunk = useCallback((arrayBuffer: ArrayBuffer) => {
    if (!playCtxRef.current) {
      playCtxRef.current = new window.AudioContext({ sampleRate: 24000 });
      analyserRef.current = playCtxRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      analyserRef.current.connect(playCtxRef.current.destination);
    }
    const audioCtx = playCtxRef.current;
    if (audioCtx.state === 'suspended') audioCtx.resume();

    const int16Data = new Int16Array(arrayBuffer);
    const float32Data = new Float32Array(int16Data.length);
    for (let i = 0; i < int16Data.length; i++) float32Data[i] = int16Data[i] / 32768.0;

    const buf = audioCtx.createBuffer(1, float32Data.length, 24000);
    buf.getChannelData(0).set(float32Data);

    const source = audioCtx.createBufferSource();
    source.buffer = buf;
    source.connect(analyserRef.current!);

    const now = audioCtx.currentTime;
    if (nextPlayTimeRef.current < now) nextPlayTimeRef.current = now;
    source.start(nextPlayTimeRef.current);
    nextPlayTimeRef.current += buf.duration;
  }, []);

  const { isConnected, lastMessage, sendMessage } = useWebSocket(
    'ws://localhost:8000/ws/chat',
    playAudioChunk
  );

  const { isRecording, start } = useVADRecorder({
    onAudioChunk: (chunk) => {
      sendMessage(chunk.buffer);
      let sum = 0;
      for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
      const rms = Math.sqrt(sum / chunk.length);
      if (systemState === 'LISTENING') setVisualVolume(rms * 5);
    },
    onSpeechEvent: (eventType) => {
      if (eventType === 'speech_start') setSystemState('LISTENING');
      sendMessage(JSON.stringify({ type: eventType }));
    },
  });

  // 🛡️ 核心优化：前端防卡死看门狗 (Watchdog)
  useEffect(() => {
    let watchdogTimer: NodeJS.Timeout;

    if (systemState === 'THINKING') {
      watchdogTimer = setTimeout(() => {
        console.warn("⚠️ [Watchdog] API 响应超时！强行恢复互动状态以避免死锁。");
        
        if (playCtxRef.current) {
          playCtxRef.current.close();
          playCtxRef.current = null;
        }
        
        setAiLines(prev => [...prev.slice(-2), "⚠️ 网络信号似乎开小差了，能再说一遍吗？"]);
        setCurrentAiLine("");
        setSystemState('LISTENING');
        
        // 向后端发送假信号，触发后端的截杀清理逻辑
        sendMessage(JSON.stringify({ type: "speech_start" })); 
        
      }, 12000); 
    }

    return () => {
      if (watchdogTimer) clearTimeout(watchdogTimer);
    };
  }, [systemState, sendMessage]);

  useEffect(() => {
    if (!lastMessage) return;
    const type = lastMessage.type;

    if (type === 'asr_partial') {
      setCurrentUserLine(lastMessage.text);
    } else if (type === 'asr_final') {
      const finalText = lastMessage.text;
      setUserLines(prev => [...prev.slice(-3), finalText]);
      setCurrentUserLine('');
      setCurrentAiLine('');
      setSystemState('THINKING');
    } else if (type === 'llm_text') {
      setCurrentAiLine(prev => prev + lastMessage.text);
      setSystemState('SPEAKING');
    } else if (type === 'voice_changed') {
      setCurrentVoice(lastMessage.voice);
    } else if (type === 'stop_audio') {
      if (playCtxRef.current) {
        playCtxRef.current.close();
        playCtxRef.current = null;
      }
      if (currentAiLine) {
        setAiLines(prev => [...prev.slice(-3), currentAiLine]);
        setCurrentAiLine('');
      }
      setSystemState('LISTENING');
    } else if (type === 'woken_up') {
      // 🚀 核心逻辑：如果系统在准备关机时，用户突然喊了“开机”，立刻拦截关机动作！
      if (shutdownTimerRef.current) {
        clearTimeout(shutdownTimerRef.current);
        shutdownTimerRef.current = null;
      }
      setIsSleeping(false);
      setIsShutDown(false); 
      setSystemState('IDLE');
    } else if (type === 'voice_enrolled') {
      // 克隆完成通知 (未来可接入 UI 反馈)
    } else if (type === 'shutdown') {
      // 🚀 终极时序优化：前端根据 Web Audio API 精准计算剩余播放时间
      let delay = 0;
      if (playCtxRef.current) {
        const now = playCtxRef.current.currentTime;
        const end = nextPlayTimeRef.current;
        if (end > now) {
          delay = (end - now) * 1000; // 换算成毫秒
        }
      }
      
      // 设置定时器：等音频正好播完，加上 800ms 的自然停顿缓冲，然后优雅黑屏
      shutdownTimerRef.current = setTimeout(() => {
        setIsShutDown(true);
        // 顺手把界面的对话记录清理干净，保证下次开机清清爽爽
        setCurrentAiLine('');
        setCurrentUserLine('');
        setAiLines([]);
        setUserLines([]);
        setSystemState('IDLE');
      }, delay + 800); 
    }
  }, [lastMessage]);

  useEffect(() => {
    let frame: number;
    const update = () => {
      if (systemState === 'SPEAKING' && analyserRef.current) {
        const data = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(data);
        const avg = data.reduce((a, b) => a + b, 0) / data.length;
        setVisualVolume(avg / 100);
      }
      frame = requestAnimationFrame(update);
    };
    update();
    return () => cancelAnimationFrame(frame);
  }, [systemState]);

  useEffect(() => {
    if (isConnected && !isRecording) start();
  }, [isConnected, isRecording, start]);

  useEffect(() => {
    if (systemState === 'IDLE' && currentAiLine) {
      setAiLines(prev => [...prev.slice(-3), currentAiLine]);
      setCurrentAiLine('');
    }
  }, [systemState]);

  const cfg = STATE_CONFIG[systemState as keyof typeof STATE_CONFIG] ?? STATE_CONFIG.IDLE;

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@300;400;600&family=JetBrains+Mono:wght@300;400&display=swap');

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        :root {
          --bg: ${isSleeping || isShutDown ? '#020305' : '#0a111a'};
          --bg-grid: ${isSleeping || isShutDown ? 'rgba(255,255,255,0.01)' : 'rgba(255,255,255,0.03)'};
          --border: rgba(255,255,255,0.08);
          --text: #e2e8f0;
          --text-dim: #64748b;
          --font-display: 'Noto Serif SC', serif;
          --font-mono: 'JetBrains Mono', monospace;
        }

        body { 
          background: var(--bg); 
          color: var(--text); 
          font-family: var(--font-mono); 
          overflow: hidden; 
          transition: background 1.5s ease;
        }

        .app {
          display: grid;
          grid-template-columns: 260px 1fr 260px;
          grid-template-rows: 1fr;
          height: 100vh;
          position: relative;
          overflow: hidden;
        }
        .app::before {
          content: '';
          position: fixed;
          inset: 0;
          background-image:
            linear-gradient(var(--bg-grid) 1px, transparent 1px),
            linear-gradient(90deg, var(--bg-grid) 1px, transparent 1px);
          background-size: 40px 40px;
          pointer-events: none;
          z-index: 0;
          transition: background-image 1.5s ease;
        }

        .sidebar {
          padding: 32px 24px;
          border-right: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          gap: 20px;
          position: relative;
          z-index: 1;
          background: linear-gradient(90deg, rgba(0,0,0,0.2) 0%, transparent 100%);
        }
        .sidebar.right { 
          border-right: none; 
          border-left: 1px solid var(--border);
          background: linear-gradient(-90deg, rgba(0,0,0,0.2) 0%, transparent 100%);
        }

        .panel {
          background: rgba(255,255,255,0.02);
          border: 1px solid rgba(255,255,255,0.05);
          border-radius: 12px;
          padding: 20px;
          box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }
        .panel-title {
          font-size: 11px;
          letter-spacing: 0.25em;
          color: var(--text-dim);
          text-transform: uppercase;
          margin-bottom: 16px;
        }

        .voice-list { display: flex; flex-direction: column; gap: 8px; }
        .voice-chip {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 14px;
          border-radius: 8px;
          font-size: 15px; 
          color: var(--text-dim);
          border: 1px solid transparent;
          transition: all 0.25s;
          cursor: default;
        }
        .voice-chip.active {
          background: rgba(255,255,255,0.08);
          border-color: rgba(255,255,255,0.15);
          color: var(--text);
          box-shadow: 0 0 15px rgba(255,255,255,0.05);
        }
        .voice-chip-dot {
          width: 6px; height: 6px;
          border-radius: 50%;
          background: var(--text-dim);
          flex-shrink: 0;
          transition: all 0.3s;
        }
        .voice-chip.active .voice-chip-dot {
          background: #00f5a0;
          box-shadow: 0 0 8px #00f5a0;
        }

        .main {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 0;
          position: relative;
          z-index: 1;
          overflow: hidden;
        }

        .status-row {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 10px;
        }
        .status-dot {
          width: 8px; height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
          animation: dotPulse 2s ease-in-out infinite;
        }
        .status-label {
          font-size: 12px;
          letter-spacing: 0.2em;
          color: var(--text-dim);
          text-transform: uppercase;
        }
        @keyframes dotPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }

        .orb-wrap {
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          margin: -10px 0;
        }

        .text-zone {
          width: 100%;
          max-width: 600px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0;
          padding: 0 20px;
          min-height: 180px;
        }

        .user-bubble {
          align-self: flex-end;
          max-width: 85%;
          text-align: right;
          padding: 12px 18px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.05);
          border-radius: 16px 16px 4px 16px;
          font-size: 16px;
          color: #a0aec0;
          font-family: var(--font-display);
          font-weight: 300;
          letter-spacing: 0.03em;
          line-height: 1.6;
          transition: opacity 0.4s;
          margin-bottom: 16px;
        }
        .user-bubble.typing { border-color: rgba(0,245,160,0.3); }
        .user-bubble:empty { display: none; }

        .ai-bubble {
          align-self: flex-start;
          max-width: 95%;
          text-align: left;
          padding: 16px 24px;
          font-family: var(--font-display);
          font-size: 24px;
          font-weight: 300;
          letter-spacing: 0.04em;
          line-height: 1.8;
          color: var(--text);
          position: relative;
        }
        .ai-bubble::before {
          content: '';
          position: absolute;
          left: 0;
          top: 8px;
          bottom: 8px;
          width: 3px;
          border-radius: 3px;
          background: var(--accent-color, #4a5568);
          box-shadow: 0 0 12px var(--accent-color, #4a5568);
          transition: background 0.5s, box-shadow 0.5s;
        }
        .ai-bubble:empty { display: none; }

        .ai-history {
          font-size: 15px;
          color: var(--text-dim);
          align-self: flex-start;
          padding: 6px 24px;
          font-family: var(--font-display);
          font-weight: 300;
          letter-spacing: 0.03em;
          line-height: 1.6;
          border-left: 2px solid rgba(255,255,255,0.05);
          margin-bottom: 12px;
          max-width: 90%;
        }

        .guide-item {
          display: flex;
          gap: 12px;
          align-items: flex-start;
          padding: 12px 0;
          border-bottom: 1px solid rgba(255,255,255,0.05);
          font-size: 14px; 
          color: var(--text-dim);
          line-height: 1.6;
        }
        .guide-item:last-child { border-bottom: none; }
        .guide-cmd {
          color: var(--text);
          font-family: var(--font-display);
          font-size: 15px; 
          display: block;
          margin-bottom: 4px;
        }

        /* ── 休眠屏幕 ── */
        .sleep-screen {
          position: fixed; inset: 0;
          background: #030508; 
          display: flex; align-items: center; justify-content: center;
          z-index: 200;
          cursor: pointer;
        }
        .sleep-inner {
          position: relative;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          gap: 20px;
        }
        .sleep-ring {
          position: absolute;
          width: 280px; height: 280px;
          border-radius: 50%;
          border: 1px solid rgba(0,245,160,0.1);
          animation: sleepExpand 4s ease-out infinite;
        }
        .sleep-ring.delay1 { animation-delay: 1.3s; }
        .sleep-ring.delay2 { animation-delay: 2.6s; }
        @keyframes sleepExpand {
          0%   { transform: scale(0.8); opacity: 0.5; }
          100% { transform: scale(2.8); opacity: 0; }
        }
        .sleep-title {
          font-family: var(--font-display);
          font-size: 64px;
          font-weight: 300;
          letter-spacing: 0.3em;
          color: #e2e8f0;
          margin-right: -0.3em;
          text-shadow: 0 0 50px rgba(0,245,160,0.2);
        }
        .sleep-sub {
          font-size: 13px;
          letter-spacing: 0.2em;
          color: #4a5568;
          text-transform: uppercase;
        }

        /* 🚀 关机屏幕：科技感待机舱风格 */
        .shutdown-screen {
          position: fixed; inset: 0;
          background: #020305; 
          display: flex; align-items: center; justify-content: center;
          z-index: 200;
        }
        .shutdown-inner {
          display: flex; flex-direction: column;
          align-items: center; gap: 16px;
          text-align: center;
          animation: fadeDown 1.5s ease-out forwards;
        }
        @keyframes fadeDown {
          0% { opacity: 0; transform: translateY(-20px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        .shutdown-orb {
          width: 12px; height: 12px;
          border-radius: 50%;
          background: #4a5568;
          box-shadow: 0 0 15px #4a5568;
          margin-bottom: 8px;
          animation: dimPulse 4s ease-in-out infinite;
        }
        @keyframes dimPulse {
          0%, 100% { opacity: 0.2; transform: scale(0.8); }
          50% { opacity: 0.8; transform: scale(1.2); }
        }
        .shutdown-text {
          font-family: var(--font-mono);
          font-size: 24px; 
          letter-spacing: 0.5em;
          color: #64748b;
          text-transform: uppercase;
          margin-right: -0.5em;
        }
        .shutdown-sub {
          font-size: 13px;
          letter-spacing: 0.3em;
          color: #334155;
          text-transform: uppercase;
        }
        .shutdown-hint {
          margin-top: 40px;
          font-size: 18px; 
          color: #94a3b8;
          letter-spacing: 0.1em;
          line-height: 1.8;
          background: rgba(255,255,255,0.02);
          padding: 24px 40px;
          border-radius: 16px;
          border: 1px solid rgba(255,255,255,0.05);
          box-shadow: 0 10px 30px rgba(0,0,0,0.2);
          animation: float 4s ease-in-out infinite;
        }
        .shutdown-hint .highlight {
          color: #00f5a0;
          font-weight: 600;
          opacity: 0.9;
        }
        @keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
      `}</style>

      {/* 状态遮罩层 */}
      {isShutDown ? <ShutdownScreen /> : null}
      {isSleeping && !isShutDown ? <SleepScreen onWake={() => setIsSleeping(false)} /> : null}

      <div className="app">
        {/* ── 左侧栏 ── */}
        <div className="sidebar">
          <div className="panel-title">Voice Roster</div>

          <div className="panel">
            <div className="voice-list">
              {[
                { key: 'default', label: '默认女声 (Cherry)' },
                { key: '男声', label: '默认男声 (Ethan)' },
                { key: 'leijun', label: '雷军' },
                { key: 'yizhongtian', label: '易中天' },
                { key: 'speaker', label: '我的专属声音' },
              ].map(v => (
                <div key={v.key} className={`voice-chip ${currentVoice === v.key || (v.key==='男声' && currentVoice==='龙老铁') ? 'active' : ''}`}>
                  <span className="voice-chip-dot" />
                  {v.label}
                </div>
              ))}
            </div>
          </div>

          <div style={{ flex: 1 }} />

          <div className="conn-badge" style={{ paddingBottom: 8, fontSize: '11px', color: 'var(--text-dim)', display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span className="conn-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: isConnected ? '#00f5a0' : '#fc5c65', boxShadow: isConnected ? '0 0 8px #00f5a0' : 'none' }} />
            {isConnected ? 'SYSTEM ONLINE' : 'DISCONNECTED'}
          </div>
        </div>

        {/* ── 中央区域 ── */}
        <div className="main">
          <StatusDot state={systemState} />

          <div className="orb-wrap">
            <VoiceOrb volume={visualVolume} state={systemState} />
          </div>

          <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 8, letterSpacing: '0.1em', fontFamily: 'var(--font-display)' }}>
            正在使用音色：<span style={{ color: '#00f5a0', fontWeight: 600 }}>{VOICE_NAMES[currentVoice] || currentVoice}</span>
          </div>

          <div className="text-zone">
            {aiLines.length > 0 && (
              <div className="ai-history">
                {aiLines[aiLines.length - 1]}
              </div>
            )}

            {(currentUserLine || userLines.length > 0) && (
              <div className={`user-bubble ${currentUserLine ? 'typing' : ''}`}>
                {currentUserLine || userLines[userLines.length - 1]}
                {currentUserLine && <span className="cursor" style={{display: 'inline-block', width: 2, height: '1.2em', background: 'currentColor', marginLeft: 4, verticalAlign: 'middle', animation: 'blink 1s step-end infinite'}} />}
              </div>
            )}

            {currentAiLine ? (
              <div
                className="ai-bubble"
                style={{ '--accent-color': cfg.color } as React.CSSProperties}
              >
                {currentAiLine}
                <span className="cursor" style={{display: 'inline-block', width: 3, height: '1.2em', background: 'currentColor', marginLeft: 6, verticalAlign: 'middle', animation: 'blink 1s step-end infinite'}} />
              </div>
            ) : systemState === 'LISTENING' ? (
              <div style={{fontSize: 14, color: 'var(--text-dim)', letterSpacing: '0.1em', marginTop: 12, animation: 'float 3s ease-in-out infinite'}}>请说话…</div>
            ) : systemState === 'THINKING' ? (
              <div style={{fontSize: 14, color: '#00d2ff', letterSpacing: '0.1em', marginTop: 12, animation: 'float 3s ease-in-out infinite'}}>逻辑解算中…</div>
            ) : null}
          </div>
        </div>

        {/* ── 右侧栏 ── */}
        <div className="sidebar right">
          <div className="panel-title">Interactive Guide</div>

          <div className="panel">
            {[
              { icon: '🎙', cmd: '"用雷军的声音说"', desc: '触发目标音色克隆对话' },
              { icon: '🔄', cmd: '"换个男声说话"', desc: '由 AI 自动指派适合音色' },
              { icon: '💤', cmd: '"百变关机"', desc: '切断输出并进入深度休眠' },
            ].map((g, i) => (
              <div key={i} className="guide-item">
                <span style={{flexShrink: 0, marginTop: 2}}>{g.icon}</span>
                <div>
                  <span className="guide-cmd">{g.cmd}</span>
                  {g.desc}
                </div>
              </div>
            ))}
          </div>

          <div style={{ flex: 1 }} />

          <div className="panel" style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.8, fontFamily: 'var(--font-mono)' }}>
            <div className="panel-title">Telemetry</div>
            <div>Model: qwen3-tts-vc</div>
            <div>ASR: paraformer-realtime</div>
            <div>VAD: Active (Always-on)</div>
            <div>Watchdog: Armed (12s)</div>
          </div>
        </div>
      </div>
    </>
  );
}

export default App;