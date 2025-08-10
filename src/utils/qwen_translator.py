"""
通义百炼翻译器模块
提供基于通义千问大模型的英译中翻译功能
"""

import os
from openai import OpenAI
from typing import Optional, List, Dict, Any, Union, Iterable
from openai.types.chat import ChatCompletionMessageParam


class QwenTranslator:
    """
    通义千问翻译器
    使用通义千问大模型进行专业的生物学文本翻译
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化翻译器
        
        Args:
            api_key (str, optional): 通义百炼API密钥
                                     如果未提供，则从环境变量DASHSCOPE_API_KEY获取
        """
        # 如果没有直接提供api_key，则尝试从环境变量获取
        self.api_key = api_key or os.environ.get('DASHSCOPE_API_KEY')
        
        # 如果仍然没有api_key，则尝试从配置文件获取
        if not self.api_key:
            try:
                from .config_manager import get_config_manager
                config_manager = get_config_manager()
                self.api_key = config_manager.get_api_key('dashscope')
            except Exception:
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
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    
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
            
        # 构造翻译提示词，专门针对生物学领域
        prompt = f"""
        你是一位专业的生物学家和翻译专家，请将以下生物学相关的英文文本翻译成中文：
        
        要求：
        1. 保持专业术语的准确性
        2. 保持原文的语义和结构
        3. 对于生物学专业词汇，请使用标准的中文学术术语
        4. 如果遇到物种学名（如 Homo sapiens），请保留原文格式
        
        文本：
        {text}
        
        翻译结果：
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
        
        # 调用通义千问模型进行翻译
        try:
            # 调用通义千问模型进行翻译
            completion = self.client.chat.completions.create(
                model="qwen-mt-turbo",  # 使用专门的翻译模型
                messages=messages,
                extra_body={
                    "translation_options": translation_options
                }
            )
            
            return completion.choices[0].message.content.strip()
                
        except Exception as e:
            raise Exception(f"调用通义千问API时出错: {str(e)}")
    
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
    
    def batch_translate(self, texts: list) -> list:
        """
        批量翻译文本列表
        
        Args:
            texts (list): 要翻译的文本列表
            
        Returns:
            list: 翻译后的文本列表
        """
        results = []
        for text in texts:
            try:
                # 确保输入是字符串类型
                if not isinstance(text, str):
                    text = str(text)
                    
                translated = self.translate_text(text)
                results.append(translated)
            except Exception as e:
                # 如果翻译失败，保留原文
                print(f"翻译 '{text}' 时出错: {e}")
                results.append(text)
        return results


def get_qwen_translator(api_key: Optional[str] = None) -> QwenTranslator:
    """
    获取通义千问翻译器实例
    
    Args:
        api_key (str, optional): 通义百炼API密钥
        
    Returns:
        QwenTranslator: 翻译器实例
    """
    return QwenTranslator(api_key)


# 示例和测试
if __name__ == "__main__":
    # 测试代码
    try:
        # 注意：需要先设置DASHSCOPE_API_KEY环境变量
        translator = get_qwen_translator()
        
        # 测试翻译
        test_cases = [
            "Bacillus licheniformis strain WS02 16S ribosomal RNA gene, partial sequence",
            "Staphylococcus epidermidis partial 16S rRNA gene, isolate OCOB16",
            "Escherichia coli gene sequence",
            "Saccharomyces cerevisiae strain ABC123 plasmid vector"
        ]
        
        print("通义千问生物学翻译测试:")
        print("=" * 50)
        
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