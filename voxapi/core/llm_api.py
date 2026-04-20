# voxapi/core/llm_api.py
import re
import json
import asyncio
import dashscope
from dashscope import Generation
from loguru import logger
from configs.config import settings

dashscope.api_key = settings.dashscope_api_key

class QwenEngine:
    def __init__(self):
        self.system_prompt = (
            "你是一个名为 百变 的实时语音助手。交互规则：\n"
            "1. 你的回复将被直接转为语音朗读，所以**必须极其口语化、简短**。\n"
            "2. **绝对禁止**使用 Markdown 格式（如 *、#、-、代码块等），数字尽量用汉字表达（如“三个”）。\n"
            "3. 如果用户的提问明确要求“换个声音”、“用某某的声音”、“模仿我说话”，你必须在回复的最开头输出控制帧 `[VOICE_CTRL: {\"target\": \"音色名\"}]`，然后再输出回复正文。\n"
            "   - 如果是克隆用户自己的声音，target 为 \"speaker\"。\n"
            "   - 如果是预留的特定人物（如晓燕），target 为对应拼音或名字。\n"
            "   - 如果没有明确要求，不要输出控制帧。"
        )
        
        self.punctuation_pattern = re.compile(r'([。？！，；!?.,;])')

    async def generate_stream(self, text: str, history: list = None):
        messages = [{'role': 'system', 'content': self.system_prompt}]
        if history:
            messages.extend(history)
        messages.append({'role': 'user', 'content': text})

        try:
            def _make_sync_call():
                return Generation.call(
                    model='qwen-turbo',
                    messages=messages,
                    result_format='message',
                    stream=True,
                    incremental_output=True
                )

            responses = await asyncio.to_thread(_make_sync_call)

            buffer = ""
            is_first_chunk = True

            while True:
                # 🚀 修复核心：传入 None 作为默认值，防止抛出 StopIteration
                response = await asyncio.to_thread(next, responses, None)
                
                # 如果返回 None，说明生成器已经遍历结束，安全退出循环
                if response is None:
                    break

                if response.status_code != 200:
                    logger.error(f"LLM API 错误: {response.message}")
                    continue

                delta = response.output.choices[0].message.content
                buffer += delta

                # ==========================================
                # 意图拦截：解析首个块的 VOICE_CTRL
                # ==========================================
                if is_first_chunk:
                    if buffer.startswith("[VOICE_CTRL"):
                        if "]" in buffer:
                            try:
                                json_str = buffer[buffer.find("{"):buffer.find("}")+1]
                                ctrl_data = json.loads(json_str)
                                target = ctrl_data.get("target", "default")
                                
                                logger.success(f"🎯 [LLM] 成功拦截音色切换指令: target='{target}'")
                                yield {"type": "voice_ctrl", "target": target}
                            except Exception as e:
                                logger.warning(f"⚠️ 解析 VOICE_CTRL 失败: {e}")
                            
                            buffer = buffer[buffer.find("]")+1:].lstrip()
                            is_first_chunk = False
                        else:
                            continue 
                    elif len(buffer) > 0 and not buffer.startswith("["):
                        is_first_chunk = False

                # ==========================================
                # 标点切片：组装句子
                # ==========================================
                if not is_first_chunk:
                    match = self.punctuation_pattern.search(buffer)
                    while match:
                        split_idx = match.end()
                        sentence = buffer[:split_idx].strip()
                        buffer = buffer[split_idx:]
                        
                        if sentence:
                            yield {"type": "text_chunk", "text": sentence}
                        
                        match = self.punctuation_pattern.search(buffer)

            # 兜底：输出 buffer 里最后残留的文本
            if buffer.strip():
                yield {"type": "text_chunk", "text": buffer.strip()}

        except Exception as e:
            logger.error(f"LLM 生成异常: {e}")


# ==========================================
# 🧪 本地独立测试模块
# ==========================================
if __name__ == "__main__":
    async def test_llm():
        engine = QwenEngine()
        
        test_prompts = [
            "武汉有什么好吃的？简单说两句。",
            "用马保国的声音回答我，你觉得年轻人应该怎么做？"
        ]
        
        for prompt in test_prompts:
            print(f"\n🗣️ User: {prompt}")
            print("-" * 40)
            
            async for chunk in engine.generate_stream(prompt):
                if chunk["type"] == "voice_ctrl":
                    print(f"⚙️ [控制信号拦截] 准备将声音切换为 -> {chunk['target']}")
                elif chunk["type"] == "text_chunk":
                    print(f"📦 [文本切片送往TTS] -> {chunk['text']}")
                    
            print("-" * 40)

    asyncio.run(test_llm())