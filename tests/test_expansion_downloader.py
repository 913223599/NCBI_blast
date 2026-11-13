# -*- coding: utf-8 -*-
"""
V3 靶向扩展下载器单元测试（零泄露、GC范围校验、正负双向排异、断点恢复）
"""
import io
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from src.utils.phage_dataset.expansion_downloader import (
    DEFAULT_UNSEEN_HOLDOUT_ACCS,
    ExpansionDownloader,
    collect_excluded_accessions,
)


def _make_genbank_text(
    acc: str,
    seq_str: str,
    organism: str,
    taxonomy: list[str],
    description: str,
    product: str = "hypothetical protein",
    host: str = "",
) -> str:
    rec = SeqRecord(
        Seq(seq_str),
        id=acc,
        name=acc.split(".")[0],
        description=description,
        annotations=cast(
            Any,
            {
                "molecule_type": "DNA",
                "topology": "linear",
                "organism": organism,
                "taxonomy": taxonomy,
            },
        ),
    )
    src_qual = {"organism": [organism]}
    if host:
        src_qual["host"] = [host]
    rec.features.append(SeqFeature(FeatureLocation(0, len(seq_str), strand=1), type="source", qualifiers=src_qual))
    rec.features.append(
        SeqFeature(
            FeatureLocation(10, min(len(seq_str), 310), strand=1),
            type="CDS",
            qualifiers={"product": [product], "locus_tag": ["T_001"]},
        )
    )
    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")
    return buf.getvalue()


def test_collect_excluded_accessions_covers_val_test_and_unseen(tmp_path: Path):
    neg_json = tmp_path / "negative_splits.json"
    neg_json.write_text(
        json.dumps({"train": ["TR_1.1"], "val": ["VA_1.2"], "test": ["TE_1.3"]}),
        encoding="utf-8",
    )
    pos_dir = tmp_path / "splits"
    pos_dir.mkdir()
    (pos_dir / "val.tsv").write_text("accession\tlen\nPV_1.1\t5000\n", encoding="utf-8")
    (pos_dir / "test.tsv").write_text("accession\tlen\nPT_1.2\t6000\n", encoding="utf-8")
    (pos_dir / "train.tsv").write_text("accession\tlen\nPTR_1.1\t7000\n", encoding="utf-8")

    exact, base = collect_excluded_accessions(
        negative_splits_json=neg_json,
        positive_splits_dir=pos_dir,
        extra_excluded_accs=["EXTRA_9.4"],
        include_existing_train=False,
    )
    assert "VA_1.2" in exact and "TE_1.3" in exact
    assert "PV_1.1" in exact and "PT_1.2" in exact
    assert "EXTRA_9.4" in exact
    assert "TR_1.1" not in exact and "PTR_1.1" not in exact
    for unseen in DEFAULT_UNSEEN_HOLDOUT_ACCS:
        assert unseen in exact
        assert unseen.split(".")[0] in base


