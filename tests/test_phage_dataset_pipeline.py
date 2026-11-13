# -*- coding: utf-8 -*-
"""
噬菌体数据集下载、多核验证与索引构建单元测试（先测试后执行）
覆盖：
1. 分层检索去重与超采配额控制；
2. gbwithparts 拆分落盘、原子写与 Checkpoint 断点续传恢复；
3. 多核并行验证器对正常样本、序列长度不一致损坏样本、缺失配对样本的识别；
4. SQLite WAL 索引（genomes + cds_features）、TSV 导出、manifest.json 汇总与 BLAST 库调用。
"""
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from src.utils.phage_dataset.indexer import build_phage_dataset_indexes
from src.utils.phage_dataset.ncbi_downloader import (
    PhageDatasetDownloader,
    split_genbank_entries,
)
from src.utils.phage_dataset.validator import validate_dataset_parallel


def _build_synthetic_gbk(
    accession: str,
    length: int = 3600,
    host: str = "Escherichia coli",
    product: str = "major capsid protein",
) -> str:
    """生成一条符合 BioPython 标准的合成噬菌体 GenBank 文本。"""
    import io

    motif = ("ATGAAAGCATTTGGGAAACCC" * 200)[:length]
    rec = SeqRecord(
        Seq(motif),
        id=accession,
        name=accession,
        description=f"Escherichia phage {accession}, complete genome",
    )
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["topology"] = "circular"
    rec.annotations["organism"] = f"Escherichia phage {accession}"
    cast(Any, rec.annotations)["taxonomy"] = ["Viruses", "Duplodnaviria", "Caudoviricetes"]

    src_feat = SeqFeature(
        FeatureLocation(0, length, strand=1),
        type="source",
        qualifiers={"host": [host]},
    )
    cds_feat = SeqFeature(
        FeatureLocation(0, 300, strand=1),
        type="CDS",
        qualifiers={
            "locus_tag": [f"{accession}_0001"],
            "protein_id": [f"WP_{accession}"],
            "product": [product],
            "translation": ["MKAFGKP" * 14],
        },
    )
    cds_int = SeqFeature(
        FeatureLocation(300, 600, strand=1),
        type="CDS",
        qualifiers={
            "locus_tag": [f"{accession}_0002"],
            "protein_id": [f"WP_{accession}_INT"],
            "product": ["tyrosine integrase"],
            "translation": ["MKLLKKII" * 12],
        },
    )
    rec.features = [src_feat, cds_feat, cds_int]

    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")
    return buf.getvalue()


class _FakeSession:
    """模拟 NCBI E-utilities esearch 与 efetch 响应的轻量桩对象。"""

    def __init__(self, uid_to_gbk: dict, fail_second_batch: bool = False):
        self.uid_to_gbk = uid_to_gbk
        self.fail_second_batch = fail_second_batch
        self.efetch_calls = 0

    def get(self, url: str, params: dict, timeout: int = 30):
        if "esearch.fcgi" in url:
            uids = list(self.uid_to_gbk.keys())
            payload = {"esearchresult": {"count": str(len(uids)), "idlist": uids}}
            return SimpleNamespace(
                status_code=200,
                json=lambda p=payload: p,
                raise_for_status=lambda: None,
            )

        self.efetch_calls += 1
        if self.fail_second_batch and self.efetch_calls >= 2:
            return SimpleNamespace(
                status_code=503,
                text="Service Unavailable",
                raise_for_status=lambda: None,
            )

        req_ids = [x.strip() for x in str(params.get("id", "")).split(",") if x.strip()]
        combined = "\n".join(self.uid_to_gbk[uid] for uid in req_ids if uid in self.uid_to_gbk)
        return SimpleNamespace(
            status_code=200,
            text=combined,
            raise_for_status=lambda: None,
        )


