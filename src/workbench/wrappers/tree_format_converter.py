"""
Tree Format Converter - 负责进化树格式转换
职责：处理Newick、二进制等树格式的相互转换
"""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class TreeFormatConverter:
    """树格式转换器"""
    
    def __init__(self):
        pass
    
    def newick_to_binary(self, input_nwk: Path, output_bin: Path = None) -> Path:
        """
        将Newick格式转换为NCBI tree-tool的二进制格式
        
        Args:
            input_nwk: Newick文件路径
            output_bin: 输出二进制文件路径（可选）
            
        Returns:
            二进制文件路径
        """
        if not input_nwk.exists():
            raise FileNotFoundError(f"Newick file not found: {input_nwk}")
        
        if output_bin is None:
            output_bin = input_nwk.with_suffix(".tree")
        
        try:
            # 调用NCBI的newick2tree工具进行转换
            from src.workbench.wrappers.base_wrapper import BaseWrapper
            
            class TempWrapper(BaseWrapper):
                pass
            
            wrapper = TempWrapper()
            result = wrapper._run_command("newick2tree.exe", [str(input_nwk)])
            
            # 写入二进制内容
            with open(output_bin, 'wb') as f:
                f.write(result.stdout.encode('utf-8'))
            
            logger.info(f"Converted Newick to binary: {output_bin}")
            return output_bin
            
        except Exception as e:
            logger.error(f"Failed to convert Newick to binary: {e}")
            raise
    
    def validate_newick_format(self, newick_content: str) -> bool:
        """
        验证Newick格式的基本合法性
        
        Args:
            newick_content: Newick字符串
            
        Returns:
            True if valid, False otherwise
        """
        if not newick_content or not newick_content.strip():
            return False
        
        content = newick_content.strip()
        
        # 基本检查：必须以分号结尾
        if not content.endswith(';'):
            return False
        
        # 括号匹配检查
        if content.count('(') != content.count(')'):
            return False
        
        # 至少包含一对括号
        if '(' not in content:
            return False
        
        return True
    
    def normalize_newick(self, newick_content: str) -> str:
        """
        规范化Newick格式（清理多余空格、确保分号结尾等）
        
        Args:
            newick_content: 原始Newick字符串
            
        Returns:
            规范化后的Newick字符串
        """
        if not newick_content:
            return newick_content
        
        normalized = newick_content.strip()
        
        # 确保以分号结尾
        if not normalized.endswith(';'):
            normalized += ';'
        
        # 清理多余空白
        import re
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized
    
    def extract_tree_statistics(self, tree_file: Path) -> dict:
        """
        提取树的基本统计信息
        
        Args:
            tree_file: 树文件路径（Newick或binary）
            
        Returns:
            统计信息字典
        """
        stats = {
            "file_path": str(tree_file),
            "format": "unknown",
            "leaf_count": 0,
            "internal_node_count": 0
        }
        
        try:
            # 检测文件格式
            if tree_file.suffix in ['.nwk', '.newick', '.tree']:
                content = tree_file.read_text(encoding='utf-8')
                if self.validate_newick_format(content):
                    stats["format"] = "newick"
                    
                    # 简单统计叶子节点（通过逗号数量估算）
                    # 更精确的统计需要使用专门的树解析库
                    leaf_estimate = content.count(',') + 1
                    stats["leaf_count"] = leaf_estimate
            
            elif tree_file.suffix == '.tree':
                stats["format"] = "binary"
                # 二进制格式需要特殊解析，这里暂不实现
            
        except Exception as e:
            logger.warning(f"Failed to extract tree statistics: {e}")
        
        return stats
