"""
优化的BLAST配置
提供经过优化的BLAST参数配置
"""

# 远程BLAST优化配置
REMOTE_BLAST_CONFIG = {
    # 基本参数
    'program': 'blastn',
    'database': 'nt',
    
    # 性能相关参数
    'hitlist_size': 50,          # 返回结果数量（减少以提高速度）
    'word_size': 28,             # 字词大小（较大的值提高速度但可能降低敏感性）
    'evalue': 10.0,              # E值阈值（较宽松的阈值）
    'max_hsps': 1,               # 每个匹配序列的最大HSP数
    
    # 并发参数
    'max_workers': 5,            # 最大并发线程数
    'request_delay': (1, 3),     # 请求间隔延迟（秒）
    'timeout': 60,               # 超时时间（秒）
    
    # 重试参数
    'max_retries': 3,            # 最大重试次数
    'retry_delay': (5, 10, 20),  # 重试延迟时间（秒）
}

# 本地BLAST优化配置
LOCAL_BLAST_CONFIG = {
    # 基本参数
    'program': 'blastn',
    'database': 'nt',
    
    # 性能相关参数
    'hitlist_size': 50,
    'word_size': 28,
    'evalue': 10.0,
    'max_hsps': 1,
    'num_threads': 4,            # 本地BLAST线程数
    
    # 输出参数
    'outfmt': 5,                 # XML格式输出
}

# 混合模式配置
HYBRID_CONFIG = {
    # 优先使用本地BLAST
    'prefer_local': True,
    
    # 当本地不可用时的备选方案
    'fallback_to_remote': True,
    
    # 批量处理大小
    'batch_size': 10,
    
    # 缓存设置
    'use_cache': True,
    'cache_expiry': 86400,       # 缓存过期时间（秒）
}

def get_optimized_config(config_type='remote'):
    """
    获取优化配置
    
    Args:
        config_type (str): 配置类型 ('remote', 'local', 'hybrid')
        
    Returns:
        dict: 配置字典
    """
    configs = {
        'remote': REMOTE_BLAST_CONFIG,
        'local': LOCAL_BLAST_CONFIG,
        'hybrid': HYBRID_CONFIG
    }
    
    return configs.get(config_type, REMOTE_BLAST_CONFIG)


def print_config_recommendations():
    """
    打印配置建议
    """
    print("BLAST配置优化建议")
    print("=" * 30)
    
    print("\n远程BLAST优化:")
    print("- 减少hitlist_size到50-100以提高响应速度")
    print("- 使用较大的word_size (28 for blastn)")
    print("- 设置合适的并发线程数 (3-5)")
    print("- 添加请求间隔避免服务器限制")
    
    print("\n本地BLAST优化:")
    print("- 确保有足够的内存和存储空间")
    print("- 使用SSD硬盘以提高数据库访问速度")
    print("- 设置合适的num_threads参数")
    print("- 定期更新本地数据库")
    
    print("\n混合模式优化:")
    print("- 优先使用本地BLAST处理")
    print("- 对于本地未命中的序列使用远程BLAST")
    print("- 实现结果缓存避免重复查询")
    print("- 根据序列特征动态选择处理方式")


if __name__ == "__main__":
    print_config_recommendations()