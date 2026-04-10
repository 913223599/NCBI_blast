import csv
import re
import json
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

class CSVParserWorker(QThread):
    """
    异步 CSV 解析线程，防止大结果文件加载时 UI 挂起
    """
    finished = pyqtSignal(str)  # 成功完成，返回 JSON 字符串
    error = pyqtSignal(str)     # 出错
    
    def __init__(self, csv_path, limit=None):
        super().__init__()
        self.csv_path = csv_path
        self.limit = limit

    def run(self):
        try:
            csv_path_obj = Path(self.csv_path)
            if not csv_path_obj.exists():
                self.error.emit(f"File not found: {self.csv_path}")
                return

            data = []
            
            # [核心优化] 自动探测分隔符，防止分号格式导致的解析失败
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f_test:
                first_line = f_test.readline()
                delimiter = ';' if ';' in first_line and first_line.count(';') > first_line.count(',') else ','

            best_hits = {} # key: accession, value: hit_data
            
            with open(self.csv_path, 'r', encoding='utf-8-sig') as fobj:
                reader = csv.DictReader(fobj, delimiter=delimiter)
                for row in reader:
                    acc = row.get('访问号', 'N/A').strip()
                    
                    # 提取数值用于对比
                    try:
                        sim_str = row.get('相似度', '0%').replace('%', '').strip()
                        sim_val = float(sim_str)
                        e_val_str = row.get('E值', '10').replace('e', 'E')
                        e_val = float(e_val_str)
                    except:
                        sim_val = 0.0
                        e_val = 10.0

                    # 如果这个登录号已经存在，则开始竞争上岗
                    if acc in best_hits and acc != 'N/A':
                        old_hit = best_hits[acc]
                        # 相似度更高，或者相似度一样但 E 值更小，则替换
                        if sim_val > old_hit['_sim_val'] or (sim_val == old_hit['_sim_val'] and e_val < old_hit['_e_val']):
                            pass # 继续执行存入逻辑
                        else:
                            continue # 维持现状，跳过此行

                    raw_title = row.get('标题', 'Unknown')
                    if '>' in raw_title:
                        raw_title = raw_title.split('>')[0].strip()

                    clean_title = raw_title
                    gi_match = re.match(r'^gi\|\d+\|[a-z]+\|[A-Za-z0-9_.]+\|\s*', raw_title)
                    if gi_match:
                        clean_title = raw_title[gi_match.end():].strip()

                    gene_source = ''
                    source_patterns = [
                        r'(16S\s+ribosomal\s+RNA\s+gene)',
                        r'(23S\s+ribosomal\s+RNA\s+gene)',
                        r'(ITS\s+region)',
                        r'(chromosome[^,]*)',
                        r'(complete\s+genome)',
                        r'(genome\s+assembly)',
                    ]
                    for pattern in source_patterns:
                        source_match = re.search(pattern, clean_title, re.IGNORECASE)
                        if source_match:
                            gene_source = source_match.group(1)
                            break
                    
                    species_raw = row.get('物种', 'N/A').strip()
                    species_final = species_raw
                    if len(species_raw) < 4 or species_raw.lower() in ['newman', 'strain', 'str.', 'subsp.', 'aureus']:
                        match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+))', clean_title)
                        if match:
                            species_final = match.group(1)

                    hit_entry = {
                        'title': clean_title,
                        'len': row.get('长度', '0'),
                        'acc': acc,
                        'species': species_final,
                        'genus': row.get('属名', ''),
                        'strain': row.get('菌株', ''),
                        'gene_type': row.get('基因类型', ''),
                        'seq_type': row.get('序列类型', ''),
                        'host': row.get('宿主信息', ''),
                        'gene_source': gene_source,
                        'hsp_count': row.get('高得分片段对(HSPs)', '0'),
                        'evalue': row.get('E值', 'N/A'),
                        'align_len': row.get('比对长度', '0'),
                        'ident_count': row.get('相同碱基数', '0'),
                        'similarity': row.get('相似度', '0%'),
                        'gaps': row.get('缺口数', '0'),
                        'query_range': row.get('查询起始-结束', ''),
                        'hit_range': row.get('命中起始-结束', ''),
                        '_sim_val': sim_val, # 隐藏字段用于辅助排序
                        '_e_val': e_val
                    }
                    best_hits[acc] = hit_entry
                    
                    if self.limit and len(best_hits) >= self.limit:
                        break
            
            # 将字典转换回列表发送
            data = list(best_hits.values())
            
            # 在后台线程完成最后的序列化动作，减轻 UI 线程负担
            self.finished.emit(json.dumps(data))
            
        except Exception as e:
            self.error.emit(str(e))
