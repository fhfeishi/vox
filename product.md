# VOX  高自然度、支持实时声纹克隆、全双工交互的 AI 桌面语音终端
1. **功能概览**
    1. 实时声纹克隆与切换：支持官方预设音色（雷军、易中天等）的实时切换，
       并支持通过 3~8 秒的纯净音频动态克隆用户本人的专属声音（speaker）。
    2. 全双工与自然打断 (Barge-in)：支持在 AI 思考或说话时，用户随时插话打断，实现极低延迟的对话交锋。
    3. 零延迟的系统控制：用户发出“关机”、“开机”等指令时，系统通过本地缓存音频与前端精准计时，实现 0 延迟的语音及视觉黑屏反馈。
    4. 沉浸式视觉交互：通过 Canvas 渲染随音量和状态（思考、聆听、播报、休眠）动态变色的呼吸光球（Voice Orb），
       辅以动态更新的音色侧边栏（Voice Roster）。
2. **工程架构与实现路线 (Engineering Roadmap)**
VOX 的演进分为四个核心阶段，从基础链路打通走向极致工业级体验：
   1. 阶段一：基础管线构建 (Pipeline Foundation)
   目标：搭建前端麦克风采集 -> 后端流式处理 -> 前端播放的闭环。
    实现：使用 FastAPI 建立 WebSocket 通道。集成阿里云 DashScope 的 ASR（语音识别）、Qwen LLM（大模型流式输出）、TTS（文本转语音流式合成）。前端利用 Web Audio API 播放 PCM 二进制流。
   2. 阶段二：全双工与状态管理 (Full-Duplex & State Machine)
   目标：解决“单向对讲机”体验，实现系统级状态机。
   实现：引入核心状态机 (SLEEPING, IDLE, LISTENING, THINKING, SPEAKING)。前端引入 VAD（静音检测），通过 speech_start/end 辅助后端判断。后端实现强杀协程（_cancel_output）逻辑以支持打断。
   3. 阶段三：动态能力与本地化重构 (Dynamic Features & Localization)
   目标：支持大模型主动控制音色，并解决云端 API 的不稳定因素。
   实现：
      - 动态提示词注入：在 LLM 的 System Prompt 中注入动态可用音色表，LLM 通过输出 [VOICE_CTRL: {"target": "..."}] 控制 TTS 引擎切换。
      - 本地 ASR 降级：因云端 API 欠费/限流风险，将 ASR 引擎无缝切换为本地 FunASR (asr_local.py)，剥离网络依赖。
   4. 阶段四：极致时序与防卡死自愈 (Resilience & Edge-case Optimization)
   目标：消除幽灵音频（诈尸）、假死、无响应等并发 Bug。
   实现：引入“无敌过渡态”（SHUTTING_DOWN, WAKING_UP）免疫环境底噪误打断；引入 12s 看门狗（Watchdog）与指数退避断线重连；TTS 引擎实现彻底的线程隔离销毁。
3. **核心工程实现说明 (Crucial Engineering Details)**
工程的成败在于细节，以下是我们为解决特定“顽疾”而设计的核心机制：
   1. 语义级防误打断与状态护盾 (Semantic Barge-in & Transition Shields)
      - 痛点：早期的 VAD 过于灵敏，用户的呼吸声或键盘声会轻易触发打断，导致 AI “经常闭嘴不说话”；同时，在播放关机音效时如果收到杂音，会导致关机任务被“自我腰斩”（协程自杀）。
      - 工程实现：
          - 语义打断：剥夺了 VAD 纯音频信号的打断权。必须等到 ASR 吐出 asr_partial 且有效中文字符 len >= 2 时，后端才判定为真正的人类插话，触发 _cancel_output()。
          - 状态护盾：引入 SHUTTING_DOWN 和 WAKING_UP 过渡态。在此状态下，管线强行 continue 忽略一切 ASR 识别结果，确保关机/开机动画与语音 100% 执行完毕。
   2. 前端音频时间轴与防“诈尸” (AudioContext Axis & Anti-Zombie Audio)
      - 痛点：打断 AI 后，上一轮未播完的音频会与新一轮音频重叠播放；或者出现“只有字，过了半天突然出声音”的诡异延迟。
      - 工程实现：
        - 硬件级重置：前端接收到 stop_audio 指令时，不仅关闭 playCtxRef.current，且必须强制将调度指针 nextPlayTimeRef.current 归零。
        - 物理隔离阀门：引入 isAudioAllowedRef 引用开关。只要发生打断或收到完整的最终识别结果，立刻关阀，直接丢弃 WebSocket 管道中残余的“幽灵 TTS 音频帧”。
   3. TTS 线程隔离与纯内存声纹管理 (TTS Thread Isolation & Memory-Only VC)
      - 痛点：阿里云的 TTS WebSocket 如果遇到网络闪断，同步的 .close() 和 .connect() 会彻底堵死 Python 的 asyncio 事件循环，导致全站假死；且克隆的 Voice ID 有几小时的过期时间，持久化到本地 JSON 会导致隔天启动直接报错。
      - 工程实现：
        - 抛弃本地缓存：彻底删除 voice_cache.json。每次启动服务端时，调用 preload_local_refs 自动在后台向阿里云请求最新鲜的临时 Voice ID，仅存在内存 (self.enrolled_voices) 中。
        - 异步避障：将 SDK 所有的网络 I/O 方法（建连、发送文本、强关 Socket）全部通过 asyncio.to_thread() 抛入后台线程池。即使底层 Socket 死锁，主程序的语音识别与路由分发也依然丝滑运行。
   4. 零延迟本地指令分流 (Zero-Latency Local Dispatch)
      - 痛点：说出“关机”后，若走完整管线（大模型生成 -> TTS 合成 -> 播放），往往需要 1.5 秒以上的延迟，极不自然。
      - 工程实现：
        - 在 _message_router 中进行关键字前置拦截。
        - 命中“关机”后，后端直接读取硬盘上的 .wav PCM 二进制流，通过一个简单的 for 循环伪装成流式发给前端。
        - 前端利用 Web Audio API 获取精确的 delay = end - now（剩余播放时间），并设置 setTimeout，实现语音最后一个字落下的瞬间，UI 精准黑屏。
```
VOX
├── /configs
│   ├── config.py        # 音色映射字典、API Keys、VAD参数等
│   └── .env             # 环境变量
├── /locals
│   └── /ref             # 预留参考音频 (default.wav, zhangsan.wav ...)
├── /voxapi
│   ├── /core
│   │   ├── asr_api.py       # 封装流式ASR (如阿里云 Paraformer)
│   │   ├── llm_api.py       # 封装流式LLM，处理结构化输出(意图+回复)
│   │   └── tts_api.py       # 封装流式克隆TTS (如 FishAudio / CosyVoice)
│   ├── pipeline.py      # 流式编排与打断控制逻辑
│   └── server.py        # FastAPI服务，利用lifespan初始化，提供WebSocket接口
└── /web   # React + TypeScript :极简灵动UI样式\WebSocket客户端，声波动效控制，VAD录音控制
    ├── /
    ├── /
    ├── /
```

3. 需要你注意的地方
    - 鼓励简单有效的设计，切忌过度设计，避免过度假设，尽可能用最简洁、最少的代码解决问题
    - 鼓励你根据需求、目标提出更好的、更合适的解决方案和技术路线，可以不局限于当前的技术路线