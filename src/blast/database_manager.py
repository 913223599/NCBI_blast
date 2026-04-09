"""
本地数据库管理器
负责创建、管理和查询本地BLAST数据库
"""

import glob
import os
import shutil
import subprocess


class DatabaseManager:
    def __init__(self, db_root="database"):
        """
        初始化数据库管理器
        :param db_root: 数据库存储根目录，默认为项目根目录下的 database
        """
        if not os.path.isabs(db_root):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_root = os.path.join(project_root, db_root)
        else:
            self.db_root = db_root
            
        if not os.path.exists(self.db_root):
            os.makedirs(self.db_root)
            
        self.makeblastdb_bin = "makeblastdb"

    def check_makeblastdb_installation(self):
        """检查 makeblastdb 是否已安装"""
        return shutil.which(self.makeblastdb_bin) is not None

    def make_blast_db(self, input_file, db_type, title, out_name=None):
        """
        创建BLAST数据库
        :param input_file: 输入FASTA文件路径
        :param db_type: 数据库类型 ('nucl' 或 'prot')
        :param title: 数据库标题
        :param out_name: 输出数据库名称（不含路径），如果为None则使用title
        :return: (success, message)
        """
        if not self.check_makeblastdb_installation():
            return False, "未找到 makeblastdb 可执行文件，请确保已安装 BLAST+ 并添加到 PATH。"

        if not os.path.exists(input_file):
            return False, f"输入文件不存在: {input_file}"

        if not out_name:
            out_name = title.replace(" ", "_")

        # 确保输出目录存在
        out_path = os.path.join(self.db_root, out_name)
        
        # 构建命令
        cmd = [
            self.makeblastdb_bin,
            "-in", input_file,
            "-dbtype", db_type,
            "-title", title,
            "-out", out_path,
            "-parse_seqids"
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return True, f"数据库创建成功: {out_name}"
        except subprocess.CalledProcessError as e:
            return False, f"创建数据库失败:\n{e.stderr}"
        except Exception as e:
            return False, f"发生未知错误: {e}"

    def list_local_databases(self):
        """
        列出所有本地数据库
        :return: 数据库列表 [{'name': 'db_name', 'type': 'nucl/prot', 'path': 'full_path', 'size': 'size_str'}]
        """
        databases = []
        if not os.path.exists(self.db_root):
            return databases

        # 查找 .pin (蛋白) 和 .nin (核酸) 文件作为数据库存在的标志
        # BLAST数据库通常由多个文件组成，如 .nin, .nhr, .nsq
        
        # 扫描核酸数据库
        for nin_file in glob.glob(os.path.join(self.db_root, "*.nin")):
            db_path = nin_file[:-4] # 去掉 .nin
            db_name = os.path.basename(db_path)
            databases.append({
                'name': db_name,
                'type': 'nucl',
                'path': db_path,
                'files': self._get_db_files(db_path, 'nucl')
            })
            
        # 扫描蛋白数据库
        for pin_file in glob.glob(os.path.join(self.db_root, "*.pin")):
            db_path = pin_file[:-4] # 去掉 .pin
            db_name = os.path.basename(db_path)
            databases.append({
                'name': db_name,
                'type': 'prot',
                'path': db_path,
                'files': self._get_db_files(db_path, 'prot')
            })
            
        return databases

    def _get_db_files(self, db_path, db_type):
        """获取数据库相关的所有文件"""
        extensions = ['.nin', '.nhr', '.nsq'] if db_type == 'nucl' else ['.pin', '.phr', '.psq']
        files = []
        for ext in extensions:
            f = db_path + ext
            if os.path.exists(f):
                files.append(f)
        return files

    def delete_database(self, db_name):
        """删除指定的数据库"""
        # 查找数据库文件
        db_path = os.path.join(self.db_root, db_name)
        
        # 尝试删除所有相关文件
        deleted_files = []
        # 常见扩展名
        extensions = ['.nin', '.nhr', '.nsq', '.pin', '.phr', '.psq', '.nal', '.pal', '.ndb', '.pdb', '.not', '.pot', '.ntf', '.ptf', '.nto', '.pto']
        
        for ext in extensions:
            f = db_path + ext
            if os.path.exists(f):
                try:
                    os.remove(f)
                    deleted_files.append(f)
                except Exception as e:
                    print(f"删除文件失败 {f}: {e}")
                    
        return len(deleted_files) > 0
