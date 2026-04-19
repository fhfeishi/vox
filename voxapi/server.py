# voxapi/server.py
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

# 规范的绝对路径导入
from voxapi.pipeline import SessionPipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.success("🚀 VOX Backend Phase 4: 实时流式 TTS 管线已启动！")
    logger.info("👉 监听地址: ws://0.0.0.0:8000/ws/chat")
    
    # 💡 注意：由于升级了 QwenTtsRealtime 极速引擎，这里不再需要 preload_refs 预热
    
    yield
    logger.warning("🛑 VOX Backend 正在关闭...")

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.success("✅ 前端已成功连接！")
    
    # 将 WebSocket 句柄交给中枢管线
    pipeline = SessionPipeline(websocket)
    await pipeline.start()
    
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.receive":
                data = message.get("bytes") or message.get("text")
                
                # 二进制帧 -> 喂给 ASR 听
                if isinstance(data, bytes) and len(data) > 0:
                    await pipeline.process_audio(data)
                
                # 文本帧 -> 喂给状态机解析 VAD 意图
                elif isinstance(data, str):
                    await pipeline.process_control(data)
                    
            elif message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        logger.info("🔌 客户端主动断开")
    except Exception as e:
        logger.error(f"⚠️ WebSocket 异常: {e}")
    finally:
        # 客户端断开时，必须确保管线资源安全释放
        await pipeline.stop()

if __name__ == "__main__":
    # 注意：使用 voxapi.server:app 要求在项目根目录(VOX/)下运行命令
    uvicorn.run("voxapi.server:app", host="0.0.0.0", port=8000, reload=True)