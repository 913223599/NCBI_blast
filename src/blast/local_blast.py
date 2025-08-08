"""
本地BLAST工具模块
使用本地数据库进行BLAST搜索，大幅提高查询速度
"""

import subprocess
from pathlib import Path

from Bio.Blast import NCBIXML
from Bio.Blast.Applications import NcbiblastnCommandline


class LocalBlastExecutor:
    """
    本地BLAST执行器
    使用本地数据库进行BLAST搜索
    """
    
    def __init__(self, database_path="nt", blast_bin_path=None):
        """
        初始化本地BLAST执行器
        
        Args:
            database_path (str): 数据库路径
            blast_bin_path (str): BLAST二进制文件路径（可选）
        """
        self.database_path = database_path
        self.blast_bin_path = blast_bin_path
        
        # 检查BLAST是否已安装
        if not self.is_blast_installed():
            raise RuntimeError(
                "未找到BLAST+工具。请先安装NCBI BLAST+:\n"
                "1. 访问 https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/ \n"
                "2. 下载并安装适合您操作系统的版本\n"
                "3. 将BLAST bin目录添加到系统PATH环境变量"
            )
    
    def is_blast_installed(self):
        """
        检查BLAST是否已安装
        
        Returns:
            bool: 是否已安装BLAST
        """
        try:
            # 尝试运行blastn命令
            subprocess.run(
                ["blastn", "-version"], 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def download_database(self, db_name="nt", output_dir="database"):
        """
        下载BLAST数据库（需要手动执行）
        
        Args:
            db_name (str): 数据库名称
            output_dir (str): 输出目录
        """
        print(f"请手动下载数据库 {db_name} 到 {output_dir} 目录:")
        print("方法一：使用NCBI提供的工具")
        print(f"  update_blastdb.pl --decompress {db_name}")
        print("方法二：从NCBI网站下载")
        print(f"  https://ftp.ncbi.nih.gov/blast/db/")
        print(f"  下载 {db_name}.*.tar.gz 文件并解压到 {output_dir} 目录")
    
    def execute_local_blast(self, sequence_file, output_file, max_hits=50):
        """
        执行本地BLAST搜索
        
        Args:
            sequence_file (str): 序列文件路径
            output_file (str): 输出文件路径
            max_hits (int): 最大匹配数
            
        Returns:
            str: 输出文件路径
        """
        try:
            # 构建BLAST命令行
            blastn_cline = NcbiblastnCommandline(
                query=sequence_file,
                db=self.database_path,
                out=output_file,
                outfmt=5,  # XML格式输出
                max_target_seqs=max_hits,
                evalue=10.0
            )
            
            print(f"正在执行本地BLAST搜索: {Path(sequence_file).name}")
            print(f"命令: {blastn_cline}")
            
            # 执行BLAST搜索
            stdout, stderr = blastn_cline()
            
            if stderr:
                print(f"警告: {stderr}")
            
            print(f"本地BLAST搜索完成，结果保存到: {output_file}")
            return output_file
            
        except Exception as e:
            raise RuntimeError(f"本地BLAST搜索失败: {e}")
    
    def parse_result(self, result_file):
        """
        解析BLAST结果
        
        Args:
            result_file (str): 结果文件路径
            
        Returns:
            blast_record: 解析后的BLAST记录
        """
        try:
            with open(result_file) as result_handle:
                blast_records = NCBIXML.parse(result_handle)
                blast_record = next(blast_records)
                return blast_record
        except Exception as e:
            raise RuntimeError(f"解析BLAST结果失败: {e}")
    
    def display_result_summary(self, blast_record, top_hits=5):
        """
        显示结果摘要
        
        Args:
            blast_record: BLAST记录
            top_hits (int): 显示前几个匹配结果
        """
        print(f"\n找到 {len(blast_record.alignments)} 个比对结果")
        print("\n前{}个最佳比对:".format(top_hits))
        print("=" * 80)
        
        for i, alignment in enumerate(blast_record.alignments[:top_hits]):
            print(f"匹配 {i+1}:")
            print(f"标题: {alignment.title}")
            print(f"长度: {alignment.length}")
            
            for hsp in alignment.hsps[:1]:  # 只显示最好的HSP
                print(f"E值: {hsp.expect}")
                print(f"得分: {hsp.score}")
                print(f"比对长度: {hsp.align_length}")
                print(f"相似度: {hsp.identities / hsp.align_length * 100:.2f}%")
                print(f"缺口: {hsp.gaps}")
            
            print("=" * 80)


class LocalBatchProcessor:
    """
    本地批量处理器
    使用本地BLAST进行批量序列处理
    """
    
    def __init__(self, database_path="nt"):
        """
        初始化本地批量处理器
        
        Args:
            database_path (str): 数据库路径
        """
        self.database_path = database_path
        self.blast_executor = LocalBlastExecutor(database_path=database_path)
    
    def process_single_sequence(self, sequence_file):
        """
        处理单个序列文件
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果信息
        """
        try:
            # 获取文件名（不含扩展名）用于结果文件命名
            file_name = Path(sequence_file).stem
            result_file = Path("results") / f"{file_name}_local_blast_result.xml"
            
            # 执行本地BLAST搜索
            self.blast_executor.execute_local_blast(sequence_file, str(result_file))
            
            # 解析结果
            blast_record = self.blast_executor.parse_result(str(result_file))
            
            # 显示结果摘要
            print(f"\n文件 {file_name} 的搜索结果:")
            self.blast_executor.display_result_summary(blast_record, top_hits=3)
            
            return {
                "file": sequence_file,
                "status": "success",
                "result_file": result_file
            }
        except Exception as e:
            print(f"处理文件 {sequence_file} 时出错: {e}")
            return {
                "file": sequence_file,
                "status": "error",
                "error": str(e)
            }
    
    def process_sequences(self, sequence_files):
        """
        批量处理序列文件
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: 处理结果列表
        """
        print(f"开始本地批量处理 {len(sequence_files)} 个序列文件...")
        
        # 创建结果目录（如果不存在）
        Path("results").mkdir(exist_ok=True)
        
        # 处理序列文件
        results = []
        for seq_file in sequence_files:
            result = self.process_single_sequence(seq_file)
            results.append(result)
            if result["status"] == "success":
                print(f"✓ 完成处理: {Path(seq_file).name}")
            else:
                print(f"✗ 处理失败: {Path(seq_file).name} - {result['error']}")
        
        return results


def main():
    """
    本地BLAST工具使用示例
    """
    print("本地BLAST工具")
    print("=" * 30)
    
    # 检查是否安装了BLAST
    try:
        executor = LocalBlastExecutor()
        print("✓ BLAST+ 已正确安装")
    except RuntimeError as e:
        print(f"✗ {e}")
        return
    
    print("\n使用说明:")
    print("1. 首先下载NCBI BLAST数据库:")
    print("   - 访问 https://ftp.ncbi.nih.gov/blast/db/")
    print("   - 下载 nt.*.tar.gz 文件并解压")
    print("2. 设置数据库路径")
    print("3. 运行本地BLAST搜索")
    
    print("\n本地BLAST优势:")
    print("- 查询速度快（秒级响应）")
    print("- 不依赖网络连接")
    print("- 可以处理大量序列")
    print("- 支持批量处理")


if __name__ == "__main__":
    main()