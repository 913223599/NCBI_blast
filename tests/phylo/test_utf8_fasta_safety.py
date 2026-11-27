# -*- coding: utf-8 -*-
"""
UTF-8 / Windows GBK 安全回归测试：
1. AST 静态门禁：确保 src/phylo/ 与 src/backend/routes/phylo.py 中无任何隐式 cp936(GBK) 文件或 Biopython 路径读写；
2. 含中文样本名 FASTA 端到端读取与 Treemmer 修剪保护校验。
"""
import ast
from pathlib import Path
import pytest

pytestmark = pytest.mark.offline

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_no_implicit_gbk_io_in_phylo_sources() -> None:
    """扫描 PhyloCore 相关全部 Python 源码，禁止文本读写省略 encoding 或直接传路径给 Biopython。"""
    roots = [PROJECT_ROOT / "src" / "phylo", PROJECT_ROOT / "src" / "backend" / "routes" / "phylo.py"]
    py_files = []
    for r in roots:
        if r.is_file():
            py_files.append(r)
        else:
            py_files.extend(sorted(r.rglob("*.py")))

    # 仅允许已在 with open(..., encoding="utf-8") 内传入文件句柄的两处核心封装调用
    allowed_bio_handle_calls = {
        Path("src/phylo/core/fasta_io.py").as_posix(),
        Path("src/phylo/core/profiler.py").as_posix(),
    }

    violations = []
    for path in py_files:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            kw_names = {k.arg for k in node.keywords}
            fn = ""
            if isinstance(node.func, ast.Name):
                fn = node.func.id
            elif isinstance(node.func, ast.Attribute):
                val = node.func.value.id if isinstance(node.func.value, ast.Name) else "..."
                fn = f"{val}.{node.func.attr}"

            # 1. open() 非二进制模式必须显式声明 encoding
            if fn == "open":
                mode = None
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for k in node.keywords:
                    if k.arg == "mode" and isinstance(k.value, ast.Constant):
                        mode = str(k.value.value)
                if (mode is None or "b" not in mode) and "encoding" not in kw_names:
                    violations.append(f"{rel}:{node.lineno}: open() 缺少 encoding 参数 (mode={mode})")

            # 2. Path.read_text / write_text 必须显式声明 encoding
            if fn.endswith(".read_text") or fn.endswith(".write_text"):
                if "encoding" not in kw_names:
                    violations.append(f"{rel}:{node.lineno}: {fn}() 缺少 encoding 参数")

            # 3. 禁止直接传字符串/Path 给 SeqIO/AlignIO/Phylo，统一通过 fasta_io UTF-8 封装
            if any(fn.startswith(p) for p in ("SeqIO.", "AlignIO.", "Phylo.")):
                if rel not in allowed_bio_handle_calls:
                    violations.append(f"{rel}:{node.lineno}: 禁止直接调用 {fn}()，请改用 fasta_io UTF-8 封装")
                else:
                    # 即便在白名单内也禁止 str(...) 传路径
                    first_arg = node.args[0] if node.args else None
                    if isinstance(first_arg, ast.Call) and isinstance(first_arg.func, ast.Name) and first_arg.func.id == "str":
                        violations.append(f"{rel}:{node.lineno}: {fn}() 传入了 str(...) 路径而非 UTF-8 文件句柄")

    assert not violations, "发现隐式 GBK / 非 UTF-8 IO 风险:\n" + "\n".join(violations)


def test_utf8_chinese_fasta_roundtrip_and_treemmer(tmp_path: Path) -> None:
    """验证含中文样本名的 UTF-8 FASTA 读取及 Treemmer ASCII 映射等价修剪。"""
    from src.phylo.core.fasta_io import iter_fasta_records, read_fasta_records
    from src.phylo.engines.reference.treemmer_pruner import TreemmerPruner

    cn_id = "附件2霍氏肠杆菌噬菌体2基因组序列"
    fa_path = tmp_path / f"{cn_id}.fasta"
    fa_path.write_text(f">{cn_id} 完整基因组\nATGCTAGCTAGCATCGATCG\n", encoding="utf-8")

    recs_iter = list(iter_fasta_records(fa_path))
    recs_list = read_fasta_records(fa_path)
    assert len(recs_iter) == 1
    assert len(recs_list) == 1
    assert recs_list[0].id == cn_id
    assert str(recs_list[0].seq) == "ATGCTAGCTAGCATCGATCG"

    # 验证 TreemmerPruner 在使用 ASCII 映射键修剪后能够准确保留受保护节点并映回原始中文 ID
    nwk = "((TM0001:0.01,TM0002:0.02):0.05,(TM0003:0.10,TM0004:0.20):0.05);"
    ascii_to_acc = {
        "TM0001": cn_id,
        "TM0002": "NC_000001",
        "TM0003": "NC_000002",
        "TM0004": "OUT_001",
    }
    kept_ascii = TreemmerPruner.prune_newick_leaves(
        nwk,
        target_count=2,
        protected={"TM0001", "TM0004"},
    )
    kept_orig = {ascii_to_acc[k] for k in kept_ascii}
    assert kept_orig == {cn_id, "OUT_001"}
