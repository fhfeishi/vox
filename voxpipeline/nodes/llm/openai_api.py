# voxpipeline/nodes/llm/openai_api.py
import asyncio
from openai import AsyncOpenAI
from loguru import logger

from voxpipeline.core.base_node import BaseNode
from voxpipeline.core.datatypes import TextChunk


class OpenAINode(BaseNode):
    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str = None):
        super().__init__(name="OpenAI_LLM")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.history = [{"role": "system", "content": "你是一个反应敏捷的语音助手。请保持回答简洁、口语化。"}]

    async def process(self, input_stream: asyncio.Queue, output_stream: asyncio.Queue):
        await self.emit_state("ready", "LLM 已连接")

        while True:
            try:
                # 1. 接收来自 ASR 的识别文本
                user_text_chunk: TextChunk = await input_stream.get()

                if user_text_chunk.is_last:
                    await output_stream.put(user_text_chunk)
                    break

                if not user_text_chunk.text.strip():
                    continue

                await self.emit_state("thinking", "正在思考...")
                self.history.append({"role": "user", "content": user_text_chunk.text})

                # 2. 调用 OpenAI 流式接口
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=self.history,
                    stream=True
                )

                full_reply = ""
                async for chunk in response:
                    # 【核心修改】每次生成前，看一眼有没有被打断
                    if self._cancel_event.is_set():
                        logger.warning(f"✂️ [{self.name}] LLM 生成被打断！放弃后续推理。")
                        break  # 直接跳出循环，停止生成

                    content = chunk.choices[0].delta.content
                    if content:
                        full_reply += content
                        await output_stream.put(TextChunk(text=content, is_last=False))

                # 记录对话历史
                self.history.append({"role": "assistant", "content": full_reply})

                # 3. 发送本段对话结束信号给 TTS，触发 TTS 结算最后一段缓存
                await output_stream.put(TextChunk(text="", is_last=False))
                await self.emit_state("responded", "回答完毕")

            except Exception as e:
                logger.error(f"LLM 节点异常: {e}")
                break