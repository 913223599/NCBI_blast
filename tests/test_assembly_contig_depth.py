# -*- coding: utf-8 -*-
"""
test_assembly_contig_depth.py - Contig 独立测序深度解析、回溯与 API 合同测试
"""

import asyncio
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.assembly.utils.contig_depth import (
    _estimate_depths_kmer,
    backfill_manifest_contig_depths,
    clear_depth_cache,
    estimate_contig_depths,
)
from src.backend.routes import assembly as assembly_routes


def _make_seq(rng: random.Random, length: int) -> str:
    return "".join(rng.choices("ACGT", k=length))


def _rev_comp(seq: str) -> str:
    return seq.translate(str.maketrans("ACGT", "TGCA"))[::-1]


def _write_pe_reads(
    fq1_path: Path,
    fq2_path: Path,
    seq_counts: list,
    read_len: int = 100,
    insert_len: int = 250,
    seed: int = 123,
) -> None:
    rng = random.Random(seed)
    idx = 0
    with open(fq1_path, "w", encoding="utf-8") as f1, open(fq2_path, "w", encoding="utf-8") as f2:
        for _name, seq, pairs in seq_counts:
            max_start = max(0, len(seq) - insert_len)
            for _ in range(pairs):
                st = rng.randint(0, max_start) if max_start > 0 else 0
                frag = seq[st : st + insert_len]
                if len(frag) < read_len:
                    continue
                r1 = frag[:read_len]
                r2 = _rev_comp(frag[-read_len:])
                idx += 1
                f1.write(f"@r{idx}/1\n{r1}\n+\n{'I'*len(r1)}\n")
                f2.write(f"@r{idx}/2\n{r2}\n+\n{'I'*len(r2)}\n")


