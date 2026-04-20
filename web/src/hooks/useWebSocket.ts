// web/src/hooks/useWebSocket.ts
import { useState, useEffect, useRef, useCallback } from 'react';

export function useWebSocket(url: string, onAudioData?: (data: ArrayBuffer) => void) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const retryCount = useRef(0);
  
  const onAudioDataRef = useRef(onAudioData);
  useEffect(() => {
    onAudioDataRef.current = onAudioData;
  }, [onAudioData]);

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