def test_split_genbank_entries_and_checkpoint_resume():
    """验证 GenBank 多记录切分、分片即时落盘与断点续传不重复拉取已完成批"""
    gbk1 = _build_synthetic_gbk("NC_TEST_001")
    gbk2 = _build_synthetic_gbk("NC_TEST_002")
    gbk3 = _build_synthetic_gbk("NC_TEST_003")

    entries = split_genbank_entries(gbk1 + "\n" + gbk2)
    assert len(entries) == 2

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        uid_map = {"101": gbk1, "102": gbk2, "103": gbk3}

        # 第一次运行：batch_size=2，第1批2株落盘，第2批模拟服务端失败，验证第1批已安全存盘
        fake_fail = _FakeSession(uid_map, fail_second_batch=True)
        dl1 = PhageDatasetDownloader(data_dir, batch_size=2, min_length_bp=3000, retry_backoff_base=0.0, session=fake_fail)
        dl1._min_interval = 0.0
        queries = [("Escherichia", "dummy", 1.0)]

        try:
            dl1.download_batch_dataset(target_count=3, queries=queries)
        except RuntimeError:
            pass

        assert (data_dir / "gbk" / "NC_TEST_001.gbk").exists()
        assert (data_dir / "fasta" / "NC_TEST_001.fasta").exists()
        assert (data_dir / "gbk" / "NC_TEST_002.gbk").exists()
        assert not (data_dir / "gbk" / "NC_TEST_003.gbk").exists()

        # 第二次断点恢复运行：仅请求剩余的 103
        fake_ok = _FakeSession(uid_map, fail_second_batch=False)
        dl2 = PhageDatasetDownloader(data_dir, batch_size=2, min_length_bp=3000, retry_backoff_base=0.0, session=fake_ok)
        dl2._min_interval = 0.0
        summary = dl2.download_batch_dataset(target_count=3, queries=queries)

        assert summary["saved_count"] == 3
        assert summary["newly_downloaded"] == 1
        assert (data_dir / "gbk" / "NC_TEST_003.gbk").exists()
        assert (data_dir / "fasta" / "NC_TEST_003.fasta").exists()


