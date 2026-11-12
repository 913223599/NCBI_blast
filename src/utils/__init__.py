# -*- coding: utf-8 -*-
"""
工具模块初始化文件（按需延迟导出，确保空虚拟环境自举阶段可安全导入零依赖子模块）
"""

import importlib

__all__ = [
    'get_biology_translator',
    'get_qwen_translator',
    'get_translation_data_manager',
    'get_config_manager',
    'get_blast_result_translator',
    'FileHandler',
]

_TRANSLATION_ATTRS = {
    'get_biology_translator',
    'get_qwen_translator',
    'get_translation_data_manager',
    'get_blast_result_translator',
}


def __getattr__(name: str):
    if name == 'get_config_manager':
        mod = importlib.import_module('.config_manager', __name__)
        val = getattr(mod, 'get_config_manager')
        globals()[name] = val
        return val
    if name in _TRANSLATION_ATTRS:
        mod = importlib.import_module('.translation', __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    if name == 'FileHandler':
        mod = importlib.import_module('.file_handler', __name__)
        val = getattr(mod, 'FileHandler')
        globals()[name] = val
        return val
    # Submodule attributes (e.g. from . import file_handler)
    if name in {
        'config_manager', 'file_handler', 'translation', 'universal_parser',
        'bio_tools_healer', 'verify_and_install_deps', 'environment_checker',
        'headless_browser_manager',
    }:
        return importlib.import_module(f'.{name}', __name__)
    mod = importlib.import_module('.file_handler', __name__)
    if hasattr(mod, name):
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals().keys()) | set(__all__))
