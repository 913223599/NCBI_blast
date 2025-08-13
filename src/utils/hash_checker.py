"""
哈希校验模块
用于计算和验证序列文件的哈希值，实现结果缓存功能
"""

import hashlib
import os
from pathlib import Path


class HashChecker:
    """
    哈希校验器
    用于计算文件哈希值并检查缓存结果
    """
    
    def __init__(self, cache_dir="results"):
        """
        初始化哈希校验器
        
        Args:
            cache_dir (str): 缓存目录路径
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def calculate_file_hash(self, file_path):
        """
        计算文件的MD5哈希值
        
        Args:
            file_path (str): 文件路径
            
        Returns:
            str: 文件的MD5哈希值
        """
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            raise RuntimeError(f"计算文件哈希值失败 {file_path}: {e}")
    
    def get_cache_files(self, file_hash):
        """
        根据文件哈希值获取缓存文件路径
        
        Args:
            file_hash (str): 文件哈希值
            
        Returns:
            dict: 包含各种缓存文件路径的字典
        """
        cache_files = {
            'xml': self.cache_dir / f"{file_hash}_blast_result.xml",
            'csv': self.cache_dir / f"{file_hash}_blast_result.csv",
            'desc': self.cache_dir / f"{file_hash}_blast_result.desc"
        }
        return cache_files
    
    def cache_exists(self, file_hash):
        """
        检查缓存是否存在
        
        Args:
            file_hash (str): 文件哈希值
            
        Returns:
            bool: 缓存是否存在
        """
        cache_files = self.get_cache_files(file_hash)
        # 检查主要的XML结果文件是否存在
        return cache_files['xml'].exists()
    
    def save_hash_file(self, file_path, file_hash):
        """
        保存文件哈希值到结果目录
        
        Args:
            file_path (str): 原始文件路径
            file_hash (str): 文件哈希值
        """
        try:
            hash_file = self.cache_dir / f"{Path(file_path).stem}.hash"
            with open(hash_file, 'w') as f:
                f.write(file_hash)
        except Exception as e:
            print(f"警告: 保存哈希文件失败: {e}")
    
    def load_hash_file(self, file_path):
        """
        从结果目录加载文件哈希值
        
        Args:
            file_path (str): 原始文件路径
            
        Returns:
            str: 文件哈希值，如果不存在则返回None
        """
        try:
            hash_file = self.cache_dir / f"{Path(file_path).stem}.hash"
            if hash_file.exists():
                with open(hash_file, 'r') as f:
                    return f.read().strip()
            return None
        except Exception as e:
            print(f"警告: 加载哈希文件失败: {e}")
            return None
    
    def verify_hash(self, file_path):
        """
        验证文件哈希值
        
        Args:
            file_path (str): 文件路径
            
        Returns:
            tuple: (是否匹配, 当前哈希值)
        """
        stored_hash = self.load_hash_file(file_path)
        if stored_hash is None:
            return False, None
            
        current_hash = self.calculate_file_hash(file_path)
        return stored_hash == current_hash, current_hash
    
    def copy_cache_results(self, file_hash, target_file_stem):
        """
        复制缓存结果到目标文件名
        
        Args:
            file_hash (str): 源文件哈希值
            target_file_stem (str): 目标文件名（不含扩展名）
            
        Returns:
            bool: 是否成功复制
        """
        try:
            source_files = self.get_cache_files(file_hash)
            target_files = {
                'xml': self.cache_dir / f"{target_file_stem}_blast_result.xml",
                'csv': self.cache_dir / f"{target_file_stem}_blast_result.csv",
                'desc': self.cache_dir / f"{target_file_stem}_blast_result.desc"
            }
            
            # 检查源文件是否存在
            for file_path in source_files.values():
                if not file_path.exists():
                    print(f"缓存文件不存在: {file_path}")
                    return False
            
            # 复制文件
            for key in source_files:
                if source_files[key].exists():
                    with open(source_files[key], 'rb') as src, open(target_files[key], 'wb') as dst:
                        dst.write(src.read())
            
            return True
        except Exception as e:
            print(f"复制缓存结果失败: {e}")
            return False


def get_hash_checker(cache_dir="results") -> HashChecker:
    """
    获取哈希校验器实例
    
    Args:
        cache_dir (str): 缓存目录路径
        
    Returns:
        HashChecker: 哈希校验器实例
    """
    return HashChecker(cache_dir)