# -*- coding: utf-8 -*-
"""
配套负样本下载/校验/索引及正样本预处理模块单元测试（先测试后执行）
"""
import io
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from src.utils.phage_dataset.negative_downloader import NegativeDatasetDownloader
from src.utils.phage_dataset.negative_indexer import build_negative_dataset_indexes
from src.utils.phage_dataset.negative_validator import validate_negative_dataset_parallel
from src.utils.phage_dataset.preprocessor import (
    compute_canonical_4mer_freq,
    preprocess_phage_dataset,
)


def _make_gbk_text(
    acc: str,
    seq_str: str,
    organism: str,
    description: str,
    taxonomy: list,
    products: list,
    host: str = "",
    plasmid_name: str = "",
) -> str:
    rec = SeqRecord(Seq(seq_str), id=acc, name=acc, description=description)
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["topology"] = "circular"
    rec.annotations["organism"] = organism
    rec.annotations["taxonomy"] = taxonomy

    src_qual = {}
    if host:
        src_qual["host"] = [host]
    if plasmid_name:
        src_qual["plasmid"] = [plasmid_name]
    feats = [SeqFeature(FeatureLocation(0, len(seq_str), strand=1), type="source", qualifiers=src_qual)]

    step = max(250, len(seq_str) // max(1, len(products)))
    for i, prod in enumerate(products):
        s = i * step
        e = min(len(seq_str), s + 210)
        if e - s < 90:
            break
        feats.append(
            SeqFeature(
                FeatureLocation(s, e, strand=1 if i % 2 == 0 else -1),
                type="CDS",
                qualifiers={
                    "locus_tag": [f"{acc}_{i+1:03d}"],
                    "protein_id": [f"WP_{acc}_{i+1:03d}"],
                    "product": [prod],
                    "translation": ["MKAFGKPLM" * 10],
                },
            )
        )
    rec.features = feats
    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")
    return buf.getvalue()


class _FakeNegSession:
    def __init__(self, uid_map: dict):
        self.uid_map = uid_map

    def get(self, url: str, params: dict, timeout: int = 30):
        if "esearch.fcgi" in url:
            uids = list(self.uid_map.keys())
            payload = {"esearchresult": {"count": str(len(uids)), "idlist": uids}}
            return SimpleNamespace(status_code=200, json=lambda p=payload: p, raise_for_status=lambda: None)
        req_ids = [x.strip() for x in str(params.get("id", "")).split(",") if x.strip()]
        text = "\n".join(self.uid_map[u] for u in req_ids if u in self.uid_map)
        return SimpleNamespace(status_code=200, text=text, raise_for_status=lambda: None)


def test_negative_downloader_blocks_phage_contamination():
    """验证负样本下载器能保留质粒并拦截误混入的游离噬菌体。"""
    seq_a = ("ATGAAAGCATTTGGGAAACCCGCG" * 200)[:3600]
    plasmid_gbk = _make_gbk_text(
        "NZ_PLAS_01",
        seq_a,
        "Escherichia coli",
        "Escherichia coli plasmid pTest1, complete sequence",
        ["Bacteria", "Pseudomonadota", "Enterobacteriaceae"],
        ["conjugal transfer protein TraA", "replication initiation protein"],
        plasmid_name="pTest1",
    )
    phage_gbk = _make_gbk_text(
        "NC_PHAGE_99",
        seq_a,
        "Escherichia phage T4",
        "Escherichia phage T4, complete genome",
        ["Viruses", "Duplodnaviria", "Caudoviricetes"],
        ["major capsid protein", "terminase large subunit"],
        host="Escherichia coli",
    )
    with tempfile.TemporaryDirectory() as tmp:
        neg_dir = Path(tmp)
        sess = _FakeNegSession({"201": plasmid_gbk, "202": phage_gbk})
        dl = NegativeDatasetDownloader(neg_dir, min_length_bp=3000, retry_backoff_base=0.0, session=sess)
        dl._min_interval = 0.0
        queries = [("Plasmid_Escherichia", "plasmid", "dummy", 1.0, 10)]
        summary = dl.download_batch_dataset(target_count=2, queries=queries)

        assert summary["saved_count"] == 1
        assert (neg_dir / "gbk" / "NZ_PLAS_01.gbk").exists()
        assert not (neg_dir / "gbk" / "NC_PHAGE_99.gbk").exists()
        ckpt = json.loads((neg_dir / "meta" / "negative_download_checkpoint.json").read_text(encoding="utf-8"))
        assert "phage_contamination_blocked" in ckpt["skipped_ids"]["202"]


def test_negative_validator_and_indexer():
    """验证负样本多核校验（质粒/真核病毒识别+噬菌体污染剔除）及 SQLite/TSV/manifest 索引构建。"""
    seq_a = ("ATGGGCAAACCCTTTAAAGGGCCC" * 200)[:3600]
    with tempfile.TemporaryDirectory() as tmp:
        neg_dir = Path(tmp)
        (neg_dir / "fasta").mkdir()
        (neg_dir / "gbk").mkdir()

        records = [
            (
                "NZ_PLAS_01",
                _make_gbk_text(
                    "NZ_PLAS_01",
                    seq_a,
                    "Klebsiella pneumoniae",
                    "Klebsiella pneumoniae plasmid pKPN1, complete sequence",
                    ["Bacteria", "Pseudomonadota", "Enterobacteriaceae"],
                    ["conjugal transfer protein", "type IV secretion protein"],
                    plasmid_name="pKPN1",
                ),
            ),
            (
                "NC_VIR_02",
                _make_gbk_text(
                    "NC_VIR_02",
                    seq_a,
                    "Human adenovirus C",
                    "Human adenovirus C, complete genome",
                    ["Viruses", "Varidnaviria", "Adenoviridae"],
                    ["hexon protein", "penton base"],
                    host="Homo sapiens",
                ),
            ),
            (
                "NC_CONTAM_03",
                _make_gbk_text(
                    "NC_CONTAM_03",
                    seq_a,
                    "Salmonella phage P22",
                    "Salmonella phage P22, complete genome",
                    ["Viruses", "Duplodnaviria", "Caudoviricetes"],
                    ["major capsid protein", "tyrosine integrase"],
                    host="Salmonella enterica",
                ),
            ),
        ]

        for acc, gbk_txt in records:
            (neg_dir / "gbk" / f"{acc}.gbk").write_text(gbk_txt, encoding="utf-8")
            rec = SeqIO.read(io.StringIO(gbk_txt), "genbank")
            SeqIO.write(rec, str(neg_dir / "fasta" / f"{acc}.fasta"), "fasta")

        vals = validate_negative_dataset_parallel(neg_dir, min_length_bp=3000, max_workers=1)
        by_acc = {v.accession: v for v in vals}

        assert by_acc["NZ_PLAS_01"].is_valid_negative is True
        assert by_acc["NZ_PLAS_01"].negative_category == "plasmid"
        assert by_acc["NC_VIR_02"].is_valid_negative is True
        assert by_acc["NC_VIR_02"].negative_category == "non_phage_virus"
        assert by_acc["NC_CONTAM_03"].is_valid_negative is False
        assert by_acc["NC_CONTAM_03"].status == "failed"

        manifest = build_negative_dataset_indexes(neg_dir, vals, build_blast_db=False)
        assert manifest["summary"]["valid_negative_count"] == 2
        assert manifest["summary"]["rejected_phage_contaminated"] == 1
        assert manifest["negative_category_distribution"] == {"non_phage_virus": 1, "plasmid": 1}

        with closing(sqlite3.connect(neg_dir / "index" / "negative_index.sqlite")) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM genomes WHERE is_valid_negative = 1").fetchone()[0]
            assert cnt == 2

        nucl_txt = Path(manifest["artifacts"]["nucl_fasta"]).read_text(encoding="utf-8")
        assert "NZ_PLAS_01" in nucl_txt and "NC_VIR_02" in nucl_txt
        assert "NC_CONTAM_03" not in nucl_txt


def test_canonical_4mer_and_cluster_aware_preprocessor():
    """验证反向互补 4-mer 对称性、分片特征落盘与同源集群零泄露划分。"""
    s = "ATGCGTACGTAGCTAGCTAGCATCGATCGTAGCTAGCTA"
    rc = str(Seq(s).reverse_complement())
    f1 = compute_canonical_4mer_freq(s)
    f2 = compute_canonical_4mer_freq(rc)
    assert f1.shape == (136,)
    assert np.allclose(f1, f2, atol=1e-6)
    assert np.isclose(f1.sum(), 1.0, atol=1e-5)

    # 构造 5 株测试噬菌体：前两株同序列（必然聚为同一簇），后 3 株特征明显不同
    rng = np.random.default_rng(42)
    seq_base = "".join(rng.choice(["A", "C", "G", "T"], size=6000, p=[0.25, 0.25, 0.25, 0.25]))
    seq_at = "".join(rng.choice(["A", "C", "G", "T"], size=6000, p=[0.40, 0.10, 0.10, 0.40]))
    seq_gc = "".join(rng.choice(["A", "C", "G", "T"], size=6000, p=[0.10, 0.40, 0.40, 0.10]))
    seq_c_bias = "".join(rng.choice(["A", "C", "G", "T"], size=6000, p=[0.15, 0.45, 0.15, 0.25]))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "gbk").mkdir()

        samples = [
            ("NC_DUP_01", seq_base),
            ("NC_DUP_02", seq_base),
            ("NC_AT_03", seq_at),
            ("NC_GC_04", seq_gc),
            ("NC_CB_05", seq_c_bias),
        ]
        for acc, sq in samples:
            txt = _make_gbk_text(
                acc,
                sq,
                f"Escherichia phage {acc}",
                f"Escherichia phage {acc}, complete genome",
                ["Viruses", "Duplodnaviria", "Caudoviricetes"],
                ["major capsid protein", "terminase large subunit", "endolysin", "hypothetical protein"],
                host="Escherichia coli",
            )
            (root / "gbk" / f"{acc}.gbk").write_text(txt, encoding="utf-8")

        manifest = preprocess_phage_dataset(
            root,
            shard_size=2,
            window_size=3000,
            window_step=1500,
            sim_threshold=0.97,
            max_workers=1,
        )
        assert manifest["summary"]["total_genomes"] == 5
        assert manifest["summary"]["total_clusters"] == 4  # DUP_01 与 DUP_02 合并为一个簇

        # 验证同簇样本绝对在同一 split（零跨集泄露）
        feat_lines = (root / "preprocessed" / "genome_features.tsv").read_text(encoding="utf-8").splitlines()[1:]
        acc_to_info = {}
        for ln in feat_lines:
            parts = ln.split("\t")
            acc_to_info[parts[0]] = (parts[1], parts[2])  # (cluster_id, split)

        assert acc_to_info["NC_DUP_01"][0] == acc_to_info["NC_DUP_02"][0]
        assert acc_to_info["NC_DUP_01"][1] == acc_to_info["NC_DUP_02"][1]
        assert (root / "preprocessed" / "preprocess_checkpoint.json").exists()
        assert (root / "preprocessed" / "shards" / "orf_shard_0000.jsonl").exists()
        assert (root / "preprocessed" / "shards" / "win_shard_0000.jsonl").exists()

