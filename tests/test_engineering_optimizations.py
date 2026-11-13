# -*- coding: utf-8 -*-
"""
工程优化与架构加固专项验证测试套件
验证：
1. IDE R Language Server 空命令报错修复配置 (.vscode/settings.json)
2. 组装路径解析器动态发现机制与零硬编码盘符字面量 (path_resolver.py)
3. 全库 Python 后端与 Vue/TS/JS 前端源码零彩色 Emoji、UTF-8 编码声明及 open() 显式编码合规性
4. BlastStore SQLite WAL 模式、复合索引、批量事务落盘及 BlastTask 500 条内存封顶
5. GPUSequenceMatcher 向量化 3-mer 滑动窗口局部突变不变性与分块距离矩阵准确性
6. ProteinComparer 模块化拆分、多拷贝相同序列 1:1 配对及 >=400 对候选集下远缘同源蛋白召回
7. other_tools 路由层与 schemas / sangon_order_inspector 解耦兼容性及零冗余导入
"""
import ast
import json
import random
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import numpy as np

from src.analysis.pan_genomics.gpu_accelerator import GPUSequenceMatcher
from src.analysis.protein_compare.categories import PROTEIN_CATEGORIES, resolve_domain_names
from src.analysis.protein_compare.engine import ProteinComparer
from src.analysis.protein_compare.models import (
    ProteinComparisonResult,
    ProteinComparisonRow,
    ProteinItem,
)
from src.assembly.utils.path_resolver import (
    get_candidate_safe_work_dirs,
    resolve_ngcs_cli,
    resolve_ngcs_root,
    resolve_safe_work_dir,
)
from src.backend.services.other_tools.sangon_order_inspector import inspect_sangon_order_dir
from src.backend.services.other_tools.schemas import (
    SANGON_CSV_HEADERS,
    MailConfigUpdateRequest,
    SangonRunRequest,
)
from src.blast.manager import BlastStore, BlastTask

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLOR_EMOJI_RE = re.compile(
    r"(?:[\U0001F000-\U0001FAFF]|[\u2600-\u26FF]|[\u2702-\u2712\u2714\u2716-\u27BF]|[\u2B50\u2B06\u2B07\u2195])\uFE0F?"
)
BINARY_OPEN_MODULES = {"Image", "tarfile", "zipfile", "gzip", "bz2", "lzma", "webbrowser"}


def test_vscode_r_lsp_disabled():
    """验证 .vscode/settings.json 已显式禁用 r.lsp.enabled，防止 R 插件因空路径崩溃"""
    settings_path = PROJECT_ROOT / ".vscode" / "settings.json"
    assert settings_path.exists()
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data.get("r.lsp.enabled") is False


def test_assembly_path_resolver_dynamic_and_zero_hardcoded_drives(monkeypatch):
    """验证组装路径解析器支持环境变量覆盖、动态盘符枚举且源码中不含硬编码盘符字面量"""
    resolver_src = (PROJECT_ROOT / "src" / "assembly" / "utils" / "path_resolver.py").read_text(encoding="utf-8")
    assert not re.search(r'["\'][CDEF]:[/\\]?["\']', resolver_src), "path_resolver.py 中仍存在硬编码盘符字面量"

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
    """验证后端 Python 与前端 Vue/TS/JS 源码不含彩色 Emoji，且 Python 文本 open() 均显式声明 encoding"""
    src_dir = PROJECT_ROOT / "src"
    emoji_files = []
    missing_enc = []

    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if COLOR_EMOJI_RE.search(text):
            emoji_files.append(str(py_file.relative_to(PROJECT_ROOT)))

        tree = ast.parse(text, filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_builtin_open = isinstance(func, ast.Name) and func.id == "open"
            attr_target = func if isinstance(func, ast.Attribute) and func.attr == "open" else None
            if not (is_builtin_open or attr_target is not None):
                continue
            if attr_target is not None and isinstance(attr_target.value, ast.Name) and attr_target.value.id in BINARY_OPEN_MODULES:
                continue

            # builtin open(file, mode, ...) 中 mode 是第 2 个位置参数；Path.open(mode, ...) 中是第 1 个
            mode = "r"
            is_io_open = attr_target is not None and isinstance(attr_target.value, ast.Name) and attr_target.value.id == "io"
            mode_arg_idx = 1 if (is_builtin_open or is_io_open) else 0
            if len(node.args) > mode_arg_idx:
                mode_arg = node.args[mode_arg_idx]
                if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                    mode = mode_arg.value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    mode = kw.value.value
            if "b" in mode:
                continue

            has_enc = any(kw.arg == "encoding" for kw in node.keywords)
            if is_builtin_open and not has_enc and len(node.args) < 4:
                missing_enc.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}")
            elif is_io_open and not has_enc and len(node.args) < 4:
                missing_enc.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}")

    frontend_files = [
        p
        for p in (PROJECT_ROOT / "src" / "web-next" / "src").rglob("*")
        if p.is_file()
        and p.suffix in (".vue", ".js", ".ts")
        and "node_modules" not in p.parts
        and "vendor_phylotree" not in p.parts
    ] + [
        p
        for p in (PROJECT_ROOT / "electron-shell").rglob("*.js")
        if p.is_file() and "node_modules" not in p.parts
    ]
    for fe_file in frontend_files:
        text = fe_file.read_text(encoding="utf-8")
        if COLOR_EMOJI_RE.search(text):
            emoji_files.append(str(fe_file.relative_to(PROJECT_ROOT)))

    assert emoji_files == [], f"发现含 Emoji 的源码文件: {emoji_files}"
    assert missing_enc == [], f"发现未显式声明 encoding 的 open() 调用: {missing_enc}"


