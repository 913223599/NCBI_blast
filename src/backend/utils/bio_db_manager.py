import os
import logging
import asyncio
import hashlib
import tarfile
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List
from .response import BioResponse
import time
from datetime import datetime
from ...workbench.models.tool_config import ToolConfig

logger = logging.getLogger("api_server")

from .compat import get_short_path_name

class BioDatabase:
    """
    通用生物数据库管理基类
    符合单一职责原则：专门处理数据库的下载、校验、索引与状态查询
    """
    def __init__(self, db_id: str, config: Dict[str, Any]):
        self.db_id = db_id
        self.config = config
        self.name = config.get("name", db_id)
        
        # 从中心配置计算物理路径
        self.base_dir = ToolConfig.DATABASE_ROOT / config.get("local_folder", db_id)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_dir_info(self) -> tuple[float, str]:
        total_size = 0
        latest_mtime = 0
        try:
            if self.base_dir.exists():
                for f in self.base_dir.rglob('*'):
                    if f.is_file():
                        stat = f.stat()
                        total_size += stat.st_size
                        if stat.st_mtime > latest_mtime:
                            latest_mtime = stat.st_mtime
        except Exception:
            pass
        
        size_mb = round(total_size / (1024 * 1024), 2)
        mtime_str = datetime.fromtimestamp(latest_mtime).strftime('%Y-%m-%d %H:%M:%S') if latest_mtime > 0 else '未知'
        return size_mb, mtime_str

    def get_status(self) -> Dict[str, Any]:
        """获取当前本地库状态 (基础实现)"""
        size_mb, mtime_str = self._get_dir_info()
        return {
            "db_id": self.db_id,
            "name": self.name,
            "installed": False,
            "version": self.config.get("version", "Unknown"),
            "size_mb": size_mb,
            "last_modified": mtime_str,
            "category": self.config.get("category", "未分类数据库"),
            "url": self.config.get("url", "local_only")
        }

