"""
通义百炼翻译器模块
提供基于通义千问大模型的英译中翻译功能
"""

import os
from typing import Optional, List

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam


class QwenTranslator:
    """
    通义千问翻译器
    使用通义千问大模型进行专业的生物学文本翻译
    """
    
    _has_arrearage = False # 类级别变量，追踪欠费状态
    _on_arrearage_callback = None # 欠费时的回调函数
    
    def __init__(self, api_key: Optional[str] = None, model: str = 'deepseek-r1'):
        """
        初始化翻译器
        
        Args:
            api_key (str, optional): 通义百炼API密钥
                                     如果未提供，则从环境变量DASHSCOPE_API_KEY获取
            model (str): 使用的模型名称，默认为'deepseek-r1'
        """
        # 如果没有直接提供api_key，则尝试从环境变量获取
        self.api_key = api_key or os.environ.get('DASHSCOPE_API_KEY')
        
        # 模型名称不再进行硬性白名单验证，以允许测试新增模型
        self.model = model
        
        # 如果仍然没有api_key，则尝试从配置文件获取
        if not self.api_key:
            try:
                from ...utils.config_manager import get_config_manager
                config_manager = get_config_manager()
                self.api_key = config_manager.get_api_key('dashscope')
            except (ImportError, AttributeError):
                # 如果配置管理器不可用，则api_key保持为空
                pass
        
        # 如果仍然没有API密钥，则抛出异常
        if not self.api_key:
            raise ValueError("未提供API密钥。请通过以下方式之一设置API密钥：\n"
                           "1. 在初始化时传入api_key参数\n"
                           "2. 设置DASHSCOPE_API_KEY环境变量\n"
                           "3. 在配置文件中设置dashscope API密钥")
        
        # 初始化OpenAI客户端，使用DashScope的兼容模式
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            max_retries=5  # 🚀 增加重试次数
        )
    
    def get_supported_models(self, return_keys_only=False) -> dict | list:
        """获取支持的AI模型列表"""
        # 从配置文件获取支持的模型
        try:
            from ...utils.config_manager import get_config_manager
            config_manager = get_config_manager()
            if return_keys_only:
                return config_manager.get_supported_model_keys()
            else:
                return config_manager.get_supported_models()
        except Exception as e:
            # 如果配置管理器不可用，返回默认值
            default_models = {
                'qwen-plus': '通义千问-Plus',
                'qwen-mt-plus': '通义千问-MT-Plus',
                'qwen-mt-turbo': '通义千问-MT-Turbo',
                'qwen-turbo': '通义千问-Turbo',
                'deepseek-r1': 'DeepSeek'
            }
            if return_keys_only:
                return list(default_models.keys())
            else:
                return default_models
    
    def validate_model(self) -> tuple[bool, str]:
        """
        验证模型是否可用 (轻量级测试)
        Returns: (success, message)
        """
        try:
            messages: List[ChatCompletionMessageParam] = [{"role": "user", "content": "hello"}]
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=20 # 允许返回翻译结果
            )
            response_content = (completion.choices[0].message.content or "").strip()
            return True, f"验证成功！模型响应: '{response_content}'"
        except Exception as e:
            err_msg = str(e)
            if 'Arrearage' in err_msg or 'overdue-payment' in err_msg:
                return False, "账户欠费或访问受限"
            if 'Model' in err_msg or 'model_not_found' in err_msg or '400' in err_msg:
                return False, f"无效的模型标识符: {self.model}"
            return False, f"连接测试失败: {err_msg}"

    def translate_text(self, text: str, source_lang: str = 'en', target_lang: str = 'zh') -> str:
        """
        翻译文本
        
        Args:
            text (str): 要翻译的文本
            source_lang (str): 源语言，默认为'en'
            target_lang (str): 目标语言，默认为'zh'
            
        Returns:
            str: 翻译后的文本
            
        Raises:
            Exception: 翻译失败时抛出异常
        """
        # 确保输入是字符串类型
        if not isinstance(text, str):
            text = str(text)
            
        if not text:
            return text
            
        # 构造翻译提示词，专门针对生物学领域，特别是菌种名称翻译
        prompt = f"""
你是一位专业的生物学家和翻译专家，请将以下生物学相关的英文文本翻译成中文：

翻译要求：
1. 保持原文的语义和结构，保持专业术语的准确性
2. 请使用标准的中文学术术语
3. 只进行文本翻译，除了翻译内容外不要输出任何无关内容
4. 对于微生物学名，严格按照以下规则处理：
   - 完整的学名（如 "Streptococcus iniae"）必须翻译为标准中文名（如"海豚链球菌"）
   - 属名+sp.或spp.（如 "Streptococcus sp."）翻译为"链球菌属"
   - 不要将学名直接音译，而要使用标准的中文学名
5. 如果你不确定某个学名的标准中文翻译，请使用最接近的翻译并保持学名格式
6. 再次强调，除了输出翻译内容本身外不要输出其他内容
文本：
{text}

""".strip()
        
        # 设置翻译选项
        translation_options = {
            "source_lang": source_lang,
            "target_lang": target_lang
        }
        
        # 定义消息参数，使用正确的ChatCompletionMessageParam类型
        messages: List[ChatCompletionMessageParam] = [
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        if QwenTranslator._has_arrearage:
            import logging
            logging.getLogger(__name__).warning(f"[DEBUG] _has_arrearage is TRUE! Skipping network.")
            return text

        import logging
        logging.getLogger(__name__).info(f"[DEBUG] Invoking OpenAI completion for: {text}")

        # 调用通义千问模型进行翻译
        try:
            # 调用通义千问模型进行翻译
            completion = self.client.chat.completions.create(
                model=self.model,  # 使用配置的模型
                messages=messages,
                timeout=60.0 # 🚀 提高超时到 60 秒，Qwen-Max 推理较慢
            )
            
            # 输出API返回的完整内容用于调试
            # print("=" * 50)
            # print("通义千问API返回内容:")
            # print(f"Model: {completion.model}")
            # print(f"Choices count: {len(completion.choices)}")
            # print(f"Response content: {completion.choices[0].message.content}")
            # print("=" * 50)
            
            import re
            content = (completion.choices[0].message.content or "").strip()
            # 过滤掉 DeepSeek-R1 这种模型产生的 <think> 思考过程标签
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            return content
                
        except Exception as e:
            err_msg = str(e)
            import logging
            logger = logging.getLogger(__name__)
            
            # 精确匹配欠费相关错误
            if 'Arrearage' in err_msg or 'overdue-payment' in err_msg or 'FreeTierOnly' in err_msg or 'free tier' in err_msg.lower():
                if not QwenTranslator._has_arrearage:
                    QwenTranslator._has_arrearage = True
                    logger.error(f"[严重错误] AI 翻译账户欠费或免费额度已耗尽，已进入静默模式。")
                    if QwenTranslator._on_arrearage_callback:
                        QwenTranslator._on_arrearage_callback()
                return text
            
            # 模型错误处理
            if 'Model' in err_msg or 'model_not_found' in err_msg or '400' in err_msg:
                logger.warning(f"[警告] AI 模型调用失败 ({self.model}): {err_msg}")
                return text

            logger.error(f"调用API时出错: {err_msg}")
            raise Exception(f"调用API时出错: {err_msg}")
    
    def translate_biology_term(self, term: str) -> str:
        """
        翻译生物学专业术语
        
        Args:
            term (str): 生物学专业术语
            
        Returns:
            str: 翻译后的术语
        """
        # 确保输入是字符串类型
        if not isinstance(term, str):
            term = str(term)
            
        return self.translate_text(term)
    
    def translate_batch_llm(self, texts: List[str], source_lang: str = 'en', target_lang: str = 'zh') -> List[str]:
        """
        [ULTRA-FAST] 真正的批量翻译：通过一个 Prompt 翻译多个词条
        """
        if not texts: return []
        if len(texts) == 1: return [self.translate_text(texts[0])]

        # 构造批量翻译提示词
        texts_input = "\n".join([f"{i+1}. {txt}" for i, txt in enumerate(texts)])
        prompt = f"""
你是一位专业的生物学翻译专家。请将以下编号列表中的生物学英文名称翻译成中文。

要求：
1. 保持专业术语准确。
2. 严格按输入顺序返回结果，每行一个。
3. 不要输出编号，不要输出原文，不要输出任何解释内容。
4. 微生物学名遵循：属名+种名 -> 标准中文名；属名+sp. -> XX菌属。

待翻译列表：
{texts_input}
""".strip()

        messages: List[ChatCompletionMessageParam] = [{"role": "user", "content": prompt}]
        
        if QwenTranslator._has_arrearage:
            import logging
            logging.getLogger(__name__).warning(f"[DEBUG] _has_arrearage is TRUE! Skipping batch network request.")
            return texts

        try:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[BatchAI] Sending {len(texts)} terms for translation...")
            
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=120.0  # 🚀 批量请求给 120 秒，确保长列表稳定返回
            )
            
            import re
            content = (completion.choices[0].message.content or "").strip()
            # 过滤思考过程
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            
            # 分割行，并清理可能的干扰
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            
            # 始终执行正则清洗以去除大模型自作主张加的编号前缀（如 "1. "）
            cleaned_lines = []
            import re
            for line in lines:
                cleaned = re.sub(r'^\d+[\.\s、]+', '', line).strip()
                if cleaned:
                    cleaned_lines.append(cleaned)
            lines = cleaned_lines

            # 最终补偿：如果行数依然不对，至少保证长度一致
            if len(lines) > len(texts):
                lines = lines[:len(texts)]
            while len(lines) < len(texts):
                lines.append(texts[len(lines)]) # 补齐原文
                
            return lines
                
        except Exception as e:
            err_msg = str(e)
            import logging
            logger = logging.getLogger(__name__)
            
            if 'Arrearage' in err_msg or 'overdue-payment' in err_msg or 'FreeTierOnly' in err_msg or 'free tier' in err_msg.lower():
                if not QwenTranslator._has_arrearage:
                    QwenTranslator._has_arrearage = True
                    logger.error(f"[严重错误] 批量AI翻译账户欠费或免费额度已耗尽，已进入静默模式。")
                    if QwenTranslator._on_arrearage_callback:
                        QwenTranslator._on_arrearage_callback()

            logger.error(f"Batch AI Error: {err_msg}")
            return texts # 出错退化为原文

    def batch_translate(self, texts: list) -> list:
        """批量翻译文本列表 (兼容旧接口并自动启用 LLM 批处理)"""
        return self.translate_batch_llm(texts)


