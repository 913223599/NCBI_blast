"""
智能查询调度模块
优化查询顺序和资源利用
"""

import random
from collections import deque
from pathlib import Path


class SmartQueryScheduler:
    """
    智能查询调度器
    优化查询顺序和资源利用
    """
    
    def __init__(self, max_workers=5, priority_strategy='size'):
        """
        初始化智能查询调度器
        
        Args:
            max_workers (int): 最大并发工作线程数
            priority_strategy (str): 优先级策略 ('size', 'name', 'random')
        """
        self.max_workers = max_workers
        self.priority_strategy = priority_strategy
        self.query_queue = deque()
        self.completed_queries = []
        self.failed_queries = []
    
    def prioritize_sequences(self, sequence_files):
        """
        为序列文件设置优先级
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: 按优先级排序的序列文件列表
        """
        if self.priority_strategy == 'size':
            # 按文件大小排序（小文件优先）
            return sorted(sequence_files, key=lambda f: Path(f).stat().st_size)
        elif self.priority_strategy == 'name':
            # 按文件名字典序排序
            return sorted(sequence_files, key=lambda f: Path(f).name)
        elif self.priority_strategy == 'random':
            # 随机排序
            files = sequence_files.copy()
            random.shuffle(files)
            return files
        else:
            # 默认按原始顺序
            return sequence_files
    
    def adaptive_rate_control(self, success_rate, base_delay=2):
        """
        自适应速率控制
        
        Args:
            success_rate (float): 成功率 (0-1)
            base_delay (int): 基础延迟（秒）
            
        Returns:
            float: 计算的延迟时间
        """
        # 根据成功率调整延迟
        # 成功率低时增加延迟，成功率高时减少延迟
        if success_rate < 0.5:
            return base_delay * 3  # 低成功率时大幅增加延迟
        elif success_rate < 0.8:
            return base_delay * 2  # 中等成功率时适度增加延迟
        else:
            return base_delay * 0.5  # 高成功率时减少延迟
    
    def batch_processing(self, sequence_files, batch_size=10):
        """
        批量处理序列文件
        
        Args:
            sequence_files (list): 序列文件路径列表
            batch_size (int): 批处理大小
            
        Yields:
            list: 每批序列文件
        """
        # 按优先级排序
        prioritized_files = self.prioritize_sequences(sequence_files)
        
        # 分批处理
        for i in range(0, len(prioritized_files), batch_size):
            batch = prioritized_files[i:i + batch_size]
            yield batch
    
    def dynamic_worker_adjustment(self, current_success_rate):
        """
        动态调整工作线程数
        
        Args:
            current_success_rate (float): 当前成功率
            
        Returns:
            int: 调整后的工作线程数
        """
        if current_success_rate > 0.9:
            # 高成功率时可以增加并发
            return min(self.max_workers + 1, 10)
        elif current_success_rate < 0.3:
            # 低成功率时减少并发
            return max(self.max_workers - 1, 1)
        else:
            # 保持当前并发数
            return self.max_workers
    
    def monitor_and_adapt(self, completed_count, failed_count, total_count):
        """
        监控并自适应调整策略
        
        Args:
            completed_count (int): 完成的查询数
            failed_count (int): 失败的查询数
            total_count (int): 总查询数
            
        Returns:
            dict: 调整建议
        """
        processed_count = completed_count + failed_count
        if processed_count == 0:
            success_rate = 1.0
        else:
            success_rate = completed_count / processed_count
        
        # 计算进度
        progress = processed_count / total_count if total_count > 0 else 0
        
        # 获取自适应延迟
        delay = self.adaptive_rate_control(success_rate)
        
        # 动态调整工作线程数
        workers = self.dynamic_worker_adjustment(success_rate)
        
        return {
            'success_rate': success_rate,
            'progress': progress,
            'recommended_delay': delay,
            'recommended_workers': workers,
            'status': 'good' if success_rate > 0.8 else 'warning' if success_rate > 0.5 else 'poor'
        }


class SequenceAnalyzer:
    """
    序列分析器
    分析序列特征以优化处理策略
    """
    
    def __init__(self):
        """
        初始化序列分析器
        """
        pass
    
    def analyze_sequence(self, sequence_file):
        """
        分析序列特征
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 序列特征分析结果
        """
        try:
            with open(sequence_file, 'r') as f:
                sequence = f.read().strip()
            
            # 基本统计
            length = len(sequence)
            gc_content = self._calculate_gc_content(sequence)
            complexity = self._estimate_complexity(sequence)
            
            return {
                'file': sequence_file,
                'length': length,
                'gc_content': gc_content,
                'complexity': complexity,
                'estimated_difficulty': self._estimate_difficulty(length, gc_content, complexity)
            }
        except Exception as e:
            return {
                'file': sequence_file,
                'error': str(e)
            }
    
    def _calculate_gc_content(self, sequence):
        """
        计算GC含量
        
        Args:
            sequence (str): 序列
            
        Returns:
            float: GC含量百分比
        """
        if not sequence:
            return 0.0
        
        gc_count = sequence.upper().count('G') + sequence.upper().count('C')
        return (gc_count / len(sequence)) * 100
    
    def _estimate_complexity(self, sequence):
        """
        估算序列复杂度
        
        Args:
            sequence (str): 序列
            
        Returns:
            float: 复杂度评分 (0-1)
        """
        if not sequence:
            return 0.0
        
        # 简单的复杂度估算：基于重复模式的检测
        unique_kmers = set()
        kmer_size = min(6, len(sequence))
        
        for i in range(len(sequence) - kmer_size + 1):
            kmer = sequence[i:i + kmer_size]
            unique_kmers.add(kmer)
        
        total_kmers = max(1, len(sequence) - kmer_size + 1)
        return len(unique_kmers) / total_kmers
    
    def _estimate_difficulty(self, length, gc_content, complexity):
        """
        估算BLAST查询难度
        
        Args:
            length (int): 序列长度
            gc_content (float): GC含量
            complexity (float): 复杂度
            
        Returns:
            str: 难度等级 ('easy', 'medium', 'hard')
        """
        # 简单的难度评估规则
        if length < 100 or complexity > 0.8:
            return 'easy'
        elif length > 1000 or complexity < 0.3 or gc_content > 70 or gc_content < 30:
            return 'hard'
        else:
            return 'medium'


def main():
    """
    智能调度模块使用示例
    """
    print("智能查询调度模块")
    print("=" * 30)
    
    print("功能特点:")
    print("1. 智能优先级排序")
    print("2. 自适应速率控制")
    print("3. 动态工作线程调整")
    print("4. 批量处理优化")
    print("5. 实时监控和调整")
    
    print("\n优先级策略:")
    print("- size: 小文件优先")
    print("- name: 按文件名字典序")
    print("- random: 随机排序")
    
    print("\n自适应控制:")
    print("- 根据成功率动态调整请求频率")
    print("- 根据成功率动态调整并发线程数")
    print("- 实时监控处理进度和成功率")
    
    print("\n使用方法:")
    print("# 创建调度器")
    print("scheduler = SmartQueryScheduler(max_workers=5, priority_strategy='size')")
    print()
    print("# 设置优先级")
    print("prioritized_files = scheduler.prioritize_sequences(sequence_files)")
    print()
    print("# 批量处理")
    print("for batch in scheduler.batch_processing(sequence_files, batch_size=10):")
    print("    process_batch(batch)")


if __name__ == "__main__":
    main()