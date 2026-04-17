"""
本地BLAST工具模块
使用本地数据库进行BLAST搜索，大幅提高查询速度
"""

import shutil
import subprocess
import threading
from pathlib import Path

from Bio.Blast import NCBIXML
from ..workbench.models.tool_config import ToolConfig
from ..backend.utils.compat import get_short_path_name

# 全局并发控制：限制同时运行的 blastn 进程数，防止 CPU 过载
# 默认为 4，可根据 CPU 核心数调整
_local_blast_semaphore = threading.Semaphore(4)

class LocalBlastExecutor:
    """
    本地BLAST执行器
    使用本地数据库进行BLAST搜索
    """

    def __init__(self, database_path="database/nt"):
        self.database_path = database_path
        try:
            self.blast_bin = str(ToolConfig.get_tool_path("blastn"))
        except:
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
            raise FileNotFoundError(f"未找到BLAST可执行文件: {self.blast_bin}")

        if not Path(sequence_file).exists():
             raise FileNotFoundError(f"序列文件不存在: {sequence_file}")

        # 核心优化：使用短路径解决 Windows 空格与内存映射问题
        bin_path = get_short_path_name(self.blast_bin)
        
        # 将输入输出文件转为绝对路径后取短路径
        abs_in = str(Path(sequence_file).resolve())
        abs_out = str(Path(output_file).resolve())
        
        # 确定数据库目录并作为工作目录
        db_full_path = Path(self.database_path).resolve()
        db_dir = str(db_full_path.parent)
        db_name = db_full_path.name
        
        short_db_dir = get_short_path_name(db_dir)
        short_in = get_short_path_name(abs_in)
        short_out = get_short_path_name(abs_out)

        # 构建BLAST命令行参数 (相对于 CWD)
        blast_cmd = [
            f'"{bin_path}"',
            "-query", f'"{short_in}"',
            "-db", f'"{db_name}"',
            "-out", f'"{short_out}"',
            "-outfmt", "5",
            "-max_target_seqs", str(max_hits),
            "-evalue", "10.0"
        ]

        cmd_str = " ".join(blast_cmd)

        try:
            print(f"🚀 [LocalBLAST] 执行比对 (CWD: {short_db_dir}): {cmd_str}")
            
            with _local_blast_semaphore:
                # 关键：在 Windows 下必须在无空格的 CWD 中运行或使用 shell=True 配合引号
                subprocess.run(
                    cmd_str,
                    cwd=short_db_dir,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True
                )
            
            if not Path(output_file).exists():
                raise RuntimeError(f"BLAST执行看似成功但未生成输出文件: {output_file}")
                
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