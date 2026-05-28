import json
import logging
import time
from typing import List
import requests

logger = logging.getLogger(__name__)

AVAILABLE_MODELS = [
    'qwen3.7-max',
    'qwen3.7-max-2026-05-20',
    'qwen3.7-max-preview',
    'qwen3.6-max-preview',
    'qwen3.6-plus-2026-04-02',
    'qwen3.6-plus',
    'qwen3.5-plus-2026-04-20',
    'glm-5.1'
]

class LLMTranslator:
    def __init__(self, api_key: str, model: str = "qwen3.7-max", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        self.api_key = api_key
        self.base_url = base_url
        if self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]
            
        # 动态组装实例的可用模型列表。如果传入了自定义模型，则将其置于首位作为首选模型，后续使用内置备用模型。
        if model in AVAILABLE_MODELS:
            self.models = AVAILABLE_MODELS[:]
            self.model_idx = AVAILABLE_MODELS.index(model)
        else:
            self.models = [model] + AVAILABLE_MODELS
            self.model_idx = 0
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def get_current_model(self):
        return self.models[self.model_idx]
        
    def switch_model(self):
        if self.model_idx < len(self.models) - 1:
            self.model_idx += 1
            logger.info(f"Model quota exhausted. Switching to next model: {self.get_current_model()}")
            return True
        logger.error("All fallback models exhausted!")
        return False

    def translate_batch(self, texts: List[str]) -> List[str]:
        if not texts:
            return []
            
        system_prompt = (
            "你是一个专业的中国生物学家。请将以下列表中的拉丁文/英文分类学名词翻译为中文。\n"
            "【规则】：\n"
            "1. 绝对禁止对未知单词凭空捏造（如果不能确定请把未知的词汇保留为'原名'或'拼音'等）\n"
            "2. 对于常见的后缀单词如 unclassified, incertae sedis, bacterium 等，请翻译为：未分类的，地位未定的，细菌\n"
            "3. 对已知的门纲目科属如 Actinomycetota, Pseudomonadales, Thermothrix等请翻译为官方约定的学术名\n"
            "4. 请保留后缀修饰符如 sp., cf., var., subsp., f.，例如 'Escherichia coli O157' -> '大肠杆菌 O157'。\n"
            "5. 如果你确实没有任何学术界的中文定名，请保留原名。不要强行音译不懂的词汇。\n"
            "6. 只需要输出翻译结果即可。\n"
            "严格保持原有的列表编号格式，例如 '1. 翻译结果'，不要夹带任何其他废话"
        )

        numbered_texts = [f"{i+1}. {text}" for i, text in enumerate(texts)]
        user_content = "\\n".join(numbered_texts)

        while True:
            current_model = self.get_current_model()
            payload = {
                "model": current_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请翻译列表：\\n{user_content}"}
                ],
                "temperature": 0.1,
                "max_tokens": 4096
            }
            if "deepseek" in current_model.lower():
                payload["thinking"] = {"type": "disabled"}

            try:
                if current_model.startswith('qwen'):
                    import dashscope
                    from dashscope import Generation
                    dashscope.api_key = self.api_key
                    response = Generation.call(
                        model=current_model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"请翻译列表：\\n{user_content}"}
                        ],
                        result_format="message"
                    )
                    
                    if response.status_code != 200:
                        if response.code in ['DataInspectionFailed', 'QuotaExhausted', 'AllocationQuota.FreeTierOnly'] or 'Quota' in str(response.message) or response.status_code in [403, 429]:
                            if self.switch_model():
                                continue
                            return texts
                        logger.error(f"DashScope API 错误: {response.status_code} - {response.message}")
                        return texts
                    content = response.output.choices[0].message.content
                else:
                    response = requests.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload, timeout=90)
                    if response.status_code != 200:
                        if response.status_code in [403, 429]:
                            if self.switch_model():
                                continue
                            return texts
                        logger.error(f"LLM API 错误: {response.status_code} - {response.text}")
                        return texts
    
                    result = response.json()
                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                    else:
                        logger.error(f"LLM 响应异常: {result}")
                        return texts

                import re
                # 兼容实际换行符 (\n, \r\n) 和字面量双字符 "\\n" 的混合分割
                lines = [line.strip() for line in re.split(r'\r?\n|\\n', content.strip()) if line.strip()]
                
                translated_lines = []
                for line in lines:
                    match = re.match(r'^\d+[\.\、\s]+(.*)', line)
                    if match:
                        translated_lines.append(match.group(1).strip())
                    else:
                        translated_lines.append(line.strip())
                
                if len(translated_lines) != len(texts):
                    logger.warning(f"翻译行数与输入文本数不匹配! 输入 {len(texts)} 条, 模型返回 {len(translated_lines)} 行. 触发原样返回兜底.")
                    return texts
                return translated_lines

            except Exception as e:
                # If error is timeout or quota, we could retry, but let's just log it
                if 'quota' in str(e).lower() or 'timeout' in str(e).lower():
                     if self.switch_model():
                         continue
                logger.error(f"LLM 调用失败: {e}")
                return texts
