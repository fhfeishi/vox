```js
// error
const connect = useCallback(() => {
    try {
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        console.log("🟢 [WebSocket] 连接成功！");
        setIsConnected(true);
        retryCount.current = 0; 
      };

      ws.onclose = () => {
        console.warn("🔴 [WebSocket] 连接断开！准备重连...");
        setIsConnected(false);
        // 指数退避重连机制
        const timeout = Math.min(10000, 1000 * Math.pow(2, retryCount.current));
        retryCount.current += 1;
        // 用 const 定义的箭头函数在初始化完成前，无法在内部安全地被按名递归引用。
        reconnectTimeoutRef.current = setTimeout(connect, timeout);
      };
      
      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          setLastMessage(JSON.parse(event.data));
        } else if (event.data instanceof ArrayBuffer) {
          if (onAudioDataRef.current) {
            onAudioDataRef.current(event.data);
          }
        }
      };
      
      wsRef.current = ws;
    } catch (err) {
      console.error("❌ [WebSocket] 创建连接失败:", err);
    }
  }, [url]);








// ok
// 1. 将匿名箭头函数改为具名函数 function connectImpl()
  const connect = useCallback(function connectImpl() {
    try {
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        console.log("🟢 [WebSocket] 连接成功！");
        setIsConnected(true);
        retryCount.current = 0; 
      };

      ws.onclose = () => {
        console.warn("🔴 [WebSocket] 连接断开！准备重连...");
        setIsConnected(false);
        const timeout = Math.min(10000, 1000 * Math.pow(2, retryCount.current));
        retryCount.current += 1;
        
        // 2. 在 setTimeout 中调用内部具名函数 connectImpl
        reconnectTimeoutRef.current = setTimeout(connectImpl, timeout);
      };
      
      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          setLastMessage(JSON.parse(event.data) as WSMessage);
        } else if (event.data instanceof ArrayBuffer) {
          if (onAudioDataRef.current) {
            onAudioDataRef.current(event.data);
          }
        }
      };
      
      wsRef.current = ws;
    } catch (err) {
      console.error("❌ [WebSocket] 创建连接失败:", err);
    }
  }, [url]);
```