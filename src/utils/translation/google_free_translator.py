import urllib.request
import urllib.parse
import json
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

class GoogleFreeTranslator:
    """
    使用免费无Key的 Google Translate API 进行翻译
    (通过 translate.googleapis.com 的 web 端点)
    """
    def __init__(self):
        self.base_url = "https://translate.googleapis.com/translate_a/single"
        # 伪装请求头
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def translate_text(self, text: str, source_lang: str = 'en', target_lang: str = 'zh-CN') -> str:
        if not text or not text.strip():
            return text
            
        params = {
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": text
        }
        query_string = urllib.parse.urlencode(params)
        url = f"{self.base_url}?{query_string}"
        
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                # result[0] 包含一个列表，其中每个元素的第一项是翻译的片段
                if result and isinstance(result, list) and len(result) > 0 and result[0]:
                    translated_text = "".join([sentence[0] for sentence in result[0] if sentence[0]])
                    return translated_text
        except Exception as e:
            logger.error(f"GoogleFreeTranslator 翻译失败: {e}")
            
        return text

    def translate_batch(self, texts: List[str], source_lang: str = 'en', target_lang: str = 'zh-CN') -> List[str]:
        if not texts:
            return []
            
        # 将列表拼成带换行符的单一长字符串，使用 ' \n ' 避免被翻译引擎误合并
        combined_text = " \n ".join(texts)
        translated_text = self.translate_text(combined_text, source_lang, target_lang)
        
        if not translated_text:
            return []
            
        # 按换行符拆分，清理两端的空白字符
        translated_lines = [line.strip() for line in translated_text.split('\n')]
        
        # 长度防抖：如果翻译引擎吞了换行符，导致输出行数和输入行数不一致，则退化回单条安全翻译
        if len(translated_lines) != len(texts):
            logger.warning(f"批量翻译行数不匹配(输入{len(texts)}, 输出{len(translated_lines)})，退化为逐条翻译")
            results = []
            for text in texts:
                results.append(self.translate_text(text, source_lang, target_lang))
            return results
            
        return translated_lines

# 测试
if __name__ == "__main__":
    translator = GoogleFreeTranslator()
    print(translator.translate_text("Streptococcus iniae"))
    print(translator.translate_text("Bacillus subtilis"))
