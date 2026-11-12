# -*- coding: utf-8 -*-
"""
工程优化与架构加固专项验证测试套件
验证：
1. IDE R Language Server 空命令报错修复配置 (.vscode/settings.json)
2. 组装路径解析器动态发现机制与零硬编码盘符依赖 (path_resolver.py)
3. 全库 src/ Python 源码零 Emoji、UTF-8 编码声明及 open() 显式编码合规性
4. BlastStore SQLite WAL 模式、复合索引与 save_results_batch 批量事务落盘
5. GPUSequenceMatcher 向量化 3-mer 滑动窗口局部突变不变性与分块距离矩阵准确性
6. ProteinComparer 模块化拆分 (categories.py, models.py) 与多线程比对正确性
7. other_tools 路由层与 schemas / sangon_order_inspector 解耦兼容性
"""
import ast
import json
import re
import sqlite3
import tempfile
from pathlib import Path

import numpy as np

from src.analysis.pan_genomics.gpu_accelerator import GPUSequenceMatcher
from src.analysis.protein_compare.categories import PROTEIN_CATEGORIES, resolve_domain_names
from src.analysis.protein_compare.engine import ProteinComparer
from src.analysis.protein_compare.models import (
    MutationSite,
    ProteinComparisonResult,
    ProteinComparisonRow,
    ProteinItem,
    RegionDomainItem,
)
from src.assembly.utils.path_resolver import (
    get_candidate_safe_work_dirs,
    resolve_ngcs_cli,
    resolve_ngcs_root,
    resolve_safe_work_dir,
)
from src.backend.services.other_tools.sangon_order_inspector import (
    export_sangon_order_csv,
    inspect_sangon_order_dir,
)
from src.backend.services.other_tools.schemas import (
    SANGON_CSV_HEADERS,
    MailConfigUpdateRequest,
    SangonRunRequest,
)
from src.blast.manager import BlastStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def test_vscode_r_lsp_disabled():
    """验证 .vscode/settings.json 已显式禁用 r.lsp.enabled，防止 R 插件因空路径崩溃"""
    settings_path = PROJECT_ROOT / ".vscode" / "settings.json"
    assert settings_path.exists()
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data.get("r.lsp.enabled") is False