class TestAssemblyContigDepth(unittest.TestCase):
    def setUp(self):
        clear_depth_cache()

    def test_parse_fasta_does_not_broadcast_global_depth_to_multiple_contigs(self):
        with tempfile.TemporaryDirectory() as td:
            task_dir = Path(td)
            run_dir = task_dir / "assemblerstep" / "assembly_run"
            qc_dir = run_dir / "qc"
            qc_dir.mkdir(parents=True, exist_ok=True)

            fa = run_dir / "assembly.fasta"
            with open(fa, "w", encoding="utf-8") as f:
                f.write(">c1 length=3000 gc=50.00% circular=false\n" + ("AGTC" * 750) + "\n")
                f.write(">c2 length=2000 gc=50.00% circular=false\n" + ("CTGA" * 500) + "\n")

            with open(qc_dir / "fastp.json", "w", encoding="utf-8") as fj:
                json.dump({"summary": {"after_filtering": {"total_bases": 500000}}}, fj)

            stats, contigs = assembly_routes.parse_assembly_fasta_metrics(fa, task_dir)
            self.assertAlmostEqual(stats["avg_depth"], 100.0, places=1)
            self.assertEqual(len(contigs), 2)
            self.assertEqual(contigs[0]["depth"], 0.0)
            self.assertEqual(contigs[1]["depth"], 0.0)

    def test_parse_fasta_single_contig_inherits_global_depth(self):
        with tempfile.TemporaryDirectory() as td:
            task_dir = Path(td)
            run_dir = task_dir / "assemblerstep" / "assembly_run"
            qc_dir = run_dir / "qc"
            qc_dir.mkdir(parents=True, exist_ok=True)

            fa = run_dir / "assembly.fasta"
            with open(fa, "w", encoding="utf-8") as f:
                f.write(">c1 length=5000 gc=50.00% circular=true\n" + ("AGTC" * 1250) + "\n")

            with open(qc_dir / "fastp.json", "w", encoding="utf-8") as fj:
                json.dump({"summary": {"after_filtering": {"total_bases": 500000}}}, fj)

            stats, contigs = assembly_routes.parse_assembly_fasta_metrics(fa, task_dir)
            self.assertAlmostEqual(stats["avg_depth"], 100.0, places=1)
            self.assertEqual(len(contigs), 1)
            self.assertAlmostEqual(contigs[0]["depth"], 100.0, places=1)

    def test_get_assembly_result_reads_mean_depth_and_preserves_zero(self):
        with tempfile.TemporaryDirectory() as td:
            task_dir = Path(td)
            run_dir = task_dir / "assemblerstep" / "assembly_run"
            run_dir.mkdir(parents=True, exist_ok=True)

            rng = random.Random(7)
            s1 = _make_seq(rng, 2000)
            s2 = _make_seq(rng, 1000)
            fa = run_dir / "assembly.fasta"
            with open(fa, "w", encoding="utf-8") as f:
                f.write(f">scaf_1\n{s1}\n>scaf_2\n{s2}\n")

            # Case A: Hybrid manifest using mean_depth
            mf = run_dir / "assembly_manifest.json"
            with open(mf, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "total_contigs": 2,
                        "total_length_bp": 3000,
                        "avg_depth": 85.0,
                        "n50": 2000,
                        "gc_percent": 50.0,
                        "is_circular": True,
                        "contigs": [
                            {"name": "scaf_1", "length": 2000, "gc": 50.0, "circular": True, "mean_depth": 120.5},
                            {"name": "scaf_2", "length": 1000, "gc": 50.0, "circular": False, "mean_depth": 14.0},
                        ],
                    },
                    f,
                )

            with patch.object(assembly_routes.AssemblyStorage, "get_task_dir", return_value=task_dir), \
                 patch.object(assembly_routes.assembly_db, "get_task", return_value={"id": "t_hyb", "name": "t", "status": "completed"}), \
                 patch.object(assembly_routes.assembly_db, "update_task_metrics", return_value=None):
                res = asyncio.run(assembly_routes.get_assembly_result("t_hyb"))

            payload = res
            depths = {c["name"]: c["depth"] for c in payload["contigs"]}
            self.assertAlmostEqual(depths["scaf_1"], 120.5, places=1)
            self.assertAlmostEqual(depths["scaf_2"], 14.0, places=1)
            self.assertEqual(payload["contigs"][0]["sequence"], s1)

            # Case B: Partial 0.0 depth must NOT be overwritten by avg_depth
            with open(mf, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "total_contigs": 2,
                        "total_length_bp": 3000,
                        "avg_depth": 50.0,
                        "n50": 2000,
                        "gc_percent": 50.0,
                        "is_circular": False,
                        "contigs": [
                            {"name": "scaf_1", "length": 2000, "gc": 50.0, "circular": False, "depth": 75.0},
                            {"name": "scaf_2", "length": 1000, "gc": 50.0, "circular": False, "depth": 0.0},
                        ],
                    },
                    f,
                )

            with patch.object(assembly_routes.AssemblyStorage, "get_task_dir", return_value=task_dir), \
                 patch.object(assembly_routes.assembly_db, "get_task", return_value={"id": "t_lr", "name": "t", "status": "completed"}), \
                 patch.object(assembly_routes.assembly_db, "update_task_metrics", return_value=None):
                res_lr = asyncio.run(assembly_routes.get_assembly_result("t_lr"))

            depths_lr = {c["name"]: c["depth"] for c in res_lr["contigs"]}
            self.assertAlmostEqual(depths_lr["scaf_1"], 75.0, places=1)
            self.assertEqual(depths_lr["scaf_2"], 0.0)

    def test_depth_estimation_and_manifest_backfill_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            task_dir = Path(td)
            run_dir = task_dir / "assemblerstep" / "assembly_run"
            qc_dir = run_dir / "qc"
            qc_dir.mkdir(parents=True, exist_ok=True)

            rng = random.Random(99)
            seq_high = _make_seq(rng, 2500)
            seq_low = _make_seq(rng, 2500)

            fa = run_dir / "assembly.fasta"
            with open(fa, "w", encoding="utf-8") as f:
                f.write(f">ngcs_scaffold_1 length=2500 gc=50.00% circular=false\n{seq_high}\n")
                f.write(f">ngcs_scaffold_2 length=2500 gc=50.00% circular=false\n{seq_low}\n")

            fq1 = qc_dir / "clean_1.fq"
            fq2 = qc_dir / "clean_2.fq"
            # 30x on seq_high (~375 pairs * 200bp = 75,000bp / 2500bp = 30x)
            # 5x on seq_low (~63 pairs * 200bp = 12,600bp / 2500bp = 5x)
            _write_pe_reads(fq1, fq2, [("ngcs_scaffold_1", seq_high, 375), ("ngcs_scaffold_2", seq_low, 63)])

            # 1. Verify k-mer fallback distinguishes high vs low depth
            kmer_depths, kmer_src = _estimate_depths_kmer(
                [("ngcs_scaffold_1", seq_high), ("ngcs_scaffold_2", seq_low)],
                fq1,
                fq2,
                None,
            )
            self.assertEqual(kmer_src, "kmer_estimated")
            self.assertGreater(kmer_depths["ngcs_scaffold_1"], kmer_depths["ngcs_scaffold_2"] * 3.0)

            # 2. Verify primary estimator (minimap2 or kmer)
            est_depths, _ = estimate_contig_depths(fa, fq1, fq2)
            self.assertGreater(est_depths["ngcs_scaffold_1"], est_depths["ngcs_scaffold_2"] * 3.0)

            # 3. Verify manifest without contigs triggers backfill and caches result
            mf = run_dir / "assembly_manifest.json"
            with open(mf, "w", encoding="utf-8") as f:
                json.dump({"total_contigs": 2, "total_length_bp": 5000}, f)

            with patch.object(assembly_routes.AssemblyStorage, "get_task_dir", return_value=task_dir), \
                 patch.object(assembly_routes.assembly_db, "get_task", return_value={"id": "t_bf", "name": "t", "status": "completed"}), \
                 patch.object(assembly_routes.assembly_db, "update_task_metrics", return_value=None):
                res = asyncio.run(assembly_routes.get_assembly_result("t_bf"))

            data = res
            d_map = {c["name"]: c["depth"] for c in data["contigs"]}
            self.assertGreater(d_map["ngcs_scaffold_1"], d_map["ngcs_scaffold_2"] * 3.0)
            self.assertTrue(all(c.get("sequence") for c in data["contigs"]))

            saved_mf = json.loads(mf.read_text(encoding="utf-8"))
            self.assertEqual(len(saved_mf["contigs"]), 2)
            self.assertGreater(saved_mf["contigs"][0]["depth"], 0.0)


if __name__ == "__main__":
    unittest.main()
