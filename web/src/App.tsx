// web/src/App.tsx
import { useState, useEffect, useRef, useCallback } from 'react';
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

    // 粒子系统
    const particles = Array.from({ length: 80 }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: Math.random() * 3 + 0.5,
      orbitOffset: Math.random() * 30 - 15,
      speed: (Math.random() * 0.008 + 0.004) * (Math.random() > 0.5 ? 1 : -1),
      phase: Math.random() * Math.PI * 2,
    }));

    const render = () => {
      ctx.clearRect(0, 0, W, H);

      // lerp 音量
      smoothedVolume.current += (volume - smoothedVolume.current) * 0.12;
      const v = smoothedVolume.current;

      const cfg = STATE_CONFIG[state as keyof typeof STATE_CONFIG] ?? STATE_CONFIG.IDLE;
      const color = cfg.color;

      // 基础半径 & 脉动
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

      // 层1：远场大晕（深度感）
      const far = ctx.createRadialGradient(cx, cy, baseR * 0.2, cx, cy, baseR * 3.2);
      far.addColorStop(0, `${color}28`);
      far.addColorStop(0.5, `${color}10`);
      far.addColorStop(1, 'transparent');
      ctx.fillStyle = far;
      ctx.beginPath();
      ctx.arc(cx, cy, baseR * 3.2, 0, Math.PI * 2);
      ctx.fill();

      // 层2：中场霓虹圈
      const mid = ctx.createRadialGradient(cx, cy, baseR * 0.6, cx, cy, baseR * 1.8);
      mid.addColorStop(0, `${color}50`);
      mid.addColorStop(0.6, `${color}22`);
      mid.addColorStop(1, 'transparent');
      ctx.fillStyle = mid;
      ctx.beginPath();
      ctx.arc(cx, cy, baseR * 1.8, 0, Math.PI * 2);
      ctx.fill();

      // 层3：核心球体
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

      // 层4：高光点
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

      // 层5：轨道粒子
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

      // 思考时：旋转扫描弧
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

// ─── 休眠屏幕 ────────────────────────────────────────────────────
const SleepScreen = ({ onWake }: { onWake: () => void }) => (
  <div className="sleep-screen" onClick={onWake}>
    <div className="sleep-inner">
      <div className="sleep-ring" />
      <div className="sleep-ring delay1" />
      <div className="sleep-ring delay2" />
      <div className="sleep-title">百变</div>
      <div className="sleep-sub">说「你好」或「百变开机」以唤醒</div>
      <div className="sleep-tap">点击任意处继续</div>
    </div>
    <div className="scanline" />
  </div>
);

// ─── 关机屏幕 ────────────────────────────────────────────────────
const ShutdownScreen = () => (
  <div className="shutdown-screen">
    <div className="shutdown-inner">
      <div className="shutdown-icon">◉</div>
      <div className="shutdown-text">系统已离线</div>
      <div className="shutdown-sub">百变已进入休眠</div>
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

  const VOICE_NAMES: Record<string, string> = {
    default: '默认音色',
    leijun: '雷军',
    yizhongtian: '易中天',
    shuji: '书记',
    speaker: '我的声音',
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
      setIsSleeping(false);
      setSystemState('IDLE');
    } else if (type === 'voice_enrolled') {
      // 克隆完成通知，可选UI反馈
    } else if (type === 'shutdown') {
      setIsShutDown(true);
    }
  }, [lastMessage]);

  // TTS 音量采集
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

  // AI 输出结束后存档
  useEffect(() => {
    if (systemState === 'IDLE' && currentAiLine) {
      setAiLines(prev => [...prev.slice(-3), currentAiLine]);
      setCurrentAiLine('');
    }
  }, [systemState]);

  const cfg = STATE_CONFIG[systemState as keyof typeof STATE_CONFIG] ?? STATE_CONFIG.IDLE;

  if (isShutDown) return <ShutdownScreen />;

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@300;400&family=JetBrains+Mono:wght@300;400&display=swap');

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        :root {
          --bg: #070b12;
          --bg2: #0d1520;
          --border: rgba(255,255,255,0.06);
          --text: #e2e8f0;
          --text-dim: #4a5568;
          --font-display: 'Noto Serif SC', serif;
          --font-mono: 'JetBrains Mono', monospace;
        }

        body { background: var(--bg); color: var(--text); font-family: var(--font-mono); overflow: hidden; }

        /* ── 背景网格 ── */
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
            linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px);
          background-size: 40px 40px;
          pointer-events: none;
          z-index: 0;
        }

        /* ── 侧栏 ── */
        .sidebar {
          padding: 28px 20px;
          border-right: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          gap: 16px;
          position: relative;
          z-index: 1;
        }
        .sidebar.right { border-right: none; border-left: 1px solid var(--border); }

        .panel {
          background: rgba(255,255,255,0.03);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 18px;
        }
        .panel-title {
          font-size: 9px;
          letter-spacing: 0.2em;
          color: var(--text-dim);
          text-transform: uppercase;
          margin-bottom: 14px;
        }

        /* 音色列表 */
        .voice-list { display: flex; flex-direction: column; gap: 6px; }
        .voice-chip {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 12px;
          border-radius: 8px;
          font-size: 13px;
          color: var(--text-dim);
          border: 1px solid transparent;
          transition: all 0.25s;
          cursor: default;
        }
        .voice-chip.active {
          background: rgba(255,255,255,0.06);
          border-color: var(--border);
          color: var(--text);
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
          box-shadow: 0 0 6px #00f5a0;
        }

        /* ── 中央区域 ── */
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

        /* 状态行 */
        .status-row {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
        }
        .status-dot {
          width: 7px; height: 7px;
          border-radius: 50%;
          flex-shrink: 0;
          animation: dotPulse 2s ease-in-out infinite;
        }
        .status-label {
          font-size: 11px;
          letter-spacing: 0.15em;
          color: var(--text-dim);
          text-transform: uppercase;
        }
        @keyframes dotPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }

        /* 光球容器 */
        .orb-wrap {
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          margin: -20px 0;
        }

        /* ── 文字区域 ── */
        .text-zone {
          width: 100%;
          max-width: 580px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0;
          padding: 0 20px;
          min-height: 160px;
        }

        /* 用户输入区 */
        .user-bubble {
          align-self: flex-end;
          max-width: 85%;
          text-align: right;
          padding: 10px 16px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 16px 16px 4px 16px;
          font-size: 14px;
          color: #a0aec0;
          font-family: var(--font-display);
          font-weight: 300;
          letter-spacing: 0.02em;
          line-height: 1.6;
          transition: opacity 0.4s;
          margin-bottom: 12px;
        }
        .user-bubble.typing { border-color: rgba(0,245,160,0.25); }
        .user-bubble:empty { display: none; }

        /* AI 输出区 */
        .ai-bubble {
          align-self: flex-start;
          max-width: 92%;
          text-align: left;
          padding: 14px 20px;
          font-family: var(--font-display);
          font-size: 22px;
          font-weight: 300;
          letter-spacing: 0.03em;
          line-height: 1.7;
          color: var(--text);
          position: relative;
        }
        .ai-bubble::before {
          content: '';
          position: absolute;
          left: 0;
          top: 6px;
          bottom: 6px;
          width: 2px;
          border-radius: 2px;
          background: var(--accent-color, #4a5568);
          box-shadow: 0 0 8px var(--accent-color, #4a5568);
          transition: background 0.5s, box-shadow 0.5s;
        }
        .ai-bubble:empty { display: none; }

        /* 历史记录（渐隐）*/
        .ai-history {
          font-size: 14px;
          color: var(--text-dim);
          align-self: flex-start;
          padding: 4px 20px;
          font-family: var(--font-display);
          font-weight: 300;
          letter-spacing: 0.02em;
          line-height: 1.6;
          border-left: 1px solid var(--border);
          margin-bottom: 8px;
          margin-left: 0;
          max-width: 90%;
        }

        /* 光标 */
        .cursor {
          display: inline-block;
          width: 2px; height: 1.1em;
          background: currentColor;
          margin-left: 3px;
          vertical-align: middle;
          animation: blink 1s step-end infinite;
        }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

        /* 提示 */
        .hint {
          font-size: 12px;
          color: var(--text-dim);
          letter-spacing: 0.05em;
          margin-top: 8px;
          animation: float 3s ease-in-out infinite;
        }
        @keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }

        /* ── 右侧 Guide ── */
        .guide-item {
          display: flex;
          gap: 10px;
          align-items: flex-start;
          padding: 10px 0;
          border-bottom: 1px solid var(--border);
          font-size: 12px;
          color: var(--text-dim);
          line-height: 1.6;
        }
        .guide-item:last-child { border-bottom: none; }
        .guide-cmd {
          color: var(--text);
          font-family: var(--font-display);
          font-size: 13px;
          display: block;
          margin-bottom: 2px;
        }
        .guide-icon { flex-shrink: 0; margin-top: 2px; }

        /* 连接指示 */
        .conn-badge {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 10px;
          letter-spacing: 0.1em;
          color: var(--text-dim);
          text-transform: uppercase;
        }
        .conn-dot {
          width: 5px; height: 5px;
          border-radius: 50%;
        }
        .conn-dot.on { background: #00f5a0; box-shadow: 0 0 6px #00f5a0; }
        .conn-dot.off { background: #fc5c65; }

        /* ── 休眠屏幕 ── */
        .sleep-screen {
          position: fixed; inset: 0;
          background: #070b12;
          display: flex; align-items: center; justify-content: center;
          z-index: 200;
          cursor: pointer;
          overflow: hidden;
        }
        .sleep-inner {
          position: relative;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          gap: 16px;
        }
        .sleep-ring {
          position: absolute;
          width: 240px; height: 240px;
          border-radius: 50%;
          border: 1px solid rgba(0,245,160,0.15);
          animation: sleepExpand 3s ease-out infinite;
        }
        .sleep-ring.delay1 { animation-delay: 1s; }
        .sleep-ring.delay2 { animation-delay: 2s; }
        @keyframes sleepExpand {
          0%   { transform: scale(0.8); opacity: 0.6; }
          100% { transform: scale(2.5); opacity: 0; }
        }
        .sleep-title {
          font-family: var(--font-display);
          font-size: 52px;
          font-weight: 300;
          letter-spacing: 0.3em;
          color: #e2e8f0;
          margin-right: -0.3em;
          text-shadow: 0 0 40px rgba(0,245,160,0.3);
        }
        .sleep-sub {
          font-size: 12px;
          letter-spacing: 0.15em;
          color: #4a5568;
          text-transform: uppercase;
        }
        .sleep-tap {
          font-size: 11px;
          color: #2d3748;
          letter-spacing: 0.1em;
          margin-top: 8px;
          animation: float 3s ease-in-out infinite;
        }
        .scanline {
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 2px;
          background: linear-gradient(90deg, transparent, rgba(0,245,160,0.3), transparent);
          animation: scan 4s linear infinite;
          pointer-events: none;
        }
        @keyframes scan {
          0%   { top: 0; opacity: 0; }
          5%   { opacity: 1; }
          95%  { opacity: 1; }
          100% { top: 100%; opacity: 0; }
        }

        /* ── 关机屏幕 ── */
        .shutdown-screen {
          position: fixed; inset: 0;
          background: #070b12;
          display: flex; align-items: center; justify-content: center;
          z-index: 200;
        }
        .shutdown-inner {
          display: flex; flex-direction: column;
          align-items: center; gap: 16px;
          animation: shutdownFade 1.5s ease forwards;
        }
        @keyframes shutdownFade {
          0% { opacity: 0; transform: scale(0.95); }
          100% { opacity: 1; transform: scale(1); }
        }
        .shutdown-icon {
          font-size: 36px;
          color: #2d3748;
          animation: shutdownPulse 3s ease-in-out infinite;
        }
        @keyframes shutdownPulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.7; } }
        .shutdown-text {
          font-family: var(--font-display);
          font-size: 24px;
          font-weight: 300;
          letter-spacing: 0.2em;
          color: #4a5568;
        }
        .shutdown-sub {
          font-size: 11px;
          letter-spacing: 0.1em;
          color: #2d3748;
          text-transform: uppercase;
        }
      `}</style>

      {isShutDown ? <ShutdownScreen /> : null}
      {isSleeping ? <SleepScreen onWake={() => setIsSleeping(false)} /> : null}

      <div className="app">
        {/* ── 左侧栏 ── */}
        <div className="sidebar">
          <div className="panel-title">Voice Roster</div>

          <div className="panel">
            <div className="voice-list">
              {[
                { key: 'default', label: '默认音色' },
                { key: 'leijun', label: '雷军' },
                { key: 'yizhongtian', label: '易中天' },
                { key: 'speaker', label: '我的声音' },
              ].map(v => (
                <div key={v.key} className={`voice-chip ${currentVoice === v.key ? 'active' : ''}`}>
                  <span className="voice-chip-dot" />
                  {v.label}
                </div>
              ))}
            </div>
          </div>

          <div style={{ flex: 1 }} />

          <div className="conn-badge" style={{ paddingBottom: 8 }}>
            <span className={`conn-dot ${isConnected ? 'on' : 'off'}`} />
            {isConnected ? 'Connected' : 'Offline'}
          </div>
        </div>

        {/* ── 中央区域 ── */}
        <div className="main">
          <StatusDot state={systemState} />

          <div className="orb-wrap">
            <VoiceOrb volume={visualVolume} state={systemState} />
          </div>

          <div className="text-zone">
            {/* AI 历史（最近1条，渐隐） */}
            {aiLines.length > 0 && (
              <div className="ai-history">
                {aiLines[aiLines.length - 1]}
              </div>
            )}

            {/* 用户当前发言 */}
            {(currentUserLine || userLines.length > 0) && (
              <div className={`user-bubble ${currentUserLine ? 'typing' : ''}`}>
                {currentUserLine || userLines[userLines.length - 1]}
                {currentUserLine && <span className="cursor" />}
              </div>
            )}

            {/* AI 当前输出 */}
            {currentAiLine ? (
              <div
                className="ai-bubble"
                style={{ '--accent-color': cfg.color } as React.CSSProperties}
              >
                {currentAiLine}
                <span className="cursor" />
              </div>
            ) : systemState === 'LISTENING' ? (
              <div className="hint">请说话…</div>
            ) : systemState === 'THINKING' ? (
              <div className="hint" style={{ color: '#00d2ff' }}>思考中…</div>
            ) : null}
          </div>
        </div>

        {/* ── 右侧栏 ── */}
        <div className="sidebar right">
          <div className="panel-title">使用指南</div>

          <div className="panel">
            {[
              { icon: '🎙', cmd: '"用雷军的声音说"', desc: '切换克隆音色对话' },
              { icon: '🔄', cmd: '"换个声音说话"', desc: 'AI 自动选择音色' },
              { icon: '💤', cmd: '"百变休息"', desc: '进入休眠模式' },
            ].map((g, i) => (
              <div key={i} className="guide-item">
                <span className="guide-icon">{g.icon}</span>
                <div>
                  <span className="guide-cmd">{g.cmd}</span>
                  {g.desc}
                </div>
              </div>
            ))}
          </div>

          <div style={{ flex: 1 }} />

          <div className="panel" style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.7 }}>
            <div className="panel-title">System</div>
            <div>Model: qwen3-tts-vc</div>
            <div>ASR: streaming</div>
            <div>VAD: active</div>
          </div>
        </div>
      </div>
    </>
  );
}

export default App;
