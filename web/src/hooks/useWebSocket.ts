// web/src/hooks/useWebSocket.ts
import { useState, useEffect, useRef, useCallback } from 'react';

// 定义明确的消息接口替代 any，基于后端实际返回的字段
export interface WSMessage {
  type: string;
  text?: string;
  voice?: string;
  name?: string;
}

export function useWebSocket(url: string, onAudioData?: (data: ArrayBuffer) => void) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // 浏览器环境下 setTimeout 返回的是数字 ID。使用 ReturnType 自动推导，消除对 NodeJS 类型的依赖
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCount = useRef(0);
  
  const onAudioDataRef = useRef(onAudioData);
  useEffect(() => {
    onAudioDataRef.current = onAudioData;
  }, [onAudioData]);

  // 将匿名箭头函数改为具名函数 function connectImpl()
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

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  const sendMessage = useCallback((data: string | ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { isConnected, lastMessage, sendMessage };
}