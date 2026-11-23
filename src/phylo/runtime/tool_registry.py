# -*- coding: utf-8 -*-
"""
ToolRegistry - 动态生物信息计算工具探测与版本发现
零硬编码绝对路径，支持本地目录与 WSL 动态扫描。
"""
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional

from ..models.schemas import ToolDescriptor

logger = logging.getLogger("phylo.tool_registry")


def get_project_root() -> Path:
    """相对路径解析项目根目录。"""
    return Path(__file__).resolve().parent.parent.parent.parent


class ToolRegistry:
    """本地与 WSL 计算工具统一注册探测中心（单例）。"""

    _instance: Optional["ToolRegistry"] = None
    _lock = threading.Lock()

    NATIVE_CANDIDATE_NAMES: Dict[str, List[str]] = {
        "fasttree": ["FastTree.exe", "fasttree.exe", "FastTree", "fasttree"],
        "mafft": ["mafft.bat", "mafft"],
        "muscle": ["muscle.exe", "muscle"],
        "iqtree": ["iqtree3.exe", "iqtree2.exe", "iqtree.exe", "iqtree3", "iqtree2", "iqtree"],
        "mrbayes": ["mb.exe", "mb"],
        "mash": ["mash.exe", "mash"],
        "clustalo": ["clustalo.exe", "clustalo"],
        "blastn": ["blastn.exe", "blastn"],
        "blastp": ["blastp.exe", "blastp"],
    }

    WSL_CANDIDATE_NAMES: Dict[str, List[str]] = {
        "mash": ["mash"],
        "mafft": ["mafft"],
        "muscle": ["muscle"],
        "clustalo": ["clustalo"],
        "fasttree": ["FastTree", "fasttree", "fasttreeMP"],
        "iqtree": ["iqtree3", "iqtree2", "iqtree"],
        "mrbayes": ["mb"],
        "clipkit": ["clipkit"],
        "fastani": ["fastANI"],
        "skani": ["skani"],
        "drep": ["dRep"],
        "treemmer": ["treemmer", "Treemmer_v0.3.py"],
        "blastn": ["blastn"],
        "blastp": ["blastp"],
        "diamond": ["diamond"],
        "mmseqs": ["mmseqs"],
        "prodigal-gv": ["prodigal-gv", "prodigal"],
        "hmmsearch": ["hmmsearch"],
        "hmmfetch": ["hmmfetch"],
        "checkv": ["checkv"],
        "pharokka": ["pharokka.py"],
    }

    def __new__(cls) -> "ToolRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._probe_lock = threading.Lock()
        self._wsl_available: bool = False
        self._wsl_distro: str = ""
        self._tools: Dict[str, ToolDescriptor] = {}
        self.refresh()

    @property
    def wsl_available(self) -> bool:
        return self._wsl_available

    @property
    def wsl_distro(self) -> str:
        return self._wsl_distro

    def get_all(self) -> Dict[str, ToolDescriptor]:
        return dict(self._tools)

    def get(self, name: str) -> ToolDescriptor:
        return self._tools.get(name, ToolDescriptor(name=name, available=False))

    def _local_search_dirs(self) -> List[Path]:
        root = get_project_root()
        dirs: List[Path] = [
            root / "src" / "workbench" / "bin",
            root / "tools" / "ncbi_dist" / "bin" / "tree-tools",
        ]
        vendor_root = root / "vendor"
        if vendor_root.is_dir():
            for sub in sorted(vendor_root.iterdir()):
                if sub.is_dir():
                    dirs.append(sub)
                    if (sub / "bin").is_dir():
                        dirs.append(sub / "bin")
        iq3_root = root / "tools" / "iqtree3_win"
        if iq3_root.is_dir():
            for sub in sorted(iq3_root.iterdir()):
                if sub.is_dir() and (sub / "bin").is_dir():
                    dirs.append(sub / "bin")
        return [d for d in dirs if d.is_dir()]

    def _find_native_tool(self, tool_key: str) -> Optional[Path]:
        names = self.NATIVE_CANDIDATE_NAMES.get(tool_key, [tool_key])
        for directory in self._local_search_dirs():
            for fname in names:
                candidate = directory / fname
                if candidate.is_file():
                    return candidate.resolve()
        for fname in names:
            found = shutil.which(fname)
            if found:
                return Path(found).resolve()
        return None

    def _probe_wsl_environment(self) -> Dict[str, ToolDescriptor]:
        """单次启动 WSL 执行综合探测，减少冷启动开销。"""
        discovered: Dict[str, ToolDescriptor] = {}
        try:
            from src.assembly.env.wsl_manager import WSLManager

            if not WSLManager.is_available():
                self._wsl_available = False
                self._wsl_distro = ""
                return discovered
            distro = WSLManager.get_best_distro()
            self._wsl_available = True
            self._wsl_distro = distro
            WSLManager.ensure_project_link()
        except Exception as exc:
            logger.debug(f"WSL manager probe failed: {exc}")
            self._wsl_available = False
            self._wsl_distro = ""
            return discovered

        # 动态扫描 PATH、用户 miniforge3/envs/phylo_phage 与 /opt 嵌套 bin 目录，禁止写死版本号路径
        probe_script = r"""
export PATH="$HOME/miniforge3/envs/phylo_phage/bin:/home/administrator/miniforge3/envs/phylo_phage/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
find_tool() {
  for cand in "$@"; do
    p=$(command -v "$cand" 2>/dev/null || true)
    if [ -n "$p" ] && [ -x "$p" ]; then
      echo "$p"
      return 0
    fi
    for optp in /opt/*/"bin/$cand" /opt/*/*/"bin/$cand" /opt/miniconda3/envs/*/bin/"$cand" /home/*/miniforge3/envs/*/bin/"$cand"; do
      if [ -x "$optp" ]; then
        echo "$optp"
        return 0
      fi
    done
  done
  return 1
}
for key in mash mafft muscle clustalo fasttree iqtree mrbayes clipkit fastani skani drep treemmer blastn blastp diamond mmseqs prodigal-gv hmmsearch hmmfetch checkv pharokka; do
  case "$key" in
    mash) p=$(find_tool mash) ;;
    mafft) p=$(find_tool mafft) ;;
    muscle) p=$(find_tool muscle) ;;
    clustalo) p=$(find_tool clustalo) ;;
    fasttree) p=$(find_tool FastTree fasttree fasttreeMP) ;;
    iqtree) p=$(find_tool iqtree3 iqtree2 iqtree) ;;
    mrbayes) p=$(find_tool mb) ;;
    clipkit) p=$(find_tool clipkit) ;;
    fastani) p=$(find_tool fastANI) ;;
    skani) p=$(find_tool skani) ;;
    drep) p=$(find_tool dRep) ;;
    treemmer) p=$(find_tool treemmer Treemmer_v0.3.py) ;;
    blastn) p=$(find_tool blastn) ;;
    blastp) p=$(find_tool blastp) ;;
    diamond) p=$(find_tool diamond) ;;
    mmseqs) p=$(find_tool mmseqs) ;;
    prodigal-gv) p=$(find_tool prodigal-gv prodigal) ;;
    hmmsearch) p=$(find_tool hmmsearch) ;;
    hmmfetch) p=$(find_tool hmmfetch) ;;
    checkv) p=$(find_tool checkv) ;;
    pharokka) p=$(find_tool pharokka.py) ;;
  esac
  if [ -n "$p" ]; then
    ver=""
    case "$key" in
      mash) ver=$("$p" --version 2>&1 | head -n 1) ;;
      mafft) ver=$("$p" --version 2>&1 | head -n 1) ;;
      muscle) ver=$("$p" -version 2>&1 | head -n 1) ;;
      clustalo) ver=$("$p" --version 2>&1 | head -n 1) ;;
      fasttree) ver=$("$p" -help 2>&1 | head -n 1) ;;
      iqtree) ver=$("$p" --version 2>&1 | head -n 1) ;;
      mrbayes) ver="MrBayes (WSL)" ;;
      clipkit) ver=$("$p" -v 2>&1 | head -n 1) ;;
      fastani) ver=$("$p" --version 2>&1 | head -n 1) ;;
      skani) ver=$("$p" --version 2>&1 | head -n 1) ;;
      drep) ver="dRep (WSL phylo_phage)" ;;
      treemmer) ver="Treemmer (WSL)" ;;
      blastn) ver=$("$p" -version 2>&1 | head -n 1) ;;
      blastp) ver=$("$p" -version 2>&1 | head -n 1) ;;
      diamond) ver=$("$p" version 2>&1 | head -n 1) ;;
      mmseqs) ver=$("$p" version 2>&1 | head -n 1) ;;
      prodigal-gv) ver=$("$p" -v 2>&1 | head -n 1) ;;
      hmmsearch) ver=$("$p" -h 2>&1 | grep -m1 HMMER || echo HMMER) ;;
      hmmfetch) ver="hmmfetch (HMMER)" ;;
      checkv) ver="CheckV (WSL)" ;;
      pharokka) ver="Pharokka (WSL)" ;;
    esac
    echo "FOUND|$key|$p|$ver"
  fi
done
exit 0
"""
        try:
            res = subprocess.run(
                ["wsl", "-d", self._wsl_distro, "-u", "root", "bash", "-s"],
                input=probe_script.replace("\r\n", "\n").encode("utf-8"),
                capture_output=True,
                timeout=15,
            )
            stdout_text = (res.stdout or b"").decode("utf-8", errors="replace")
            if res.returncode == 0 or stdout_text:
                for line in stdout_text.splitlines():
                    if not line.startswith("FOUND|"):
                        continue
                    parts = line.split("|", 3)
                    if len(parts) < 3:
                        continue
                    key, tool_path = parts[1].strip(), parts[2].strip()
                    ver = parts[3].strip() if len(parts) > 3 else ""
                    discovered[key] = ToolDescriptor(
                        name=key,
                        available=True,
                        runtime="wsl",
                        path=tool_path,
                        version=ver[:120],
                        notes=f"WSL ({self._wsl_distro})",
                    )
        except Exception as exc:
            logger.warning(f"WSL tool discovery failed: {exc}")

        return discovered

    def refresh(self) -> Dict[str, ToolDescriptor]:
        """重新扫描并更新所有工具状态。"""
        with self._probe_lock:
            wsl_tools = self._probe_wsl_environment()
            all_keys = [
                "mash",
                "mafft",
                "muscle",
                "clustalo",
                "fasttree",
                "iqtree",
                "mrbayes",
                "clipkit",
                "fastani",
                "skani",
                "drep",
                "treemmer",
                "blastn",
                "blastp",
                "diamond",
                "mmseqs",
                "prodigal-gv",
                "hmmsearch",
                "hmmfetch",
                "checkv",
                "pharokka",
            ]
            result: Dict[str, ToolDescriptor] = {}

            for key in all_keys:
                native_path = self._find_native_tool(key)
                wsl_desc = wsl_tools.get(key)

                # 优先策略：
                # - WSL Linux 多核工具与 phylo_phage 科研套件优先 WSL；
                # - fasttree / mrbayes 优先本地原生再回退 WSL。
                if key not in ("fasttree", "mrbayes"):
                    if wsl_desc and wsl_desc.available:
                        result[key] = wsl_desc
                        continue
                    if native_path:
                        result[key] = ToolDescriptor(
                            name=key,
                            available=True,
                            runtime="native",
                            path=str(native_path),
                            version="local-binary",
                            notes="Windows native fallback",
                        )
                        continue
                else:
                    if native_path:
                        result[key] = ToolDescriptor(
                            name=key,
                            available=True,
                            runtime="native",
                            path=str(native_path),
                            version="local-binary",
                            notes="Windows native",
                        )
                        continue
                    if wsl_desc and wsl_desc.available:
                        result[key] = wsl_desc
                        continue

                result[key] = ToolDescriptor(
                    name=key,
                    available=False,
                    runtime="none",
                    path="",
                    version="",
                    notes="未检测到可用可执行文件",
                )

            self._tools = result
            return dict(self._tools)


def get_tool_registry() -> ToolRegistry:
    return ToolRegistry()