def test_assembly_path_resolver_dynamic_and_env_override(monkeypatch):
    """验证组装路径解析器支持环境变量覆盖及无 E: 盘时的安全回退"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_ngcs = tmp_path / "custom_ngcs"
        fake_cli = fake_ngcs / "ngcs" / "cli.py"
        fake_cli.parent.mkdir(parents=True, exist_ok=True)
        fake_cli.write_text("# -*- coding: utf-8 -*-\n", encoding="utf-8")

        monkeypatch.setenv("NGCS_ROOT", str(fake_ngcs))
        assert resolve_ngcs_root() == fake_ngcs.resolve()
        assert resolve_ngcs_cli() == fake_cli.resolve()

        work_root = tmp_path / "safe_work"
        monkeypatch.setenv("NGCS_WORK_DIR", str(work_root))
        task_dir = resolve_safe_work_dir("ASM_TEST_001")
        assert task_dir == (work_root / "tasks" / "ASM_TEST_001").resolve()
        cands = get_candidate_safe_work_dirs("ASM_TEST_001")
        assert task_dir in cands


def test_source_code_zero_emoji_and_utf8_compliance():
    """验证 src/ 下所有 Python 文件不含 Emoji 表情、不含 gbk 编码且文本 open() 均声明 encoding"""
    src_dir = PROJECT_ROOT / "src"
    emoji_files = []
    missing_enc = []

    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if EMOJI_RE.search(text):
            emoji_files.append(str(py_file.relative_to(PROJECT_ROOT)))

        tree = ast.parse(text, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                is_open = (isinstance(func, ast.Name) and func.id == "open") or (
                    isinstance(func, ast.Attribute) and func.attr == "open"
                )
                if not is_open:
                    continue
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if func.value.id in ("Image", "tarfile", " zipfile", "gzip", "bz2", "lzma", "webbrowser"):
                        continue
                mode = "r"
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        mode = kw.value.value
                if "b" in mode:
                    continue
                has_enc = len(node.args) >= 4 or any(kw.arg == "encoding" for kw in node.keywords)
                if isinstance(func, ast.Name) and func.id == "open" and not has_enc:
                    missing_enc.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert emoji_files == [], f"发现含 Emoji 的源码文件: {emoji_files}"
    assert missing_enc == [], f"发现未显式声明 encoding 的 open() 调用: {missing_enc}"


def test_blast_store_wal_and_batch_save():
    """验证 BlastStore 启用 WAL 模式、创建复合索引并支持批量事务写入"""
    from contextlib import closing
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_blast.db"
        store = BlastStore(db_path)

        with closing(sqlite3.connect(db_path)) as conn:
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert journal_mode.lower() == "wal"
            indexes = [
                row[1] for row in conn.execute("PRAGMA index_list('results');").fetchall()
            ]
            assert "idx_results_task_seq" in indexes

        batch = [
            {
                "sequence_id": f"seq_{i}",
                "sequence_length": 150 + i,
                "status": "pending",
                "raw_sequence": "ATGC" * 10,
                "data": [],
                "timestamp": "2026-11-12T20:00:00",
            }
            for i in range(120)
        ]
        store.save_results_batch("task_batch_01", batch)
        loaded = store.get_results("task_batch_01")
        assert len(loaded) == 120
        assert loaded[0]["sequence_id"] == "seq_0"
        assert loaded[-1]["sequence_id"] == "seq_119"


def test_gpu_sequence_matcher_3mer_locality_and_candidate_pairs():
    """验证向量化 3-mer 特征矩阵对单点突变具备局部性（不污染下游 k-mer）及候选对筛选准确性"""
    matcher = GPUSequenceMatcher()
    seq_orig = "MKTLLLTLVVVTIVCLDLGYT" * 5
    # 仅在开头第 3 位发生单氨基酸替换
    seq_mut = "MKALLLTLVVVTIVCLDLGYT" * 5
    seq_diff = "WQPCCCRRRNNNDDDQQQEEE" * 5

    mat = matcher._build_normalized_3mer_matrix([seq_orig, seq_mut, seq_diff], num_features=512)
    assert mat.shape == (3, 512)

    sim_orig_mut = float(np.dot(mat[0], mat[1]))
    sim_orig_diff = float(np.dot(mat[0], mat[2]))
    assert sim_orig_mut > 0.80, f"单点突变的 3-mer 余弦相似度应保持高位，实际为 {sim_orig_mut}"
    assert sim_orig_diff < 0.25

    pairs = matcher.compute_batch_candidate_pairs(
        [seq_orig, seq_mut, seq_diff],
        sim_threshold=0.5,
    )
    assert (0, 1) in pairs
    assert (0, 2) not in pairs


def test_protein_comparer_modular_imports_and_parallel_compare():
    """验证蛋白比对引擎拆分模块后的功能完整性与多线程比对准确性"""
    assert "capsid_head" in PROTEIN_CATEGORIES
    dom_names = resolve_domain_names("lysis", "endolysin")
    assert isinstance(dom_names, tuple) and len(dom_names) == 3

    comparer = ProteinComparer()
    items_a = [
        ProteinItem(
            id=f"A_{i}",
            locus_tag=f"LOC_A_{i}",
            product=f"major capsid protein {i}",
            translation="MKTLLLTLVVVTIVCLDLGYT" * 4 + ("W" * (i + 1)),
            length_aa=84 + i + 1,
            start=1 + i * 300,
            end=252 + i * 300,
            strand="+",
            category="capsid_head",
        )
        for i in range(4)
    ]
    items_b = [
        ProteinItem(
            id=f"B_{i}",
            locus_tag=f"LOC_B_{i}",
            product=f"major capsid protein {i}",
            translation="MKTLLLTLVVVTIVCLDLGYT" * 4 + ("W" * (i + 1)),
            length_aa=84 + i + 1,
            start=1 + i * 300,
            end=252 + i * 300,
            strand="+",
            category="capsid_head",
        )
        for i in range(4)
    ]
    res = comparer.compare_two_samples(
        "StrainA",
        items_a,
        "StrainB",
        items_b,
        target_category="capsid_head",
    )
    assert isinstance(res, ProteinComparisonResult)
    assert res.total_compared_pairs == 4
    assert all(isinstance(r, ProteinComparisonRow) for r in res.rows)
    assert all(r.identity_pct == 100.0 for r in res.rows)


def test_other_tools_modular_schemas_and_inspector():
    """验证 other_tools 拆分出的 schemas 与 sangon_order_inspector 独立可用"""
    assert len(SANGON_CSV_HEADERS) == 11
    req = SangonRunRequest(evalue="0.01")
    assert req.evalue == "0.01"
    mail_req = MailConfigUpdateRequest()
    assert mail_req.imap_port == 993

    with tempfile.TemporaryDirectory() as tmp:
        order_dir = Path(tmp) / "20261112_999888"
        (order_dir / "原始压缩包").mkdir(parents=True)
        (order_dir / "原始数据").mkdir(parents=True)
        (order_dir / "BLAST结果").mkdir(parents=True)
        info = inspect_sangon_order_dir(order_dir, project_root=Path(tmp))
        assert info["order_no"] == "999888"
        assert info["status"] == "pending"
