"""
BLAST结果解析器模块
负责流式解析BLAST XML结果并提取关键生物学信息
"""

import re
from Bio.Blast import NCBIXML
from typing import Iterator, Dict, Any

class BlastXmlParser:
    """
    BLAST XML流式解析器
    将Regex提取逻辑封装在此，支持逐条处理以节省内存
    """

    def parse(self, result_handle) -> Iterator[Dict[str, Any]]:
        """
        流式解析BLAST XML结果
        
        Args:
            result_handle: 打开的文件句柄（必须是文本模式）
            
        Yields:
            Dict: 包含提取信息的扁平化字典（对应CSV的一行）
        """
        # NCBIXML.parse 返回迭代器，不会一次性加载整个文件
        for blast_record in NCBIXML.parse(result_handle):
            for alignment in blast_record.alignments:
                # 提取每个比对的元数据
                extracted_data = self._extract_metadata(alignment.title)
                
                # 处理每个HSP
                for hsp in alignment.hsps:
                    # 合并HSP特定数据
                    row_data = extracted_data.copy()
                    
                    # 计算百分比
                    identity_pct = (hsp.identities / hsp.align_length * 100) if hsp.align_length > 0 else 0
                    
                    # 填充HSP数据
                    row_data.update({
                        'length': alignment.length, # 序列总长
                        'hsps_count': 1, # 标记位
                        'e_value': hsp.expect,
                        'align_length': hsp.align_length,
                        'identities': hsp.identities,
                        'identity_pct': identity_pct,
                        'gaps': hsp.gaps,
                        'query_start': hsp.query_start,
                        'query_end': hsp.query_end,
                        'sbjct_start': hsp.sbjct_start,
                        'sbjct_end': hsp.sbjct_end
                    })
                    
                    yield row_data

    def _extract_metadata(self, title: str) -> Dict[str, str]:
        """
        从标题中提取生物学元数据 (访问号, 物种, 基因等)
        逻辑迁移自 result_converter.py
        """
        metadata = {
            'title': title,
            'accession': "",
            'species': "",
            'genus': "",
            'strain': "",
            'gene_type': "",
            'sequence_type': "",
            'host_info': ""
        }
        
        # 1. 提取访问号
        accession_match = re.search(r'gi\|.*?\|.*?\|([A-Za-z0-9_.]+)\|', title)
        if accession_match:
            metadata['accession'] = accession_match.group(1)
        else:
            other_match = re.search(r'([A-Za-z0-9_.]+)(?:\.[0-9]+)?', title)
            if other_match:
                metadata['accession'] = other_match.group(1)

        # 2. 提取基因类型 (核酸)
        gene_patterns = [
            r'((?:16S|23S|18S)\s+ribosomal\s+RNA(?:\s+gene)?)',
            r'(16S\s+rRNA\s+gene)',
            r'(ribosomal\s+RNA\s+gene)',
            r'(gene\s+for\s+16S\s+rRNA)'
        ]
        for p in gene_patterns:
            m = re.search(p, title, re.IGNORECASE)
            if m:
                metadata['gene_type'] = m.group(1)
                break

        # 3. 提取蛋白质类型 (仅当未找到核酸基因类型时)
        protein_patterns = [
            r'(hypothetical protein)', r'(conserved protein)', r'(protein\s+\w+)',
            r'(\w+\s+protein)', r'(uncharacterized protein)', r'(putative protein)',
            r'(PREDICTED:\s+\w+\s+protein)', r'(COA\s+protein)', r'(coat\s+protein)',
            r'(membrane\s+protein)', r'(transcription\s+factor)', r'(kinase)',
            r'(receptor)', r'(synthase)', r'(transferase)', r'(hydrolase)',
            r'(oxidase)', r'(reductase)', r'(ligase)', r'(synthetase)',
            r'(transporter)', r'(channel)', r'(permease)', r'(binding protein)',
            r'(regulatory protein)', r'(structural protein)', r'(enzyme)',
            r'(antigen)', r'(antibiotic resistance protein)', r'(toxin)',
            r'(virulence factor)', r'(pathogenicity island protein)', r'(transposase)',
            r'(integrase)', r'(replication protein)', r'(regulatory RNA)',
            r'(small RNA)', r'(non-coding RNA)', r'(tRNA)', r'(rRNA)',
            r'(mRNA)', r'(antisense RNA)'
        ]
        if not metadata['gene_type']:
            for p in protein_patterns:
                m = re.search(p, title, re.IGNORECASE)
                if m:
                    metadata['gene_type'] = m.group(1)
                    break

        # 4. 提取序列类型
        seq_patterns = [
            r'(partial|complete)\s+(?:sequence|genome|protein|gene)',
            r'(partial\s+16S\s+rRNA\s+gene)',
            r'(complete\s+ cds)', r'(partial\s+ cds)',
            r'(genomic\s+ DNA)', r'(mRNA\s+ sequence)',
            r'(coding\s+ sequence)', r'(CDS:\s+[^,]+)'
        ]
        for p in seq_patterns:
            m = re.search(p, title, re.IGNORECASE)
            if m:
                metadata['sequence_type'] = m.group(0)
                break

        # 5. 提取菌株
        strain_patterns = [
            r'(strain\s+[A-Za-z0-9\-._]+)', r'(isolate\s+[A-Za-z0-9\-._]+)',
            r'(clone\s+[A-Za-z0-9\-._]+)', r'(serotype\s+[A-Za-z0-9\-._]+)',
            r'(subtype\s+[A-Za-z0-9\-._]+)', r'(biotype\s+[A-Za-z0-9\-._]+)',
            r'(variant\s+[A-Za-z0-9\-._]+)', r'(subsp\.\s+[A-Za-z0-9\-._]+)',
            r'(pv\.\s+[A-Za-z0-9\-._]+)', r'(type\s+[A-Za-z0-9\-._]+)'
        ]
        for p in strain_patterns:
            m = re.search(p, title, re.IGNORECASE)
            if m:
                metadata['strain'] = m.group(1)
                break

        # 6. 提取物种和属名
        species_patterns = [
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(?:16S|23S|18S|rRNA|strain|isolate|clone)',
            r'([A-Z][a-z]+\s+[a-z]+)\s+(?:strain|isolate|clone|gene|protein)',
            r'([A-Z][a-z]+\s+[a-z]+)\s+(?:complete|partial|gene|protein)',
            r'([A-Z][a-z]+\s+[a-z]+)',
            r'(Uncultured\s+\w+)', r'(Environmental\s+sample)',
            r'(Synthetic\s+construct)', r'(Artificial\s+sequence)',
            r'(Vector\s+p[A-Z0-9]+)', r'([A-Z][a-z]+\s+phage)',
            r'(Bacteriophage\s+[A-Za-z0-9]+)', r'(Phage\s+[A-Za-z0-9]+)',
        ]
        for p in species_patterns:
            # 移除 re.IGNORECASE 以确保属名首字母大写，避免误匹配 gene for 等描述词
            m = re.search(p, title)
            if m:
                metadata['species'] = m.group(1)
                break

        # 7. 提取备选物种名 (方括号中的信息通常是 NCBI 格式下的物种名)
        host_m = re.search(r'\[([^\]]+)\]', title)
        if host_m:
            metadata['host_info'] = host_m.group(1)
            # 如果主物种名提取失败，使用方括号内的内容作为物种名
            if not metadata['species']:
                metadata['species'] = metadata['host_info']

        # 8. 补全属名 (基于最终确定的物种名)
        if metadata['species']:
            genus_m = re.search(r'^([A-Z][a-z]+)', metadata['species'])
            if genus_m:
                metadata['genus'] = genus_m.group(1)

        return metadata

# 向后兼容别名 (Backward Compatibility Alias)
BlastResultParser = BlastXmlParser