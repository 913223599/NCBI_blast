"""
本地BLAST工具模块
使用本地数据库进行BLAST搜索，大幅提高查询速度
"""

import subprocess
import shutil
import os
from pathlib import Path
from Bio.Blast import NCBIXML

class LocalBlastExecutor:
    """
    本地BLAST执行器
    使用本地数据库进行BLAST搜索
    """

    def __init__(self, database_path="database/nt"):
        self.database_path = database_path
        # 根据操作系统自动查找可执行文件，Windows下可能需要.exe后缀
        self.blast_bin = "blastn"

    def check_blast_installation(self):
        """
        检查BLAST是否已安装
        使用 shutil.which 提供更健壮的跨平台检查
        """
        return shutil.which(self.blast_bin) is not None

    def download_database(self, db_name="nt", output_dir="database"):
        """下载BLAST数据库提示"""
        print(f"请手动下载数据库 {db_name} 到 {output_dir} 目录:")
        print("方法一：使用NCBI提供的工具")
        print(f"  update_blastdb.pl --decompress {db_name}")
        print("方法二：从NCBI网站下载")
        print(f"  https://ftp.ncbi.nih.gov/blast/db/")

    def execute_local_blast(self, sequence_file, output_file, max_hits=50):
        """执行本地BLAST搜索"""
        if not self.check_blast_installation():
            raise FileNotFoundError(f"未找到BLAST可执行文件: {self.blast_bin}，请确保已安装并添加到PATH环境变量。")

        if not Path(sequence_file).exists():
             raise FileNotFoundError(f"序列文件不存在: {sequence_file}")

        # 构建BLAST命令行参数
        blast_cmd = [
            self.blast_bin,
            "-query", str(sequence_file),
            "-db", str(self.database_path),
            "-out", str(output_file),
            "-outfmt", "5",  # XML格式输出
            "-max_target_seqs", str(max_hits),
            "-evalue", "10.0"
        ]

        try:
            print(f"正在执行本地BLAST搜索: {Path(sequence_file).name}")
            # 使用 capture_output=True 捕获输出，text=True 确保返回字符串
            subprocess.run(
                blast_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return output_file

        except subprocess.CalledProcessError as e:
            error_msg = f"本地BLAST执行失败 (Exit code {e.returncode}):\n{e.stderr}"
            raise RuntimeError(error_msg)

    def parse_result(self, result_file):
        """
        解析BLAST结果
        修复了使用 next() 可能导致的 StopIteration 错误
        """
        try:
            with open(result_file, 'r') as result_handle:
                # NCBIXML.parse 返回的是迭代器，转换为列表以安全访问
                blast_records = list(NCBIXML.parse(result_handle))

                if not blast_records:
                    print(f"警告: {result_file} 中未发现BLAST记录")
                    return None

                # 目前逻辑只处理单条序列的搜索结果
                return blast_records[0]
        except Exception as e:
            raise RuntimeError(f"解析BLAST结果失败: {e}")

    def display_result_summary(self, blast_record, top_hits=5):
        """显示结果摘要"""
        if not blast_record:
            print("没有可显示的BLAST记录。")
            return

        print(f"\n找到 {len(blast_record.alignments)} 个比对结果")
        print(f"\n前{top_hits}个最佳比对:")
        print("=" * 80)

        for i, alignment in enumerate(blast_record.alignments[:top_hits]):
            print(f"匹配 {i+1}:")
            print(f"标题: {alignment.title}")
            print(f"长度: {alignment.length}")

            if alignment.hsps:
                hsp = alignment.hsps[0] # 只显示最好的HSP
                print(f"E值: {hsp.expect}")
                print(f"得分: {hsp.score}")
                print(f"比对长度: {hsp.align_length}")
                if hsp.align_length > 0:
                    print(f"相似度: {hsp.identities / hsp.align_length * 100:.2f}%")
                print(f"缺口: {hsp.gaps}")

            print("=" * 80)

# LocalBatchProcessor 类保持原逻辑，只需确保调用新的 execute_local_blast 即可
class LocalBatchProcessor:
    def __init__(self, database_path="nt"):
        self.database_path = database_path
        self.blast_executor = LocalBlastExecutor(database_path=database_path)

    def process_single_sequence(self, sequence_file):
        try:
            file_path = Path(sequence_file)
            file_name = file_path.stem

            # 确保结果目录存在
            # 获取项目根目录 (src/blast/local_blast.py -> src/blast -> src -> root)
            project_root = Path(__file__).resolve().parent.parent.parent
            results_dir = project_root / "results"
            results_dir.mkdir(exist_ok=True)
            result_file = results_dir / f"{file_name}_local_blast_result.xml"

            self.blast_executor.execute_local_blast(str(file_path), str(result_file))
            blast_record = self.blast_executor.parse_result(str(result_file))

            print(f"\n文件 {file_name} 的搜索结果:")
            self.blast_executor.display_result_summary(blast_record, top_hits=3)

            return {
                "file": str(sequence_file),
                "status": "success",
                "result_file": str(result_file)
            }
        except Exception as e:
            print(f"处理文件 {sequence_file} 时出错: {e}")
            return {
                "file": str(sequence_file),
                "status": "error",
                "error": str(e)
            }

    def process_sequences(self, sequence_files):
        print(f"开始本地批量处理 {len(sequence_files)} 个序列文件...")
        return [self.process_single_sequence(f) for f in sequence_files]

def main():
    executor = LocalBlastExecutor()
    if executor.check_blast_installation():
         print("✓ BLAST+ 已正确安装")
    else:
         print("✗ 未检测到 BLAST+")

if __name__ == "__main__":
    main()