def test_parallel_validator_and_sqlite_tsv_indexer():
    """验证多核并行校验能识别完整、损坏和缺配对记录，并正确构建 SQLite WAL 与 TSV 索引"""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "fasta").mkdir()
        (data_dir / "gbk").mkdir()

        # 1. 正常样本（含 integrase 标记与完整序列）
        gbk_ok = _build_synthetic_gbk("NC_VALID_01", length=3600, host="Salmonella enterica")
        (data_dir / "gbk" / "NC_VALID_01.gbk").write_text(gbk_ok, encoding="utf-8")
        fa_rec = SeqIO.read(__import__("io").StringIO(gbk_ok), "genbank")
        SeqIO.write(fa_rec, str(data_dir / "fasta" / "NC_VALID_01.fasta"), "fasta")

        # 2. 损坏样本（fasta 与 gbk 序列不一致）
        gbk_bad = _build_synthetic_gbk("NC_MISMATCH_02", length=3600)
        (data_dir / "gbk" / "NC_MISMATCH_02.gbk").write_text(gbk_bad, encoding="utf-8")
        (data_dir / "fasta" / "NC_MISMATCH_02.fasta").write_text(">NC_MISMATCH_02\n" + ("A" * 3500) + "\n", encoding="utf-8")

        # 3. 缺配对样本（仅有 fasta，无 gbk）
        (data_dir / "fasta" / "NC_ORPHAN_03.fasta").write_text(">NC_ORPHAN_03\n" + ("G" * 3600) + "\n", encoding="utf-8")

        validations = validate_dataset_parallel(data_dir, min_length_bp=3000, max_workers=1)
        by_acc = {v.accession: v for v in validations}

        assert by_acc["NC_VALID_01"].status == "passed"
        assert by_acc["NC_VALID_01"].has_integrase is True
        assert by_acc["NC_VALID_01"].has_capsid is True
        assert by_acc["NC_VALID_01"].host == "Salmonella enterica"
        assert by_acc["NC_VALID_01"].cds_count == 2

        assert by_acc["NC_MISMATCH_02"].status == "failed"
        assert any("sequence_mismatch" in e for e in by_acc["NC_MISMATCH_02"].errors)

        assert by_acc["NC_ORPHAN_03"].status == "failed"
        assert "missing_or_empty_gbk" in by_acc["NC_ORPHAN_03"].errors

        # 构建索引（跳过外部 makeblastdb 调用以保证纯离线快速单测）
        manifest = build_phage_dataset_indexes(data_dir, validations, build_blast_db=False)
        assert manifest["summary"]["passed_count"] == 1
        assert manifest["summary"]["failed_count"] == 2
        assert manifest["summary"]["genomes_with_integrase"] == 1

        sqlite_file = Path(manifest["artifacts"]["sqlite_index"])
        assert sqlite_file.exists()
        with closing(sqlite3.connect(sqlite_file)) as conn:
            row = conn.execute(
                "SELECT host, length_bp, has_integrase, status FROM genomes WHERE accession = ?",
                ("NC_VALID_01",),
            ).fetchone()
            assert row == ("Salmonella enterica", 3600, 1, "passed")

            cds_cnt = conn.execute(
                "SELECT COUNT(*) FROM cds_features WHERE accession = ?",
                ("NC_VALID_01",),
            ).fetchone()[0]
            assert cds_cnt == 2

        tsv_lines = Path(manifest["artifacts"]["tsv_index"]).read_text(encoding="utf-8").splitlines()
        assert len(tsv_lines) == 4  # header + 3 records
        assert "NC_VALID_01" in tsv_lines[1] or any("NC_VALID_01" in ln for ln in tsv_lines)

        manifest_json = json.loads((data_dir / "index" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest_json["summary"]["valid_genomes_count"] == 1


def test_indexer_handles_spaced_dir_and_path_tool_resolution(monkeypatch):
    """验证目录含空格且 ToolConfig.resolve_bio_tool 返回 Path 对象时，索引与 makeblastdb 参数构造均正常"""
    from src.utils.phage_dataset import indexer as indexer_mod

    captured_cmds = []

    def _fake_subproc_run(cmd, **kwargs):
        cwd_val = kwargs.get("cwd")
        captured_cmds.append((cmd, cwd_val))
        # 模拟 makeblastdb 在执行工作目录生成库索引文件
        out_name = cmd[cmd.index("-out") + 1]
        dbtype = cmd[cmd.index("-dbtype") + 1]
        ext = "nin" if dbtype == "nucl" else "pin"
        if cwd_val:
            (Path(cwd_val) / f"{out_name}.{ext}").write_bytes(b"mock-db-index")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(indexer_mod.ToolConfig, "resolve_bio_tool", lambda name: Path("/mock/bin/makeblastdb.exe"))
    monkeypatch.setattr(indexer_mod.subprocess, "run", _fake_subproc_run)

    with tempfile.TemporaryDirectory() as tmp:
        spaced_dir = Path(tmp) / "Phage data spaced"
        (spaced_dir / "fasta").mkdir(parents=True)
        (spaced_dir / "gbk").mkdir(parents=True)

        gbk_ok = _build_synthetic_gbk("NC_SPACED_01", length=3600)
        (spaced_dir / "gbk" / "NC_SPACED_01.gbk").write_text(gbk_ok, encoding="utf-8")
        fa_rec = SeqIO.read(__import__("io").StringIO(gbk_ok), "genbank")
        SeqIO.write(fa_rec, str(spaced_dir / "fasta" / "NC_SPACED_01.fasta"), "fasta")

        vals = validate_dataset_parallel(spaced_dir, min_length_bp=3000, max_workers=1)
        manifest = build_phage_dataset_indexes(spaced_dir, vals, build_blast_db=True)

        assert manifest["artifacts"]["blast_nucl_db_ready"] is True
        assert manifest["artifacts"]["blast_prot_db_ready"] is True
        assert isinstance(manifest["artifacts"]["makeblastdb_bin"], str)
        # 验证传给 makeblastdb 的 -in 和 -out 均使用纯文件名（不含空格路径）
        assert len(captured_cmds) == 2
        nucl_cmd, nucl_cwd = captured_cmds[0]
        assert nucl_cmd[nucl_cmd.index("-out") + 1] == "phage_refseq_nucl"
        assert nucl_cmd[nucl_cmd.index("-in") + 1] == "phage_refseq_nucl.fna"
        assert Path(nucl_cwd).name == "blastdb"
        assert " " not in str(nucl_cwd)
        assert (spaced_dir / "blastdb" / "phage_refseq_nucl.nin").exists()
        assert (spaced_dir / "blastdb" / "phage_refseq_prot.pin").exists()


def test_phage_identity_verification_filters_non_phages():
    """验证噬菌体真伪校验可正确识别有尾/非有尾噬菌体，并拦截真核病毒与细菌序列误混入。"""
    import io

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "fasta").mkdir()
        (data_dir / "gbk").mkdir()

        def _write_custom_record(acc: str, organism: str, taxonomy: list, host: str, product: str):
            seq = ("ATGAAAGCATTTGGGAAACCC" * 200)[:3600]
            rec = SeqRecord(Seq(seq), id=acc, name=acc, description=f"{organism}, complete genome")
            rec.annotations["molecule_type"] = "DNA"
            rec.annotations["topology"] = "linear"
            rec.annotations["organism"] = organism
            cast(Any, rec.annotations)["taxonomy"] = taxonomy
            src = SeqFeature(FeatureLocation(0, 3600, strand=1), type="source", qualifiers={"host": [host]} if host else {})
            cds = SeqFeature(
                FeatureLocation(0, 300, strand=1),
                type="CDS",
                qualifiers={"locus_tag": [f"{acc}_01"], "protein_id": [f"YP_{acc}"], "product": [product], "translation": ["MKAFGKP" * 14]},
            )
            rec.features = [src, cds]
            buf = io.StringIO()
            SeqIO.write(rec, buf, "genbank")
            (data_dir / "gbk" / f"{acc}.gbk").write_text(buf.getvalue(), encoding="utf-8")
            SeqIO.write(rec, str(data_dir / "fasta" / f"{acc}.fasta"), "fasta")

        # 1. 非有尾微小噬菌体（应通过且归类为 Microviridae）
        _write_custom_record(
            "NC_MICRO_01",
            "Escherichia phage phiX174",
            ["Viruses", "Monodnaviria", "Malgrandaviricetes", "Microviridae"],
            "Escherichia coli",
            "spike protein",
        )
        # 2. 人类真核病毒误混入（应拒绝）
        _write_custom_record(
            "NC_ADENO_02",
            "Human adenovirus C",
            ["Viruses", "Varidnaviria", "Adenoviridae"],
            "Homo sapiens",
            "hexon protein",
        )
        # 3. 细菌非病毒质粒误混入（应拒绝）
        _write_custom_record(
            "NC_BACT_03",
            "Escherichia coli plasmid pTest",
            ["Bacteria", "Pseudomonadota", "Enterobacteriaceae"],
            "",
            "plasmid replication protein",
        )

        vals = validate_dataset_parallel(data_dir, min_length_bp=3000, max_workers=1)
        by_acc = {v.accession: v for v in vals}

        assert by_acc["NC_MICRO_01"].status == "passed"
        assert by_acc["NC_MICRO_01"].is_phage is True
        assert by_acc["NC_MICRO_01"].phage_confidence == "high"
        assert by_acc["NC_MICRO_01"].phage_tax_group == "Microviridae"

        assert by_acc["NC_ADENO_02"].is_phage is False
        assert by_acc["NC_ADENO_02"].status == "failed"
        assert by_acc["NC_ADENO_02"].phage_confidence == "rejected"
        assert any("not_verified_as_phage" in e for e in by_acc["NC_ADENO_02"].errors)

        assert by_acc["NC_BACT_03"].is_phage is False
        assert by_acc["NC_BACT_03"].status == "failed"
        assert by_acc["NC_BACT_03"].phage_tax_group == "Non_Virus"

        manifest = build_phage_dataset_indexes(data_dir, vals, build_blast_db=False)
        assert manifest["summary"]["verified_phage_count"] == 1
        assert manifest["summary"]["rejected_non_phage_count"] == 2
        assert manifest["summary"]["valid_genomes_count"] == 1

        nucl_text = Path(manifest["artifacts"]["nucl_fasta"]).read_text(encoding="utf-8")
        assert "NC_MICRO_01" in nucl_text
        assert "NC_ADENO_02" not in nucl_text
        assert "NC_BACT_03" not in nucl_text