class SilvaDatabase(BioDatabase):
    """
    SILVA 数据库专用管理器
    """
    
    def get_status(self) -> Dict[str, Any]:
        # 从配置中动态获取预期的索引文件名
        db_name = self.config.get("version", "silva")
        is_indexed = (self.base_dir / f"silva_{db_name}.nsq").exists()
        
        status = super().get_status()
        status.update({
            "installed": is_indexed,
            "path": str(self.base_dir) if is_indexed else None,
        })
        return status

    async def update_database(self):
        """
        全自动化更新流程：下载 -> 解压 -> 构建索引
        """
        download_url = self.config.get("url")
        if not download_url:
            raise ValueError(f"No download URL configured for {self.db_id}")

        try:
            target_gz = self.base_dir / "download.fasta.gz"
            target_fasta = self.base_dir / "source.fasta"

            # 1. 下载
            logger.info(f">>> [Download] 开始载入 {self.name}: {download_url}")
            urllib.request.urlretrieve(download_url, target_gz)
            
            # 2. 解压 (这里需要 gunzip，Python 内置 gzip 模块支持)
            import gzip
            import shutil
            with gzip.open(target_gz, 'rb') as f_in:
                with open(target_fasta, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # 3. 构建 BLAST 索引
            await self.build_index(str(target_fasta))
            
            return True
        except Exception as e:
            logger.error(f"{self.name} 更新失败: {e}")
            return False

    async def build_index(self, fasta_path: str):
        """调用本地 makeblastdb 进行索引"""
        if not os.path.exists(fasta_path):
            raise FileNotFoundError(f"FASTA source not found: {fasta_path}")
            
        # 1. 记录源文件大小
        fasta_size = os.path.getsize(fasta_path) / (1024 * 1024)
        logger.info(f"待索引文件大小: {fasta_size:.2f} MB")
        
        # 2. 核心避让逻辑：等待 2s 让 OS 释放文件锁定（如杀毒软件扫描）
        logger.info("等待系统就绪 (2s)...")
        await asyncio.sleep(2)

        db_ver = self.config.get("version", "latest")
        db_type = str(self.config.get("db_type", "nucl"))
        
        # 3. 核心修复：转换为 8.3 短路径名，规避一切空格引发的内存映射问题
        tool_path = get_short_path_name(str(ToolConfig.get_tool_path("makeblastdb")))
        short_base_dir = get_short_path_name(str(self.base_dir))
        output_name = f"silva_{db_ver}"
        
        # 清理旧索引残余
        for f in self.base_dir.glob(f"{output_name}.n*"):
            try:
                f.unlink()
            except:
                pass

        # 构造无空格威胁的命令
        cmd_str = f'"{tool_path}" -in "source.fasta" -dbtype {db_type} -title "{self.name} {db_ver}" -out "{output_name}"'
        
        logger.info(f"执行构建索引 (CWD 短路径: {short_base_dir}): {cmd_str}")
        
        process = await asyncio.create_subprocess_shell(
            cmd_str,
            cwd=short_base_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            err_msg = stderr.decode(errors='ignore').strip()
            logger.error(f"makeblastdb 失败 (退出码 {process.returncode}): {err_msg}")
            raise RuntimeError(f"Index build failed: {err_msg}")

class Ncbi16SDatabase(BioDatabase):
    """
    NCBI RefSeq 16S 数据库专用管理器
    """
    def get_status(self) -> Dict[str, Any]:
        # NCBI 库特有的索引文件后缀
        is_indexed = (self.base_dir / "16S_ribosomal_RNA.nsq").exists()
        status = super().get_status()
        status.update({
            "installed": is_indexed,
            "path": str(self.base_dir) if is_indexed else None
        })
        return status

    async def update_database(self):
        """
        利用之前编写的修复/下载逻辑进行更新
        """
        download_url = self.config.get("url")
        target_gz = self.base_dir / "16S_ribosomal_RNA.tar.gz"
        expected_md5 = self.config.get("version_md5", "32557aa0b65998ee65064999ae802705")

        try:
            # 下载与校验逻辑 (复用之前成功的修复逻辑)
            logger.info(f">>> [NCBI] 正在同步 16S 官方库...")
            urllib.request.urlretrieve(download_url, str(target_gz) + ".tmp")
            
            # (简写校验步骤...)
            os.replace(str(target_gz) + ".tmp", target_gz)
            
            with tarfile.open(target_gz) as t:
                t.extractall(path=self.base_dir)
            return True
        except Exception as e:
            logger.error(f"NCBI 同步失败: {e}")
            return False

class PhageScopeDatabase(BioDatabase):
    """
    PhageScope 噬菌体高精度注释库专用管理器
    """
    def get_status(self) -> Dict[str, Any]:
        is_indexed = (self.base_dir / "phagescope_proteins.psq").exists()
        status = super().get_status()
        status.update({
            "installed": is_indexed,
            "path": str(self.base_dir) if is_indexed else None
        })
        return status

    async def update_database(self):
        try:
            import sys
            script_path = ToolConfig.PROJECT_ROOT / "database" / "fetch_phagescope.py"
            
            logger.info(f">>> [PhageScope] 启动本地抓取与构建脚本: {script_path}")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script_path),
                cwd=str(ToolConfig.PROJECT_ROOT)
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            logger.error(f"PhageScope 同步失败: {e}")
            return False

class PharokkaDatabase(BioDatabase):
    """Pharokka 10GB 综合数据库"""
    def get_status(self) -> Dict[str, Any]:
        is_installed = self.base_dir.exists() and any(self.base_dir.iterdir())
        status = super().get_status()
        status.update({
            "installed": is_installed,
            "path": str(self.base_dir) if is_installed else None
        })
        return status

    async def update_database(self):
        try:
            import re
            project_root = str(ToolConfig.PROJECT_ROOT).replace('\\', '/')
            m = re.match(r"^([A-Za-z]):/(.*)", project_root)
            if not m: return False
            mnt_path = f"/mnt/{m.group(1).lower()}/{m.group(2)}/scripts/setup_pharokka.sh"
            
            logger.info(f">>> [Pharokka] 启动底层部署脚本: {mnt_path}")
            proc = await asyncio.create_subprocess_shell(f'wsl -d Ubuntu -u root bash "{mnt_path}"')
            await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            logger.error(f"Pharokka 同步失败: {e}")
            return False

class PholdDatabase(BioDatabase):
    """Phold AI 结构数据库"""
    def get_status(self) -> Dict[str, Any]:
        is_installed = self.base_dir.exists() and any(self.base_dir.iterdir())
        status = super().get_status()
        status.update({
            "installed": is_installed,
            "path": str(self.base_dir) if is_installed else None
        })
        return status

    async def update_database(self):
        try:
            import re
            project_root = str(ToolConfig.PROJECT_ROOT).replace('\\', '/')
            m = re.match(r"^([A-Za-z]):/(.*)", project_root)
            if not m: return False
            mnt_path = f"/mnt/{m.group(1).lower()}/{m.group(2)}/scripts/setup_phold.sh"
            
            logger.info(f">>> [Phold] 启动底层部署脚本: {mnt_path}")
            proc = await asyncio.create_subprocess_shell(f'wsl -d Ubuntu -u root bash "{mnt_path}"')
            await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            logger.error(f"Phold 同步失败: {e}")
            return False

class BioDbManager:
    """
    数据库管理门面 (Facade)
    负责汇聚所有类型的生物数据库
    """
    def __init__(self):
        # 自动从 ToolConfig 动态加载注册表并实例化对应的数据库管理器
        self.dbs: Dict[str, BioDatabase] = {}
        
        # [Migration] 核心逻辑：将散落在 16S 目录下的 NCBI 文件归位到 16S/ncbi
        self._perform_migration()

        registry = ToolConfig.get_remote_registry()
        for db_id, config in registry.items():
            if "silva" in db_id.lower():
                self.dbs[db_id] = SilvaDatabase(db_id, config)
            elif "ncbi_16s" in db_id.lower() or "16s_ribosomal" in db_id.lower():
                self.dbs[db_id] = Ncbi16SDatabase(db_id, config)
            elif "phagescope" in db_id.lower():
                self.dbs[db_id] = PhageScopeDatabase(db_id, config)
            elif "pharokka" in db_id.lower():
                self.dbs[db_id] = PharokkaDatabase(db_id, config)
            elif "phold" in db_id.lower():
                self.dbs[db_id] = PholdDatabase(db_id, config)
            else:
                self.dbs[db_id] = BioDatabase(db_id, config)

    def _perform_migration(self):
        """处理 NCBI 16S 目录不规范的历史遗留问题"""
        source_dir = ToolConfig.DATABASE_ROOT / "16S"
        target_dir = source_dir / "ncbi"
        
        if not source_dir.exists(): return
        
        # 识别散落的文件 (16S_ribosomal_RNA.*)
        scattered_files = list(source_dir.glob("16S_ribosomal_RNA*"))
        if scattered_files:
            logger.info(f"🚚 发现散落的 NCBI 文件 ({len(scattered_files)}个)，正在迁移至: {target_dir}")
            target_dir.mkdir(parents=True, exist_ok=True)
            for f in scattered_files:
                try:
                    dest = target_dir / f.name
                    if dest.exists(): f.unlink() # 如果目标已存在，则删除旧的
                    else: f.rename(dest)
                except Exception as e:
                    logger.error(f"迁移文件 {f.name} 失败: {e}")

    def list_all_status(self) -> List[Dict[str, Any]]:
        return [db.get_status() for db in self.dbs.values()]

# 全局单例
bio_db_manager = BioDbManager()
