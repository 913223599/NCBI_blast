"""
BLAST性能比较工具
比较不同BLAST查询方式的性能
"""

import time
from pathlib import Path


def compare_blast_methods(sequence_files, local_db_path=None):
    """
    比较不同BLAST查询方式的性能
    
    Args:
        sequence_files (list): 序列文件路径列表
        local_db_path (str): 本地数据库路径
    """
    print("BLAST性能比较工具")
    print("=" * 50)
    
    results = {}
    
    # 1. 测试远程BLAST（原版）
    print("\n1. 测试远程BLAST（原版）...")
    try:
        from .batch_processor import BatchProcessor
        processor = BatchProcessor(max_workers=3)
        
        start_time = time.time()
        remote_results = processor.process_sequences(sequence_files[:2])  # 只测试前2个以节省时间
        end_time = time.time()
        
        remote_time = end_time - start_time
        results['remote'] = {
            'time': remote_time,
            'success': sum(1 for r in remote_results if r["status"] == "success"),
            'total': len(remote_results)
        }
        
        print(f"  耗时: {remote_time:.2f}秒")
        print(f"  成功: {results['remote']['success']}/{results['remote']['total']}")
    except Exception as e:
        print(f"  远程BLAST测试失败: {e}")
        results['remote'] = {'time': float('inf'), 'error': str(e)}
    
    # 2. 测试优化远程BLAST
    print("\n2. 测试优化远程BLAST...")
    try:
        from .optimized_remote_blast import OptimizedBatchProcessor
        processor = OptimizedBatchProcessor(max_workers=5)
        
        start_time = time.time()
        opt_remote_results = processor.process_sequences(sequence_files[:2])
        end_time = time.time()
        
        opt_remote_time = end_time - start_time
        results['optimized_remote'] = {
            'time': opt_remote_time,
            'success': sum(1 for r in opt_remote_results if r["status"] == "success"),
            'total': len(opt_remote_results)
        }
        
        print(f"  耗时: {opt_remote_time:.2f}秒")
        print(f"  成功: {results['optimized_remote']['success']}/{results['optimized_remote']['total']}")
    except Exception as e:
        print(f"  优化远程BLAST测试失败: {e}")
        results['optimized_remote'] = {'time': float('inf'), 'error': str(e)}
    
    # 3. 测试本地BLAST（如果有本地数据库）
    if local_db_path and Path(local_db_path).exists():
        print("\n3. 测试本地BLAST...")
        try:
            from .local_blast import LocalBatchProcessor
            processor = LocalBatchProcessor(database_path=local_db_path)
            
            start_time = time.time()
            local_results = processor.process_sequences(sequence_files[:2])
            end_time = time.time()
            
            local_time = end_time - start_time
            results['local'] = {
                'time': local_time,
                'success': sum(1 for r in local_results if r["status"] == "success"),
                'total': len(local_results)
            }
            
            print(f"  耗时: {local_time:.2f}秒")
            print(f"  成功: {results['local']['success']}/{results['local']['total']}")
        except Exception as e:
            print(f"  本地BLAST测试失败: {e}")
            results['local'] = {'time': float('inf'), 'error': str(e)}
    else:
        print("\n3. 跳过本地BLAST测试（未找到本地数据库）")
        results['local'] = {'time': 0, 'skipped': True}
    
    # 4. 显示比较结果
    print("\n" + "=" * 50)
    print("性能比较结果:")
    print("=" * 50)
    
    # 按耗时排序（排除失败的测试）
    valid_results = {k: v for k, v in results.items() if 'time' in v and v['time'] != float('inf')}
    sorted_results = sorted(valid_results.items(), key=lambda x: x[1]['time'])
    
    if sorted_results:
        fastest_method = sorted_results[0][0]
        fastest_time = sorted_results[0][1]['time']
        
        print(f"最快方法: {fastest_method} ({fastest_time:.2f}秒)")
        
        for method, data in sorted_results:
            if method != fastest_method:
                speedup = data['time'] / fastest_time
                print(f"{method}: {data['time']:.2f}秒 (慢 {speedup:.1f} 倍)")
    else:
        print("所有测试都失败了，请检查配置")
    
    return results


def main():
    """
    性能比较工具主函数
    """
    print("BLAST查询方式性能比较")
    print("=" * 30)
    
    print("此工具将比较以下BLAST查询方式的性能:")
    print("1. 原版远程BLAST")
    print("2. 优化远程BLAST")
    print("3. 本地BLAST（需要预先配置）")
    
    print("\n使用方法:")
    print("# 在代码中调用")
    print("from performance_comparison import compare_blast_methods")
    print("results = compare_blast_methods(sequence_files, local_db_path='database/nt')")
    
    print("\n性能优化建议:")
    print("1. 本地BLAST: 最快，但需要下载数据库")
    print("2. 优化远程BLAST: 比原版快，通过并发和参数优化")
    print("3. 原版远程BLAST: 最慢，但配置简单")


if __name__ == "__main__":
    main()