def get_qwen_translator(api_key: Optional[str] = None, model: str = 'deepseek-r1') -> QwenTranslator:
    """
    获取通义千问翻译器实例
    
    Args:
        api_key (str, optional): 通义百炼API密钥
        model (str): 使用的模型名称，默认为'deepseek-r1'
        
    Returns:
        QwenTranslator: 翻译器实例
    """
    return QwenTranslator(api_key, model)


# 示例和测试
if __name__ == "__main__":
    # 测试代码
    try:
        # 注意：需要先设置DASHSCOPE_API_KEY环境变量
        # 可以通过model参数指定使用的模型
        translator = get_qwen_translator(model='deepseek-r1')  # 默认使用DeepSeek
        # translator = get_qwen_translator(model='qwen-plus')    # 使用通义千问-Plus
        # translator = get_qwen_translator(model='qwen-mt-plus') # 使用通义千问-MT-Plus
        # translator = get_qwen_translator(model='qwen-mt-turbo')# 使用通义千问-MT-Turbo
        # translator = get_qwen_translator(model='qwen-turbo')   # 使用通义千问-Turbo
        
        # 测试翻译
        test_cases = [
            "Bacillus licheniformis strain WS02 16S ribosomal RNA gene, partial sequence",
            "Staphylococcus epidermidis partial 16S rRNA gene, isolate OCOB16",
            "Escherichia coli gene sequence",
            "Saccharomyces cerevisiae strain ABC123 plasmid vector"
        ]
        
        print("通义千问生物学翻译测试:")
        print("=" * 50)
        # 获取模型名称（如果有的话）
        supported_models = translator.get_supported_models()
        model_name = supported_models.get(translator.model, translator.model) if isinstance(supported_models, dict) else translator.model
        print(f"使用模型: {translator.model} ({model_name})")
        print("-" * 50)
        
        for test_case in test_cases:
            try:
                translated = translator.translate_text(test_case)
                print(f"原文: {test_case}")
                print(f"译文: {translated}")
                print("-" * 50)
            except Exception as e:
                print(f"翻译 '{test_case}' 时出错: {e}")
                
    except Exception as e:
        print(f"初始化翻译器失败: {e}")
        print("\n请按照以下步骤配置:")
        print("1. 访问阿里云官网申请通义百炼API密钥")
        print("   参考: https://help.aliyun.com/zh/bailian/")
        print("2. 创建API密钥")
        print("3. 设置环境变量:")
        print("   Windows命令行: set DASHSCOPE_API_KEY=your_api_key_here")
        print("   Windows PowerShell: $env:DASHSCOPE_API_KEY=\"your_api_key_here\"")
        print("   Linux/Mac: export DASHSCOPE_API_KEY=your_api_key_here")
        print("\n或者直接在代码中传递API密钥:")
        print("  translator = get_qwen_translator('YOUR_API_KEY_HERE')")