
import os
import logging
from pathlib import Path
from typing import Optional
from ..engine.runner import CommandRunner

class NCBIDownloader:
    """
    NCBI 数据中心交互器 (SRP: 负责云端参考序列的检索与物理下载)
    """
    def __init__(self, project_root: Path, logger: Optional[logging.Logger] = None):
        self.project_root = project_root
        self.logger = logger or logging.getLogger("Assembly.NCBI")
        self.host_base_dir = self.project_root / "database" / "hosts"
        self.host_base_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_reference_genome(self, species_name: str) -> Optional[str]:
        """
        根据物种名下载参考基因组，返回 Fasta 文件磁盘路径
        """
        safe_name = species_name.replace(" ", "_").lower()
        target_dir = self.host_base_dir / safe_name
        target_dir.mkdir(parents=True, exist_ok=True)
        
        zip_file = target_dir / "genome.zip"
        
        # 🔗 0. 缓存检查：如果目录中已存在提取好的 Fasta，直接返回
        existing_fasta = self._find_fasta_in_bundle(target_dir)
        if existing_fasta:
            self.logger.info(f"✨ 发现本地已缓存的 {species_name} 参考基因组: {Path(existing_fasta).name}")
            return existing_fasta
            
        # 如果 zip 文件存在但没有对应的 fna，说明上次下载可能中断或损坏，尝试删除重下
        if zip_file.exists():
            self.logger.warning(f"检测到可能损坏的基因组安装包，正在清理并重新尝试下载...")
            zip_file.unlink()
        
        # 1. 启动专用任务执行器
        runner = CommandRunner(f"NCBI-{safe_name}", self.logger, is_wsl=True)
        
        # 🔗 1.1 环境预检：检查 datasets 命令行工具是否存在
        check_datasets = await runner.run_command(["datasets", "--version"])
        if check_datasets != 0:
            self.logger.warning("⚠️ WSL 环境缺失 datasets 工具，正在尝试本地部署...")

            # 💡 优先方案：检查用户是否手动下载并放置在了 tools 目录下
            local_tool = self.project_root / "tools" / "datasets"
            if local_tool.exists():
                self.logger.info(f"🚀 发现本地已下载的工具: {local_tool}")
                from ..env.wsl_manager import WSLManager
                wsl_local_path = WSLManager.to_wsl_path(str(local_tool))
                
                # 直接搬运到 WSL 系统路径
                deploy_cmd = [
                    "cp", wsl_local_path, "/usr/local/bin/datasets", "&&",
                    "chmod", "+x", "/usr/local/bin/datasets"
                ]
                if await runner.run_command(deploy_cmd, is_shell=True) == 0:
                    self.logger.info("✅ 本地工具已成功同步至 WSL 运行环境")
                else:
                    self.logger.error("❌ 本地工具同步失败，请检查文件权限。")
                    return None
            else:
                # 💡 备选方案：积极重试下载 (规避 SSL 错误 35 和 UNEXPECTED_EOF)
                self.logger.warning("未发现本地工具，进入自动下载流程...")
                # ... (此处保留之前的下载逻辑，以防后续其他环境需要)
                tmp_zip_windows = self.project_root / "temp_ncbi_datasets.zip"
                mirrors = [
                    "https://ghp.ci/https://github.com/ncbi/datasets/releases/latest/download/linux-amd64.cli.package.zip",
                    "https://mirror.ghproxy.com/https://github.com/ncbi/datasets/releases/latest/download/linux-amd64.cli.package.zip",
                    "https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/linux-amd64/datasets"
                ]
                
                download_success = False
                for url in mirrors:
                    try:
                        self.logger.info(f"正在尝试下载源: {url}")
                        import urllib.request
                        import ssl
                        context = ssl._create_unverified_context()
                        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
                        opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
                        urllib.request.install_opener(opener)
                        
                        temp_target = str(tmp_zip_windows) if ".zip" in url else str(self.project_root / "temp_datasets_bin")
                        urllib.request.urlretrieve(url, temp_target)
                        
                        if ".zip" not in url:
                            bin_path = self.project_root / "temp_datasets_bin"
                            wsl_bin = WSLManager.to_wsl_path(str(bin_path))
                            await runner.run_command(["mv", wsl_bin, "/usr/local/bin/datasets"], is_shell=True)
                            await runner.run_command(["chmod", "+x", "/usr/local/bin/datasets"], is_shell=True)
                            download_success = "binary"
                        else:
                            download_success = "zip"
                        break
                    except Exception: continue

                if not download_success:
                    self.logger.error("❌ 工具缺失且下载失败，请确保 datasets 已放置在 tools/ 目录下。")
                    return None

                # 💡 如果是 ZIP，转换路径并让 WSL 进行解压部署
                from ..env.wsl_manager import WSLManager
                if download_success == "zip":
                    wsl_tmp_zip = WSLManager.to_wsl_path(str(tmp_zip_windows))
                    install_cmd = [
                        "unzip", "-o", wsl_tmp_zip, "-d", "/tmp/ncbi_cli",
                        "&&", "mv", "/tmp/ncbi_cli/datasets", "/usr/local/bin/datasets",
                        "&&", "chmod", "+x", "/usr/local/bin/datasets",
                        "&&", "rm", "-rf", "/tmp/ncbi_cli"
                    ]
                    await runner.run_command(install_cmd, is_shell=True)
                
                if tmp_zip_windows.exists(): tmp_zip_windows.unlink()

            # 🔗 验证结果
            self.logger.info("正在验证工具兼容性...")
            
            # 1. 架构校验 (必须是 Linux ELF)
            check_file = await runner.run_command(["file", "/usr/local/bin/datasets", "|", "grep", "-q", "ELF"], is_shell=True)
            if check_file != 0:
                self.logger.error("❌ 部署失败：该文件不是有效的 Linux 二进制文件。")
                self.logger.error("💡 提示：您可能下载了 Windows 版本的 datasets (.exe)，请确保下载的是 'linux-amd64' 版本。")
                await runner.run_command(["rm", "-f", "/usr/local/bin/datasets"])
                return None

            # 2. 功能校验 (尝试运行)
            check_run = await runner.run_command(["datasets", "--version"])
            if check_run != 0:
                self.logger.error("❌ 部署失败：工具无法在 WSL 中执行（Exec format error）。")
                self.logger.error("💡 提示：这通常是因为二进制架构不匹配。正在清理...")
                await runner.run_command(["rm", "-f", "/usr/local/bin/datasets"])
                return None

            self.logger.info("✅ 'datasets' 工具验证通过，版本信息已就绪。")
            self.logger.info("✅ 环境自愈完成")

        # 2. 调用 Datasets 下载 Fasta
        self.logger.info(f"正在向 NCBI 请求 {species_name} 的代表性参考序列...")
        cmd = [
            "datasets", "download", "genome", "taxon", species_name,
            "--reference", "--include", "genome", "--filename", str(zip_file)
        ]
        
        ret = await runner.run_command(cmd)
        if ret != 0 or not zip_file.exists():
            self.logger.error(f"NCBI 下载失败，异常码: {ret}")
            return None

        # 3. 物理提取
        self.logger.info(f"下载成功，正在解压提取 Fasta 数据...")
        
        # 确保 unzip 存在
        check_unzip = await runner.run_command(["unzip", "-v"])
        if check_unzip != 0:
            self.logger.warning("⚠️ WSL 环境中未找到 'unzip' 工具，正在自动部署...")
            if await runner.run_command(["apt-get", "update", "&&", "apt-get", "install", "-y", "unzip"], is_shell=True) != 0:
                self.logger.error("❌ 'unzip' 安装失败，无法完成数据解压。")
                return None
            self.logger.info("✅ 'unzip' 工具部署成功")
            
        unzip_cmd = ["unzip", "-o", str(zip_file), "-d", str(target_dir)]
        await runner.run_command(unzip_cmd)
        
        return self._find_fasta_in_bundle(target_dir)

    def _find_fasta_in_bundle(self, bundle_dir: Path) -> Optional[str]:
        """
        在解压后的 NCBI 数据包中寻找最符合条件的 Fasta 文件
        """
        # 匹配模式：ncbi_dataset/data/GCF_xxx/*.fna
        patterns = ["**/ncbi_dataset/data/GCF_*/*.fna", "**/*.fna", "**/*.fasta"]
        for pattern in patterns:
            paths = list(bundle_dir.glob(pattern))
            if paths:
                return str(paths[0].resolve())
        return None
