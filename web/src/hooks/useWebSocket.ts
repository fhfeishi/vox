// web/src/hooks/useWebSocket.ts
import { useState, useEffect, useRef, useCallback } from 'react';

export function useWebSocket(url: string, onAudioData?: (data: ArrayBuffer) => void) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  
  // 使用 ref 存储回调函数，避免触发 useEffect 重新执行
  const onAudioDataRef = useRef(onAudioData);
  useEffect(() => {
    onAudioDataRef.current = onAudioData;
  }, [onAudioData]);

  useEffect(() => {
    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);
    
    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        setLastMessage(JSON.parse(event.data));
      } else if (event.data instanceof ArrayBuffer) {
        // 🚀 使用 ref 调用，不再引发死循环
        if (onAudioDataRef.current) {
          onAudioDataRef.current(event.data);
        }
      }
    };
    
    wsRef.current = ws;
    return () => ws.close();
  }, [url]); // 👈 依赖数组里去掉了 onAudioData

  const sendMessage = useCallback((data: string | ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { isConnected, lastMessage, sendMessage };
}