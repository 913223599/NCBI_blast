# -*- coding: utf-8 -*-
"""
test_pipeline_integration.py - 泛基因组流水线端到端集成测试
验证全基因组 DNA 读取、国际标准 OrthoANI 计算、UPGMA 聚类与前后端数据契约
"""

import sys
import unittest
import tempfile
import random
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.analysis.pan_genomics.engine import PanGenomicsEngine
from src.analysis.pan_genomics.types import PanGenomicsRunRequest, SampleInputItem


class TestPipelineIntegration(unittest.TestCase):
    def test_run_analysis_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            bases = ['A', 'C', 'G', 'T']
            random.seed(42)
            s1_seq = ''.join(random.choices(bases, k=4080))
            s2_seq = s1_seq[:4000] + 'AAAA' + s1_seq[4004:]
            s3_seq = ''.join(random.choices(bases, k=4080))

            gbk1 = td_path / 's1.gbk'
            gbk2 = td_path / 's2.gbk'
            gbk3 = td_path / 's3.gbk'

            def write_gbk(p, sid, dna):
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(f"LOCUS       {sid}                 {len(dna)} bp    DNA     circular BCT 08-SEP-2026\n"
                            f"FEATURES             Location/Qualifiers\n"
                            f"     source          1..{len(dna)}\n"
                            f"     CDS             1..300\n"
                            f"                     /locus_tag=\"{sid}_001\"\n"
                            f"                     /product=\"major capsid protein\"\n"
                            f"                     /translation=\"MKVLWAALLVTFLAGCQAKVEQAVETEPEPELRQQTEWQSGQ\"\n"
                            f"     CDS             301..600\n"
                            f"                     /locus_tag=\"{sid}_002\"\n"
                            f"                     /product=\"terminase large subunit\"\n"
                            f"                     /translation=\"MNIKESLKAISSAVELGIKSVEQIKDAVELGIKSVEQIKDAV\"\n"
                            f"ORIGIN\n"
                            f"        1 {dna}\n"
                            f"//\n")

            write_gbk(gbk1, 'phage_1', s1_seq)
            write_gbk(gbk2, 'phage_2', s2_seq)
            write_gbk(gbk3, 'phage_3', s3_seq)

            req = PanGenomicsRunRequest(
                samples=[
                    SampleInputItem(sample_id='phage_1', sample_name='Phage 1', source_type='external_file', file_path=str(gbk1), file_type='gbk'),
                    SampleInputItem(sample_id='phage_2', sample_name='Phage 2', source_type='external_file', file_path=str(gbk2), file_type='gbk'),
                    SampleInputItem(sample_id='phage_3', sample_name='Phage 3', source_type='external_file', file_path=str(gbk3), file_type='gbk')
                ]
            )

            engine = PanGenomicsEngine()
            res = engine.run_analysis(req)

            # 验证数据契约
            self.assertIn('phage_1', res.ani_matrix)
            self.assertEqual(res.ani_matrix['phage_1']['phage_1'], 100.0)

            # phage_1 与 phage_2 亲缘极近，ANI 应该在 99% 以上
            ani_1_2 = res.ani_matrix['phage_1']['phage_2']
            self.assertIsNotNone(ani_1_2)
            self.assertGreaterEqual(ani_1_2, 99.0)

            # phage_1 与 phage_3 异属远缘，ANI 为 None
            ani_1_3 = res.ani_matrix['phage_1']['phage_3']
            self.assertIsNone(ani_1_3)

            # 验证覆盖度
            assert res.af_matrix is not None
            self.assertIn('phage_1', res.af_matrix)
            self.assertEqual(res.af_matrix['phage_1']['phage_2'], 100.0)

            # 验证分类推断
            assert res.ani_taxonomy_matrix is not None
            self.assertIn("Same Species", res.ani_taxonomy_matrix['phage_1']['phage_2'])
            self.assertIn("Distinct Genus", res.ani_taxonomy_matrix['phage_1']['phage_3'])

            # 验证树结构正常且无错误
            assert res.ani_clustering is not None
            self.assertIsNotNone(res.ani_clustering)
            self.assertEqual(len(res.ani_clustering['ordered_ids']), 3)

            # 验证序列化
            dumped = res.model_dump()
            self.assertIsInstance(dumped, dict)


if __name__ == '__main__':
    unittest.main()
