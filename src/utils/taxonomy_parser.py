"""
NCBI Taxonomy数据库解析器
用于解析和处理NCBI Taxonomy数据库文件
"""

import os
from typing import Dict, List, Iterator, Tuple


class TaxonomyParser:
    """
    NCBI Taxonomy数据库解析器
    支持解析nodes.dmp和names.dmp文件
    """
    
    def __init__(self, taxdump_path: str = "database/taxdmp"):
        """
        初始化解析器
        
        Args:
            taxdump_path (str): taxonomy数据库文件路径
        """
        # 获取项目根目录的绝对路径
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # 构建绝对路径
        self.taxdump_path = os.path.join(project_root, taxdump_path)
        self.nodes_file = os.path.join(self.taxdump_path, "nodes.dmp")
        self.names_file = os.path.join(self.taxdump_path, "names.dmp")
        
        # 确保路径使用正斜杠，兼容不同操作系统
        self.taxdump_path = self.taxdump_path.replace("\\", "/")
        self.nodes_file = self.nodes_file.replace("\\", "/")
        self.names_file = self.names_file.replace("\\", "/")
        
    def parse_nodes(self) -> Iterator[Dict[str, str]]:
        """
        解析nodes.dmp文件
        
        Yields:
            dict: 包含节点信息的字典
        """
        if not os.path.exists(self.nodes_file):
            raise FileNotFoundError(f"Nodes file not found: {self.nodes_file}")
            
        with open(self.nodes_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    # 按照readme.txt中的说明，字段分隔符是"\t|\t"
                    fields = line.strip().split("\t|\t")
                    if len(fields) >= 13:  # nodes.dmp有13个字段
                        node_info = {
                            'tax_id': fields[0],
                            'parent_tax_id': fields[1],
                            'rank': fields[2],
                            'embl_code': fields[3],
                            'division_id': fields[4],
                            'inherited_div_flag': fields[5],
                            'genetic_code_id': fields[6],
                            'inherited_gc_flag': fields[7],
                            'mitochondrial_genetic_code_id': fields[8],
                            'inherited_mgc_flag': fields[9],
                            'genbank_hidden_flag': fields[10],
                            'hidden_subtree_root_flag': fields[11],
                            'comments': fields[12].rstrip("\t|")  # 移除行尾的\t|
                        }
                        yield node_info
    
    def parse_names(self) -> Iterator[Dict[str, str]]:
        """
        解析names.dmp文件
        
        Yields:
            dict: 包含名称信息的字典
        """
        if not os.path.exists(self.names_file):
            raise FileNotFoundError(f"Names file not found: {self.names_file}")
            
        with open(self.names_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    # 按照readme.txt中的说明，字段分隔符是"\t|\t"
                    fields = line.strip().split("\t|\t")
                    if len(fields) >= 4:  # names.dmp有4个字段
                        name_info = {
                            'tax_id': fields[0],
                            'name_txt': fields[1],
                            'unique_name': fields[2],
                            'name_class': fields[3].rstrip("\t|")  # 移除行尾的\t|
                        }
                        yield name_info
    
    def get_scientific_names(self) -> Dict[str, str]:
        """
        获取所有科学名称（scientific name）
        
        Returns:
            dict: tax_id到科学名称的映射
        """
        scientific_names = {}
        for name_info in self.parse_names():
            if name_info['name_class'] == 'scientific name':
                scientific_names[name_info['tax_id']] = name_info['name_txt']
        return scientific_names
    
    def get_taxonomy_tree(self, tax_id: str) -> List[Tuple[str, str, str]]:
        """
        获取指定tax_id的分类树路径
        
        Args:
            tax_id (str): 分类单元ID
            
        Returns:
            list: 从根到指定节点的路径，每个元素为(tax_id, name, rank)
        """
        # 获取科学名称映射
        scientific_names = self.get_scientific_names()
        
        # 获取节点信息
        nodes = {}
        for node_info in self.parse_nodes():
            nodes[node_info['tax_id']] = node_info
            
        # 构建从指定节点到根的路径
        path = []
        current_id = tax_id
        
        while current_id in nodes:
            node = nodes[current_id]
            name = scientific_names.get(current_id, "Unknown")
            path.append((current_id, name, node['rank']))
            
            # 如果到达根节点则停止
            if current_id == node['parent_tax_id']:
                break
                
            current_id = node['parent_tax_id']
            
        # 反转路径，使其从根到叶
        path.reverse()
        return path


def get_taxonomy_parser(taxdump_path: str = "database/taxdmp") -> TaxonomyParser:
    """
    获取Taxonomy解析器实例
    
    Args:
        taxdump_path (str): taxonomy数据库文件路径
        
    Returns:
        TaxonomyParser: 解析器实例
    """
    return TaxonomyParser(taxdump_path)