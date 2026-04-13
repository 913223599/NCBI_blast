# -*- coding: utf-8 -*-
"""
UI Translation Manager
Manages UI text translation for English and Chinese support.
"""

import json
import logging
from pathlib import Path

from src.utils.config_manager import get_config_manager


class UITranslationManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UITranslationManager, cls).__new__(cls)
            cls._instance.config = get_config_manager()
            cls._instance.translations = {}
            cls._instance.locales_path = Path(__file__).resolve().parents[1] / "resources" / "locales"
            cls._instance.load_all_translations()
        return cls._instance

    def load_all_translations(self):
        """Load all translation files from locales directory recursively"""
        if not self.locales_path.exists():
            logging.error(f"Locales path not found: {self.locales_path}")
            return

        # 1. 扫描顶级 JSON 文件 (保持向后兼容)
        for file in self.locales_path.glob("*.json"):
            lang_code = file.stem
            self._load_file(file, lang_code)

        # 2. 扫描语言子目录 (模块化支持)
        for sub_dir in self.locales_path.iterdir():
            if sub_dir.is_dir():
                lang_code = sub_dir.name
                # 递归扫描子目录下的所有 json
                for file in sub_dir.rglob("*.json"):
                    self._load_file(file, lang_code)

    def _load_file(self, file: Path, lang_code: str):
        """内部方法：加载单个翻译文件并合并到指定语言包"""
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if lang_code not in self.translations:
                    self.translations[lang_code] = {}
                # 平铺合并，允许不同模块文件共存
                self.translations[lang_code].update(data)
                logging.info(f"Loaded translation pack fragment: {lang_code}/{file.name}")
        except Exception as e:
            logging.error(f"Failed to load translation file {file}: {e}")

    def get_language(self):
        """Get current language code, default zh_CN"""
        return self.config.get_config_value("language", "zh_CN")

    def set_language(self, lang_code):
        """Set language code ('zh_CN' or 'en_US')"""
        # Ensure we have translations for this language, default back to zh_CN if missing
        if lang_code not in self.translations:
            lang_code = "zh_CN"
        self.config.set_config_value("language", lang_code)
        logging.info(f"UI Language set to: {lang_code}")

    def get_all_translations_for_current_lang(self):
        """Get flattened dictionary for current language"""
        lang = self.get_language()
        # Merge with zh_CN as fallback for missing keys
        fallback = self.translations.get("zh_CN", {})
        current = self.translations.get(lang, {})
        
        # Merge: current overrides fallback
        result = fallback.copy()
        result.update(current)
        return result

    def tr(self, key):
        """Translate key to current language (for Python UI)"""
        lang = self.get_language()
        
        # Primary lookup
        lang_dict = self.translations.get(lang, {})
        if key in lang_dict:
            return lang_dict[key]
            
        # Fallback to zh_CN
        fallback_dict = self.translations.get("zh_CN", {})
        if key in fallback_dict:
            return fallback_dict[key]
            
        return key

def get_ui_translator():
    return UITranslationManager()