def test_expansion_downloader_filters_leakage_gc_and_identity(tmp_path: Path):
    # 1. 高 GC 放线菌合法负例 (75% GC, 720bp 仅在自定义测试 query 下允许)
    high_gc_seq = ("GGCCGCAT" * 90)[:720]
    gb_good_high_gc = _make_genbank_text(
        acc="NZ_ACTINO_01.1",
        seq_str=high_gc_seq,
        organism="Streptomyces avermitilis",
        taxonomy=["Bacteria", "Actinomycetota", "Streptomyces"],
        description="Streptomyces avermitilis complete genome",
        product="polyketide synthase",
    )
    # 2. 应当被泄露防线拦截（命中 unseen NC_003888 不同版本号）
    gb_leak_unseen = _make_genbank_text(
        acc="NC_003888.9",
        seq_str=high_gc_seq,
        organism="Streptomyces coelicolor",
        taxonomy=["Bacteria", "Actinomycetota"],
        description="Streptomyces coelicolor chromosome",
    )
    # 3. 应当因 GC 过低被高 GC 分层过滤
    low_gc_seq = ("AATTATAT" * 90)[:720]
    gb_bad_gc = _make_genbank_text(
        acc="NZ_LOWGC_02.1",
        seq_str=low_gc_seq,
        organism="Streptomyces sp.",
        taxonomy=["Bacteria", "Actinomycetota"],
        description="fake low gc entry",
    )
    # 4. 应当因反向排异拦截游离噬菌体
    gb_phage_contam = _make_genbank_text(
        acc="NC_PHAGE_99.1",
        seq_str=high_gc_seq,
        organism="Streptomyces phage Phi1",
        taxonomy=["Viruses", "Duplodnaviria", "Caudoviricetes"],
        description="Streptomyces phage Phi1 complete genome",
        product="major capsid protein",
        host="Streptomyces",
    )

    # 稀缺正样本：合法 Microviridae vs 应该跳过 Caudoviricetes
    micro_seq = ("ATGCGCAT" * 100)[:800]
    gb_good_micro = _make_genbank_text(
        acc="NC_MICRO_01.1",
        seq_str=micro_seq,
        organism="Escherichia phage phiX174",
        taxonomy=["Viruses", "Monodnaviria", "Phixviricota", "Malgrandaviricetes", "Microviridae"],
        description="Microviridae complete genome",
        product="major spike protein",
        host="Escherichia coli",
    )
    gb_skip_caudo = _make_genbank_text(
        acc="NC_CAUDO_02.1",
        seq_str=micro_seq,
        organism="Escherichia phage T4",
        taxonomy=["Viruses", "Duplodnaviria", "Uroviricota", "Caudoviricetes"],
        description="Caudoviricetes phage complete genome",
        product="tail fiber protein",
        host="Escherichia coli",
    )

    mock_session = MagicMock()

    def fake_get(url, params=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "esearch" in url:
            term = (params or {}).get("term", "")
            if "Microviridae" in term:
                resp.json.return_value = {"esearchresult": {"count": "2", "idlist": ["201", "202"]}}
            else:
                resp.json.return_value = {"esearchresult": {"count": "4", "idlist": ["101", "102", "103", "104"]}}
        else:
            ids = (params or {}).get("id", "")
            if "101" in ids:
                resp.text = "\n".join([gb_good_high_gc, gb_leak_unseen, gb_bad_gc, gb_phage_contam])
            else:
                resp.text = "\n".join([gb_good_micro, gb_skip_caudo])
        return resp

    mock_session.get.side_effect = fake_get

    exact, base = collect_excluded_accessions()
    dl = ExpansionDownloader(
        output_dir=tmp_path / "exp_out",
        excluded_exact=exact,
        excluded_base=base,
        retry_backoff_base=0.0,
        session=mock_session,
    )

    neg_queries = [
        ("HighGC_Test", "high_gc_chromosome", "Streptomyces_test", 1.0, 4, 0.68, 0.85, 500, 10000),
    ]
    neg_res = dl.download_negative_expansion(target_count=5, queries=neg_queries)
    assert neg_res["saved_count"] == 1
    assert (tmp_path / "exp_out" / "negative_ext" / "fasta" / "NZ_ACTINO_01.1.fasta").exists()
    assert not (tmp_path / "exp_out" / "negative_ext" / "fasta" / "NC_003888.9.fasta").exists()

    pos_queries = [
        ("Rare_Micro", "Microviridae", "Microviridae_test", 1.0, 5, 0.20, 0.75, 500, 15000),
    ]
    pos_res = dl.download_rare_phage_expansion(target_count=5, queries=pos_queries)
    assert pos_res["saved_count"] == 1
    assert (tmp_path / "exp_out" / "positive_rare_ext" / "fasta" / "NC_MICRO_01.1.fasta").exists()
    assert not (tmp_path / "exp_out" / "positive_rare_ext" / "fasta" / "NC_CAUDO_02.1.fasta").exists()


def test_expansion_downloader_fast_fasta_mode_for_chromosomes(tmp_path: Path):
    high_gc_seq = ("GGCCGCAT" * 100)[:800]
    mock_session = MagicMock()

    def fake_get(url, params=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "esearch" in url:
            resp.json.return_value = {"esearchresult": {"count": "2", "idlist": ["301", "302"]}}
        else:
            assert (params or {}).get("rettype") == "fasta"
            resp.text = (
                f">NZ_STREP_FAST.1 Streptomyces griseus complete genome\n{high_gc_seq}\n"
                f">NC_003888.3 Streptomyces coelicolor A3(2) complete genome\n{high_gc_seq}\n"
            )
        return resp

    mock_session.get.side_effect = fake_get
    exact, base = collect_excluded_accessions()
    dl = ExpansionDownloader(
        output_dir=tmp_path / "exp_fast",
        excluded_exact=exact,
        excluded_base=base,
        retry_backoff_base=0.0,
        session=mock_session,
    )
    chrom_queries = [
        ("HighGC_Fast", "high_gc_chromosome", "Streptomyces", 1.0, 2, 0.68, 0.85, 500, 12000000),
    ]
    res = dl.download_negative_expansion(target_count=5, queries=chrom_queries)
    assert res["saved_count"] == 1
    assert (tmp_path / "exp_fast" / "negative_ext" / "fasta" / "NZ_STREP_FAST.1.fasta").exists()
    assert not (tmp_path / "exp_fast" / "negative_ext" / "fasta" / "NC_003888.3.fasta").exists()

