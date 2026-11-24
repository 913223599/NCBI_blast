# -*- coding: utf-8 -*-
"""
ItolBatchClient - 方案 B：免费官方 iTOL 上传打包与批量拉取出图客户端
说明：
1. iTOL 官方 batch_uploader.cgi 需要付费订阅 API Key，因此免费用户通过本地一键打包 ZIP
   （含 tree.nwk、5 套注释模板及中文操作指南）并直达 upload.cgi 拖入上传；
2. 用户粘贴上传后得到的树 URL 或 Tree ID，利用官方免费开放的 batch_downloader.cgi
   全自动导出高分辨率 PDF / SVG / PNG / EPS 并落盘归档。
"""
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from ..models.errors import InvalidInputError, PhyloError
from ..models.schemas import (
    ItolDisplayModeType,
    ItolExportFormatType,
    ItolPullRequest,
    LabelFormatType,
)
from .label_formatter import enrich_node_metadata, format_leaf_label

ITOL_UPLOAD_PAGE_URL = "https://itol.embl.de/upload.cgi"
ITOL_BATCH_DOWNLOADER_URL = "https://itol.embl.de/batch_downloader.cgi"

_TREE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_DISPLAY_MODE_MAP: Dict[ItolDisplayModeType, str] = {
    "rectangular": "1",
    "circular": "2",
    "unrooted": "3",
}


