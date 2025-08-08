"""
混合BLAST查询模块
结合本地和远程BLAST的优势，提供最佳查询体验
"""

from datetime import datetime
from pathlib import Path


class HybridBlastProcessor:
    """
    混合BLAST处理器
    自动选择最适合的查询方式
    """
    
    def __init__(self, local_db_path=None, remote_enabled=True):
        """
        初始化混合BLAST处理器
        
        Args:
            local_db_path (str): 本地数据库路径
            remote_enabled (bool): 是否启用远程BLAST
        """
        self.local_db_path = local_db_path
        self.remote_enabled = remote_enabled
        self.local_available = False
        self.remote_available = remote_enabled
        
        # 检查本地BLAST是否可用
        if local_db_path and self._check_local_blast():
            self.local_available = True
    
    def _check_local_blast(self):
        """
        检查本地BLAST是否可用
        
        Returns:
            bool: 是否可用
        """
        try:
            from .local_blast import LocalBlastExecutor
            executor = LocalBlastExecutor(database_path=self.local_db_path)
            return True
        except Exception:
            return False
    
    def process_sequence(self, sequence_file, mode="auto"):
        """
        处理单个序列
        
        Args:
            sequence_file (str): 序列文件路径
            mode (str): 处理模式 ("auto", "local", "remote")
            
        Returns:
            dict: 处理结果
        """
        if mode == "auto":
            # 自动选择模式
            mode = self._select_best_mode()
        
        if mode == "local" and self.local_available:
            return self._process_local(sequence_file)
        elif mode == "remote" and self.remote_available:
            return self._process_remote(sequence_file)
        else:
            # 回退到可用的模式
            if self.local_available:
                return self._process_local(sequence_file)
            elif self.remote_available:
                return self._process_remote(sequence_file)
            else:
                return {
                    "file": sequence_file,
                    "status": "error",
                    "error": "没有可用的BLAST处理方式"
                }
    
    def _select_best_mode(self):
        """
        选择最佳处理模式
        
        Returns:
            str: 最佳模式 ("local" 或 "remote")
        """
        # 简单策略：如果有本地数据库，优先使用本地
        if self.local_available:
            return "local"
        elif self.remote_available:
            return "remote"
        else:
            return "remote"  # 默认
    
    def _process_local(self, sequence_file):
        """
        使用本地BLAST处理
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果
        """
        try:
            from .local_blast import LocalBlastExecutor
            executor = LocalBlastExecutor(database_path=self.local_db_path)
            
            file_name = Path(sequence_file).stem
            result_file = Path("results") / f"{file_name}_hybrid_blast_result.xml"
            
            # 执行本地BLAST搜索
            executor.execute_local_blast(sequence_file, str(result_file))
            
            return {
                "file": sequence_file,
                "status": "success",
                "mode": "local",
                "result_file": result_file,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "file": sequence_file,
                "status": "error",
                "mode": "local",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def _process_remote(self, sequence_file):
        """
        使用远程BLAST处理
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果
        """
        try:
            from .executor import BlastExecutor
            executor = BlastExecutor()
            
            # 读取序列
            with open(sequence_file, 'r') as f:
                sequence = f.read().strip()
            
            # 执行远程BLAST搜索
            result_handle = executor.execute_blast_search(sequence)
            
            file_name = Path(sequence_file).stem
            result_file = Path("results") / f"{file_name}_hybrid_blast_result.xml"
            
            # 保存结果
            with open(result_file, "w") as out_handle:
                out_handle.write(result_handle.read())
            
            result_handle.close()
            
            return {
                "file": sequence_file,
                "status": "success",
                "mode": "remote",
                "result_file": result_file,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "file": sequence_file,
                "status": "error",
                "mode": "remote",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def process_sequences(self, sequence_files, mode="auto"):
        """
        批量处理序列
        
        Args:
            sequence_files (list): 序列文件路径列表
            mode (str): 处理模式
            
        Returns:
            list: 处理结果列表
        """
        print(f"开始混合BLAST处理 {len(sequence_files)} 个序列文件...")
        print(f"处理模式: {mode}")
        
        # 创建结果目录
        Path("results").mkdir(exist_ok=True)
        
        results = []
        for seq_file in sequence_files:
            result = self.process_sequence(seq_file, mode)
            results.append(result)
            
            if result["status"] == "success":
                print(f"✓ 处理完成 [{result['mode']}]: {Path(seq_file).name}")
            else:
                print(f"✗ 处理失败 [{result['mode']}]: {Path(seq_file).name} - {result['error']}")
        
        # 显示处理总结
        self._print_summary(results)
        
        return results
    
    def _print_summary(self, results):
        """
        打印处理总结
        
        Args:
            results (list): 处理结果列表
        """
        total = len(results)
        successful = sum(1 for r in results if r["status"] == "success")
        failed = total - successful
        
        local_count = sum(1 for r in results if r.get("mode") == "local")
        remote_count = sum(1 for r in results if r.get("mode") == "remote")
        
        print(f"\n处理总结:")
        print(f"  总计: {total} 个文件")
        print(f"  成功: {successful} 个文件")
        print(f"  失败: {failed} 个文件")
        print(f"  本地处理: {local_count} 个文件")
        print(f"  远程处理: {remote_count} 个文件")


def main():
    """
    混合BLAST处理器使用示例
    """
    print("混合BLAST处理器")
    print("=" * 30)
    
    print("功能特点:")
    print("1. 自动选择最佳处理方式")
    print("2. 支持本地和远程BLAST")
    print("3. 提供统一的处理接口")
    print("4. 灵活的处理模式")
    
    print("\n使用方法:")
    print("# 使用自动模式")
    print("processor = HybridBlastProcessor(local_db_path='database/nt')")
    print("results = processor.process_sequences(sequence_files, mode='auto')")
    
    print("\n处理模式:")
    print("- auto: 自动选择（默认）")
    print("- local: 强制本地处理")
    print("- remote: 强制远程处理")
    
    print("\n优势:")
    print("- 本地处理: 速度快，无网络依赖")
    print("- 远程处理: 数据库更新及时")
    print("- 混合模式: 兼顾速度和数据新鲜度")


if __name__ == "__main__":
    main()