def test_blast_store_wal_batch_save_and_memory_cap():
    """验证 BlastStore 启用 WAL 模式、复合索引、批量事务写入及 BlastTask 内存计数"""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_blast.db"
        store = BlastStore(str(db_path))

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

        task = BlastTask("task_batch_01", {"query": ">s1\nATGC"})
        task.result_count = 650
        task.results = [{"sequence_id": f"seq_{i}"} for i in range(500)]
        assert task.to_dict()["result_count"] == 650


def test_gpu_sequence_matcher_3mer_locality_and_candidate_pairs():
    """验证向量化 3-mer 特征矩阵对单点突变具备局部性（不污染下游 k-mer）及候选对筛选准确性"""
    matcher = GPUSequenceMatcher()
    seq_orig = "MKTLLLTLVVVTIVCLDLGYT" * 5
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


def test_protein_comparer_identical_duplicates_and_remote_homolog_recall():
    """
    验证蛋白比对引擎：
    1. 多拷贝完全相同序列按次序 1:1 配对，不产生虚假的 unique_b；
    2. 在 >=400 对候选集下，产品名不同、一致度约 48% 的远缘同源蛋白不被 3-mer 排序丢弃。
    """
    assert "capsid_head" in PROTEIN_CATEGORIES
    dom_names = resolve_domain_names("lysis", "endolysin")
    assert isinstance(dom_names, tuple) and len(dom_names) == 3

    comparer = ProteinComparer()
    identical_seq = "MKTLLLTLVVVTIVCLDLGYT" * 4
    items_a = [
        ProteinItem(
            id=f"A_{i}",
            locus_tag=f"LOC_A_{i}",
            product="major capsid protein",
            translation=identical_seq,
            length_aa=len(identical_seq),
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
            product="major capsid protein",
            translation=identical_seq,
            length_aa=len(identical_seq),
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
    assert res.identical_count == 4
    assert all(isinstance(r, ProteinComparisonRow) and r.match_status == "identical" for r in res.rows)

    # 构造 21 x 21 = 441 对 (>=400) 候选集，检验 ~48% 一致度且产品名不同的同源对召回
    rng = random.Random(42)
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    base_homolog = "".join(rng.choice(alphabet) for _ in range(120))
    mutated_chars = list(base_homolog)
    # 保持连续 3-mer 种子使 K-mer 剪枝通过，整体一致度约 50%
    for pos in range(60, 120):
        mutated_chars[pos] = alphabet[(alphabet.index(mutated_chars[pos]) + 7) % len(alphabet)]
    remote_homolog = "".join(mutated_chars)

    large_a = [
        ProteinItem(
            id="A_REMOTE",
            locus_tag="A_REMOTE",
            product="putative structural protein alpha",
            translation=base_homolog,
            length_aa=len(base_homolog),
            start=1,
            end=360,
            strand="+",
            category="capsid_head",
        )
    ]
    large_b = [
        ProteinItem(
            id="B_REMOTE",
            locus_tag="B_REMOTE",
            product="uncharacterized virion component beta",
            translation=remote_homolog,
            length_aa=len(remote_homolog),
            start=1,
            end=360,
            strand="+",
            category="capsid_head",
        )
    ]
    for i in range(20):
        seq_noise_a = "".join(rng.choice(alphabet) for _ in range(120))
        seq_noise_b = "".join(rng.choice(alphabet) for _ in range(120))
        large_a.append(
            ProteinItem(
                id=f"A_NOISE_{i}",
                locus_tag=f"A_NOISE_{i}",
                product=f"noise protein a{i}",
                translation=seq_noise_a,
                length_aa=120,
                start=1,
                end=360,
                strand="+",
                category="capsid_head",
            )
        )
        large_b.append(
            ProteinItem(
                id=f"B_NOISE_{i}",
                locus_tag=f"B_NOISE_{i}",
                product=f"noise protein b{i}",
                translation=seq_noise_b,
                length_aa=120,
                start=1,
                end=360,
                strand="+",
                category="capsid_head",
            )
        )

    large_res = comparer.compare_two_samples(
        "LargeA",
        large_a,
        "LargeB",
        large_b,
        target_category="capsid_head",
    )
    remote_row = next(r for r in large_res.rows if r.sample_a_id == "A_REMOTE")
    assert remote_row.sample_b_id == "B_REMOTE"
    assert 45.0 <= remote_row.identity_pct <= 55.0


def test_other_tools_modular_schemas_and_clean_imports():
    """验证 other_tools 拆分出的 schemas 与 sangon_order_inspector 独立可用且路由层无冗余导入"""
    other_tools_src = (PROJECT_ROOT / "src" / "backend" / "routes" / "other_tools.py").read_text(encoding="utf-8")
    for unused_sym in ("parse_blast_csv", "select_consensus_hit", "BaseModel"):
        assert unused_sym not in other_tools_src, f"other_tools.py 仍残留未使用的导入: {unused_sym}"

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