class ItolBatchClient:
    """免费官方 iTOL 联动：上传准备包生成器 + batch_downloader.cgi 自动拉图器。"""

    @staticmethod
    def extract_tree_id(tree_id_or_url: str) -> str:
        """从纯 Tree ID 或完整 iTOL URL（如 https://itol.embl.de/tree/123456?foo=1）中提取并校验 Tree ID。"""
        raw = (tree_id_or_url or "").strip()
        if not raw:
            raise InvalidInputError("请输入有效的 iTOL 树 URL 或 Tree ID。")

        candidate = raw
        if "://" in raw or "itol.embl.de" in raw.lower():
            parsed = urlparse(raw if "://" in raw else f"https://{raw}")
            parts = [seg for seg in parsed.path.split("/") if seg]
            if not parts:
                raise InvalidInputError(f"无法从 URL 解析 iTOL Tree ID: {raw}")
            if "tree" in parts:
                idx = parts.index("tree")
                candidate = parts[idx + 1] if idx + 1 < len(parts) else ""
            else:
                candidate = parts[-1]
        else:
            candidate = raw.split("?")[0].split("#")[0].strip("/")

        if not _TREE_ID_RE.match(candidate):
            raise InvalidInputError(
                f"iTOL Tree ID 格式无效: '{candidate}'（仅支持 4-64 位字母、数字、下划线或短横线）。"
            )
        return candidate

    @staticmethod
    def sanitize_newick_for_itol(newick: str) -> Tuple[str, Dict[str, str]]:
        """
        生成 100% 兼容官网 iTOL 的纯 ASCII 标准 Newick：
        1. 将含非 ASCII（如中文）或 Newick 保留字符/斜杠的叶名映射为 Phage_01.. 安全纯 ASCII 键；
        2. 将 IQ-TREE 双支持值（如 99.7/100）规范化为 iTOL 原生可识别的纯数值 UFBoot（100）。
        返回: (ascii_newick, orig_to_ascii_map)
        """
        from ..pipeline.postprocess import _parse_dual_support, parse_newick, to_newick

        root = parse_newick(newick)
        existing_ascii = set()
        stack = [root]
        while stack:
            cur = stack.pop()
            if cur.is_leaf and cur.name.isascii() and not re.search(r"[():,;\[\]'\s/]", cur.name):
                existing_ascii.add(cur.name)
            stack.extend(cur.children)

        orig_to_ascii: Dict[str, str] = {}
        counter = 1

        def _walk(node) -> None:
            nonlocal counter
            if node.is_leaf:
                name = node.name or "Unknown"
                needs_map = (not name.isascii()) or bool(re.search(r"[():,;\[\]'\s/]", name))
                if needs_map:
                    if name not in orig_to_ascii:
                        while True:
                            cand = f"Phage_{counter:02d}"
                            counter += 1
                            if cand not in existing_ascii:
                                existing_ascii.add(cand)
                                orig_to_ascii[name] = cand
                                break
                    node.name = orig_to_ascii[name]
            else:
                if node.name:
                    _, uf = _parse_dual_support(node.name)
                    if uf is not None:
                        node.name = f"{uf:.0f}" if abs(uf - round(uf)) < 0.05 else f"{uf:.1f}"
                    elif not node.name.isascii() or "/" in node.name:
                        node.name = ""
            for ch in node.children:
                _walk(ch)

        _walk(root)
        ascii_nwk = to_newick(root).strip() + "\n"
        return ascii_nwk, orig_to_ascii

    @staticmethod
    def build_itol_upload_bundle(
        job_dir: Path,
        job_id: str,
        newick: str,
        itol_dir: Path,
        node_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        label_format: LabelFormatType = "name_acc",
    ) -> Path:
        """打包纯 ASCII tree_itol_ascii.nwk、同步 ID 后的 iTOL 注释模板、实际名称展示标签及操作指引。"""
        from ..pipeline.postprocess import parse_newick

        job_dir.mkdir(parents=True, exist_ok=True)
        ascii_nwk, orig_to_ascii = ItolBatchClient.sanitize_newick_for_itol(newick)

        # 提取全部叶节点原名以补全历史任务可能缺失的 description，并组装统一的 iTOL LABELS 展示映射
        root_parsed = parse_newick(newick)
        leaf_orig_names = []
        stack = [root_parsed]
        while stack:
            cur = stack.pop()
            if cur.is_leaf and cur.name:
                leaf_orig_names.append(cur.name)
            stack.extend(cur.children)

        enriched_meta = enrich_node_metadata(node_metadata, leaf_orig_names)
        label_display_entries: Dict[str, str] = {}
        for orig_name in leaf_orig_names:
            ascii_key = orig_to_ascii.get(orig_name, orig_name)
            disp = format_leaf_label(orig_name, enriched_meta.get(orig_name), label_format)
            if disp and disp != ascii_key:
                label_display_entries[ascii_key] = disp

        itol_nwk_path = job_dir / "tree_itol_ascii.nwk"
        itol_nwk_path.write_text(ascii_nwk, encoding="ascii", errors="ignore", newline="\n")

        readme_lines = [
            f"PhyloCore iTOL 免费官网联动操作指引 (Task: {job_id})",
            "=" * 58,
            "[重要提醒] 请务必先解压本 ZIP 压缩包！切勿把 .zip 文件直接拖入 iTOL 的 Tree file 上传框！",
            "",
            "第 1 步：打开浏览器访问 iTOL 官方上传页：",
            f"   {ITOL_UPLOAD_PAGE_URL}",
            "第 2 步：在页面中选择解压后的纯文本树文件 tree_itol_ascii.nwk 上传（或直接复制其中内容粘贴到 Tree text）。",
            "   (已自动去除中文字符及斜杠双支持值，保证 100% 通过 iTOL 初始化校验)",
            "第 3 步：进入进化树界面后，将解压目录 itol/ 下的全部 .txt 注释模板文件拖入页面画布：",
            "   - itol_branch_colors.txt      (分支着色：Query / Outgroup / ICTV 属)",
            "   - itol_label_colors.txt       (标签字体与 Query 高亮底色)",
            "   - itol_strip_taxonomy.txt     (外圈 ICTV 分类色带与图例)",
            "   - itol_bars_genome_length.txt (外圈基因组长度条带)",
            "   - itol_bars_gc.txt            (外圈 GC% 条带)",
        ]
        if label_display_entries:
            readme_lines.append(
                "   - itol_labels_display.txt     (自动将登录号/ASCII 键展示为 `实际名称 (登录号)` 及中文原名)"
            )
        if orig_to_ascii:
            readme_lines.extend(["", "本次已自动 ASCII 映射的叶节点名称："])
            for orig_name, asc_name in orig_to_ascii.items():
                readme_lines.append(f"   {asc_name} -> {orig_name}")

        readme_lines.extend(
            [
                "",
                "第 4 步：复制浏览器地址栏 URL 或末尾 Tree ID，粘贴回工作台即可自动拉回 PDF / SVG / 高清 PNG。",
                "",
            ]
        )
        readme_path = job_dir / "README_iTOL_Upload.txt"
        readme_path.write_text("\n".join(readme_lines), encoding="utf-8", newline="\n")

        bundle_path = job_dir / f"itol_upload_{job_id}.zip"
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(itol_nwk_path, arcname="tree_itol_ascii.nwk")
            zf.write(readme_path, arcname="README_iTOL_Upload.txt")
            if itol_dir.is_dir():
                for fp in sorted(itol_dir.iterdir()):
                    if not fp.is_file() or fp.suffix.lower() != ".txt":
                        continue
                    # itol_labels_display.txt 由下方统一合并版本生成，防止重复写入
                    if fp.name == "itol_labels_display.txt":
                        continue
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    if orig_to_ascii:
                        rewritten_lines = []
                        for line in content.splitlines():
                            if "\t" in line:
                                head, rest = line.split("\t", 1)
                                if head in orig_to_ascii:
                                    line = f"{orig_to_ascii[head]}\t{rest}"
                            rewritten_lines.append(line)
                        content = "\n".join(rewritten_lines) + "\n"
                    zf.writestr(f"itol/{fp.name}", content.encode("utf-8"))

            if label_display_entries:
                label_lines = ["LABELS", "SEPARATOR TAB", "DATA"]
                for asc_key, disp_val in label_display_entries.items():
                    label_lines.append(f"{asc_key}\t{disp_val}")
                zf.writestr(
                    "itol/itol_labels_display.txt",
                    ("\n".join(label_lines) + "\n").encode("utf-8"),
                )
        return bundle_path

    @staticmethod
    def _validate_response_payload(fmt: ItolExportFormatType, data: bytes) -> None:
        if not data:
            raise PhyloError("iTOL batch_downloader.cgi 返回了空响应内容。")

        head_text = data[:400].decode("utf-8", errors="ignore").strip()
        if head_text.startswith("ERR:") or "Invalid tree ID" in head_text or "<html" in head_text.lower():
            snippet = head_text.splitlines()[0][:180]
            raise PhyloError(f"iTOL 服务端返回错误: {snippet}")

        if fmt == "pdf" and not data.lstrip().startswith(b"%PDF"):
            raise PhyloError("iTOL 导出内容校验失败：未检测到有效的 PDF 文件头。")
        if fmt == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PhyloError("iTOL 导出内容校验失败：未检测到有效的 PNG 文件头。")
        if fmt == "svg" and b"<svg" not in data[:2048].lower():
            raise PhyloError("iTOL 导出内容校验失败：未检测到有效的 SVG 根标签。")
        if fmt == "eps" and not data.lstrip().startswith(b"%!PS"):
            raise PhyloError("iTOL 导出内容校验失败：未检测到有效的 EPS 文件头。")

    @staticmethod
    def export_from_itol(
        tree_id_or_url: str,
        out_dir: Path,
        req: ItolPullRequest,
        timeout: int = 60,
    ) -> Tuple[str, Path]:
        """调用 iTOL 免费开放接口 batch_downloader.cgi 下载排版后的高质量图件。"""
        tree_id = ItolBatchClient.extract_tree_id(tree_id_or_url)
        out_dir.mkdir(parents=True, exist_ok=True)

        payload: Dict[str, str] = {
            "tree": tree_id,
            "format": req.format,
            "display_mode": _DISPLAY_MODE_MAP[req.display_mode],
            "bootstrap_display": "1" if req.bootstrap_display else "0",
            "ignore_branch_length": "1" if req.ignore_branch_length else "0",
        }
        if req.datasets_visible.strip():
            payload["datasets_visible"] = req.datasets_visible.strip()
        if req.format == "png":
            payload["export_dpi"] = str(req.dpi)

        try:
            resp = requests.post(ITOL_BATCH_DOWNLOADER_URL, data=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise PhyloError(f"连接 iTOL 服务器失败: {exc}") from exc

        if resp.status_code != 200:
            raise PhyloError(
                f"iTOL 导出请求返回异常状态码 HTTP {resp.status_code}",
                detail=resp.text[:300],
            )

        ItolBatchClient._validate_response_payload(req.format, resp.content)

        filename = f"itol_{tree_id}_{req.display_mode}.{req.format}"
        out_path = out_dir / filename
        out_path.write_bytes(resp.content)
        return tree_id, out_path
