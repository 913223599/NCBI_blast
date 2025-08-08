"""
终极BLAST处理器
整合所有优化技术的综合解决方案
"""

import time
from pathlib import Path


class UltimateBlastProcessor:
    """
    终极BLAST处理器
    整合所有优化技术的综合解决方案
    """
    
    def __init__(self, config=None):
        """
        初始化终极BLAST处理器
        
        Args:
            config (dict): 配置参数
        """
        self.config = config or self._get_default_config()
        self.cache_enabled = self.config.get('cache_enabled', True)
        self.local_enabled = self.config.get('local_enabled', False)
        self.remote_enabled = self.config.get('remote_enabled', True)
        self.hybrid_mode = self.config.get('hybrid_mode', True)
        
        # 初始化组件
        self._initialize_components()
    
    def _get_default_config(self):
        """
        获取默认配置
        
        Returns:
            dict: 默认配置
        """
        return {
            'cache_enabled': True,
            'cache_expiry': 86400,
            'local_enabled': False,
            'local_db_path': None,
            'remote_enabled': True,
            'hybrid_mode': True,
            'max_workers': 5,
            'priority_strategy': 'size',
            'batch_size': 10,
            'retry_attempts': 3
        }
    
    def _initialize_components(self):
        """
        初始化各组件
        """
        # 初始化缓存
        if self.cache_enabled:
            from .result_cache import BlastResultCache
            self.cache = BlastResultCache(expiry_time=self.config['cache_expiry'])
        else:
            self.cache = None
        
        # 初始化本地BLAST
        if self.local_enabled and self.config['local_db_path']:
            try:
                from .local_blast import LocalBlastExecutor
                self.local_executor = LocalBlastExecutor(
                    database_path=self.config['local_db_path']
                )
            except Exception as e:
                print(f"本地BLAST初始化失败: {e}")
                self.local_enabled = False
                self.local_executor = None
        else:
            self.local_executor = None
        
        # 初始化远程BLAST
        if self.remote_enabled:
            from .executor import BlastExecutor
            self.remote_executor = BlastExecutor()
        else:
            self.remote_executor = None
        
        # 初始化调度器
        from .smart_scheduler import SmartQueryScheduler
        self.scheduler = SmartQueryScheduler(
            max_workers=self.config['max_workers'],
            priority_strategy=self.config['priority_strategy']
        )
        
        # 初始化序列分析器
        from .smart_scheduler import SequenceAnalyzer
        self.analyzer = SequenceAnalyzer()
    
    def process_sequences(self, sequence_files):
        """
        处理序列文件（终极优化版）
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: 处理结果列表
        """
        print("启动终极BLAST处理器")
        print(f"待处理序列数: {len(sequence_files)}")
        
        # 1. 序列分析和优先级排序
        print("1. 分析序列特征...")
        sequence_analysis = self._analyze_sequences(sequence_files)
        
        # 2. 智能优先级排序
        print("2. 设置处理优先级...")
        prioritized_files = self.scheduler.prioritize_sequences(sequence_files)
        
        # 3. 批量处理
        print("3. 开始批量处理...")
        results = []
        total_batches = (len(prioritized_files) + self.config['batch_size'] - 1) // self.config['batch_size']
        
        for i, batch in enumerate(self.scheduler.batch_processing(
            prioritized_files, self.config['batch_size']
        )):
            print(f"  处理批次 {i+1}/{total_batches} (包含 {len(batch)} 个序列)")
            batch_results = self._process_batch(batch)
            results.extend(batch_results)
            
            # 显示批次处理进度
            completed = len([r for r in results if r['status'] == 'success'])
            print(f"  批次完成，累计成功处理: {completed}/{len(results)}")
        
        # 4. 显示最终结果
        self._print_final_summary(results)
        
        return results
    
    def _analyze_sequences(self, sequence_files):
        """
        分析序列特征
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: 序列分析结果
        """
        analysis_results = []
        for seq_file in sequence_files:
            analysis = self.analyzer.analyze_sequence(seq_file)
            analysis_results.append(analysis)
        return analysis_results
    
    def _process_batch(self, batch_files):
        """
        处理批次序列
        
        Args:
            batch_files (list): 批次序列文件列表
            
        Returns:
            list: 批次处理结果
        """
        batch_results = []
        
        for seq_file in batch_files:
            # 1. 检查缓存
            result = self._check_cache(seq_file)
            if result:
                batch_results.append(result)
                continue
            
            # 2. 选择处理方式
            if self.hybrid_mode:
                result = self._process_hybrid(seq_file)
            elif self.local_enabled and self.local_executor:
                result = self._process_local(seq_file)
            elif self.remote_enabled and self.remote_executor:
                result = self._process_remote(seq_file)
            else:
                result = {
                    'file': seq_file,
                    'status': 'error',
                    'error': '没有可用的处理方式'
                }
            
            # 3. 保存到缓存
            if result['status'] == 'success' and self.cache:
                self._save_to_cache(seq_file, result)
            
            batch_results.append(result)
        
        return batch_results
    
    def _check_cache(self, sequence_file):
        """
        检查缓存
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict or None: 缓存结果，如果没有则返回None
        """
        if not self.cache_enabled or not self.cache:
            return None
        
        try:
            with open(sequence_file, 'r') as f:
                sequence = f.read().strip()
            
            cached_result = self.cache.get_cached_result(sequence)
            if cached_result:
                cached_result['from_cache'] = True
                print(f"    ✓ 使用缓存: {Path(sequence_file).name}")
                return cached_result
        except Exception as e:
            print(f"    缓存检查失败: {e}")
        
        return None
    
    def _save_to_cache(self, sequence_file, result):
        """
        保存结果到缓存
        
        Args:
            sequence_file (str): 序列文件路径
            result (dict): 处理结果
        """
        if not self.cache_enabled or not self.cache:
            return
        
        try:
            with open(sequence_file, 'r') as f:
                sequence = f.read().strip()
            
            self.cache.save_result(sequence, result)
        except Exception as e:
            print(f"    缓存保存失败: {e}")
    
    def _process_hybrid(self, sequence_file):
        """
        混合模式处理
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果
        """
        # 1. 尝试本地处理
        if self.local_enabled and self.local_executor:
            result = self._process_local(sequence_file)
            if result['status'] == 'success':
                result['method'] = 'local'
                return result
        
        # 2. 回退到远程处理
        if self.remote_enabled and self.remote_executor:
            result = self._process_remote(sequence_file)
            if result['status'] == 'success':
                result['method'] = 'remote'
                return result
        
        return {
            'file': sequence_file,
            'status': 'error',
            'error': '所有处理方式都失败了',
            'method': 'none'
        }
    
    def _process_local(self, sequence_file):
        """
        本地处理
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果
        """
        try:
            file_name = Path(sequence_file).stem
            result_file = Path("results") / f"{file_name}_ultimate_local_result.xml"
            
            self.local_executor.execute_local_blast(sequence_file, str(result_file))
            
            return {
                'file': sequence_file,
                'status': 'success',
                'result_file': str(result_file),
                'method': 'local'
            }
        except Exception as e:
            return {
                'file': sequence_file,
                'status': 'error',
                'error': str(e),
                'method': 'local'
            }
    
    def _process_remote(self, sequence_file):
        """
        远程处理
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果
        """
        # 实现重试机制
        for attempt in range(self.config['retry_attempts']):
            try:
                with open(sequence_file, 'r') as f:
                    sequence = f.read().strip()
                
                result_handle = self.remote_executor.execute_blast_search(sequence)
                
                file_name = Path(sequence_file).stem
                result_file = Path("results") / f"{file_name}_ultimate_remote_result.xml"
                
                with open(result_file, "w") as out_handle:
                    out_handle.write(result_handle.read())
                
                result_handle.close()
                
                return {
                    'file': sequence_file,
                    'status': 'success',
                    'result_file': str(result_file),
                    'method': 'remote'
                }
            except Exception as e:
                if attempt < self.config['retry_attempts'] - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    print(f"    远程处理失败，{wait_time}秒后重试... (尝试 {attempt + 1}/{self.config['retry_attempts']})")
                    time.sleep(wait_time)
                else:
                    return {
                        'file': sequence_file,
                        'status': 'error',
                        'error': str(e),
                        'method': 'remote'
                    }
    
    def _print_final_summary(self, results):
        """
        打印最终处理总结
        
        Args:
            results (list): 处理结果列表
        """
        total = len(results)
        successful = sum(1 for r in results if r["status"] == "success")
        failed = total - successful
        
        # 统计各方法的使用情况
        method_stats = {}
        cache_hits = 0
        
        for result in results:
            method = result.get('method', 'unknown')
            method_stats[method] = method_stats.get(method, 0) + 1
            if result.get('from_cache', False):
                cache_hits += 1
        
        print("\n" + "=" * 50)
        print("终极BLAST处理完成")
        print("=" * 50)
        print(f"总计处理: {total} 个序列")
        print(f"成功处理: {successful} 个序列")
        print(f"处理失败: {failed} 个序列")
        print(f"成功率: {successful/total*100:.1f}%" if total > 0 else "成功率: 0%")
        
        if cache_hits > 0:
            print(f"缓存命中: {cache_hits} 个序列")
        
        print("\n处理方式统计:")
        for method, count in method_stats.items():
            print(f"  {method.upper()}: {count} 个序列")
        
        if failed > 0:
            print("\n失败的序列:")
            for result in results:
                if result["status"] == "error":
                    print(f"  - {Path(result['file']).name}: {result['error']}")


def main():
    """
    终极BLAST处理器使用示例
    """
    print("终极BLAST处理器")
    print("=" * 30)
    
    print("功能特点:")
    print("1. 整合所有优化技术")
    print("2. 智能处理方式选择")
    print("3. 自动缓存管理")
    print("4. 批量处理优化")
    print("5. 多层次错误处理")
    
    print("\n处理流程:")
    print("1. 序列特征分析")
    print("2. 智能优先级排序")
    print("3. 缓存检查")
    print("4. 混合模式处理")
    print("5. 结果缓存")
    print("6. 批量处理")
    
    print("\n配置选项:")
    print("- 缓存启用/禁用")
    print("- 本地/远程/混合模式")
    print("- 并发线程数")
    print("- 批处理大小")
    print("- 重试次数")
    
    print("\n使用方法:")
    print("# 创建处理器")
    print("config = {")
    print("    'cache_enabled': True,")
    print("    'local_enabled': True,")
    print("    'local_db_path': 'database/nt',")
    print("    'max_workers': 5")
    print("}")
    print("processor = UltimateBlastProcessor(config)")
    print()
    print("# 处理序列")
    print("results = processor.process_sequences(sequence_files)")


if __name__ == "__main__":
    main()