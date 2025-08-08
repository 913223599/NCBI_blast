"""
BLAST结果缓存模块
实现结果缓存以避免重复查询
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path


class BlastResultCache:
    """
    BLAST结果缓存器
    缓存查询结果以提高效率
    """
    
    def __init__(self, cache_dir="cache", expiry_time=86400):
        """
        初始化结果缓存器
        
        Args:
            cache_dir (str): 缓存目录
            expiry_time (int): 缓存过期时间（秒）
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.expiry_time = expiry_time
    
    def _get_cache_key(self, sequence):
        """
        生成序列的缓存键
        
        Args:
            sequence (str): 序列内容
            
        Returns:
            str: 缓存键
        """
        # 使用序列内容的哈希值作为缓存键
        return hashlib.md5(sequence.encode()).hexdigest()
    
    def _get_cache_file(self, cache_key):
        """
        获取缓存文件路径
        
        Args:
            cache_key (str): 缓存键
            
        Returns:
            Path: 缓存文件路径
        """
        return self.cache_dir / f"{cache_key}.json"
    
    def _is_expired(self, cache_file):
        """
        检查缓存是否过期
        
        Args:
            cache_file (Path): 缓存文件路径
            
        Returns:
            bool: 是否过期
        """
        if not cache_file.exists():
            return True
        
        # 检查文件修改时间
        mod_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
        now = datetime.now()
        return (now - mod_time).total_seconds() > self.expiry_time
    
    def get_cached_result(self, sequence):
        """
        获取缓存的结果
        
        Args:
            sequence (str): 序列内容
            
        Returns:
            dict or None: 缓存的结果，如果不存在或过期则返回None
        """
        cache_key = self._get_cache_key(sequence)
        cache_file = self._get_cache_file(cache_key)
        
        # 检查缓存是否存在且未过期
        if not cache_file.exists() or self._is_expired(cache_file):
            return None
        
        try:
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)
            return cached_data
        except Exception as e:
            print(f"读取缓存失败: {e}")
            return None
    
    def save_result(self, sequence, result):
        """
        保存结果到缓存
        
        Args:
            sequence (str): 序列内容
            result (dict): 查询结果
        """
        cache_key = self._get_cache_key(sequence)
        cache_file = self._get_cache_file(cache_key)
        
        try:
            # 添加时间戳
            cache_data = result.copy()
            cache_data['cached_at'] = datetime.now().isoformat()
            
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            print(f"保存缓存失败: {e}")
    
    def clear_expired_cache(self):
        """
        清理过期缓存
        """
        cleared_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            if self._is_expired(cache_file):
                try:
                    cache_file.unlink()
                    cleared_count += 1
                except Exception as e:
                    print(f"删除过期缓存失败 {cache_file}: {e}")
        
        print(f"清理了 {cleared_count} 个过期缓存文件")
    
    def clear_all_cache(self):
        """
        清理所有缓存
        """
        cleared_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                cleared_count += 1
            except Exception as e:
                print(f"删除缓存失败 {cache_file}: {e}")
        
        print(f"清理了 {cleared_count} 个缓存文件")
    
    def get_cache_stats(self):
        """
        获取缓存统计信息
        
        Returns:
            dict: 统计信息
        """
        total_files = len(list(self.cache_dir.glob("*.json")))
        expired_files = sum(1 for f in self.cache_dir.glob("*.json") if self._is_expired(f))
        
        return {
            'total_cached': total_files,
            'expired': expired_files,
            'valid': total_files - expired_files
        }


class CachedBlastProcessor:
    """
    带缓存的BLAST处理器
    """
    
    def __init__(self, cache_enabled=True, cache_expiry=86400):
        """
        初始化带缓存的BLAST处理器
        
        Args:
            cache_enabled (bool): 是否启用缓存
            cache_expiry (int): 缓存过期时间（秒）
        """
        self.cache_enabled = cache_enabled
        self.cache = BlastResultCache(expiry_time=cache_expiry) if cache_enabled else None
    
    def process_sequence_with_cache(self, sequence_file, blast_executor):
        """
        处理带缓存的序列
        
        Args:
            sequence_file (str): 序列文件路径
            blast_executor: BLAST执行器
            
        Returns:
            dict: 处理结果
        """
        if not self.cache_enabled or not self.cache:
            # 不使用缓存，直接处理
            return self._process_without_cache(sequence_file, blast_executor)
        
        # 读取序列
        try:
            with open(sequence_file, 'r') as f:
                sequence = f.read().strip()
        except Exception as e:
            return {
                "file": sequence_file,
                "status": "error",
                "error": f"读取序列文件失败: {e}"
            }
        
        # 检查缓存
        cached_result = self.cache.get_cached_result(sequence)
        if cached_result:
            print(f"✓ 使用缓存结果: {Path(sequence_file).name}")
            cached_result['from_cache'] = True
            return cached_result
        
        # 缓存未命中，执行实际查询
        print(f"○ 执行实际查询: {Path(sequence_file).name}")
        result = self._process_without_cache(sequence_file, blast_executor)
        
        # 保存到缓存
        if result['status'] == 'success':
            self.cache.save_result(sequence, result)
            result['from_cache'] = False
        
        return result
    
    def _process_without_cache(self, sequence_file, blast_executor):
        """
        不使用缓存处理序列
        
        Args:
            sequence_file (str): 序列文件路径
            blast_executor: BLAST执行器
            
        Returns:
            dict: 处理结果
        """
        try:
            # 读取序列
            with open(sequence_file, 'r') as f:
                sequence = f.read().strip()
            
            # 执行BLAST搜索
            result_handle = blast_executor.execute_blast_search(sequence)
            
            # 保存结果
            file_name = Path(sequence_file).stem
            result_file = Path("results") / f"{file_name}_cached_blast_result.xml"
            
            with open(result_file, "w") as out_handle:
                out_handle.write(result_handle.read())
            
            result_handle.close()
            
            return {
                "file": sequence_file,
                "status": "success",
                "result_file": str(result_file),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "file": sequence_file,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


def main():
    """
    缓存模块使用示例
    """
    print("BLAST结果缓存模块")
    print("=" * 30)
    
    print("功能特点:")
    print("1. 自动缓存查询结果")
    print("2. 基于内容哈希的缓存键")
    print("3. 可配置的过期时间")
    print("4. 缓存清理功能")
    print("5. 缓存统计信息")
    
    print("\n使用方法:")
    print("# 创建缓存器")
    print("cache = BlastResultCache(expiry_time=86400)  # 24小时过期")
    print()
    print("# 检查缓存")
    print("cached_result = cache.get_cached_result(sequence)")
    print()
    print("# 保存结果")
    print("cache.save_result(sequence, result)")
    
    print("\n优势:")
    print("- 避免重复查询相同序列")
    print("- 显著提高重复查询速度")
    print("- 减少NCBI服务器负载")
    print("- 节省网络带宽")


if __name__ == "__main__":
    main()