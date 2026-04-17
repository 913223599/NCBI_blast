
import os
import subprocess
from pathlib import Path

class RotationChecker:
    @staticmethod
    def check_rotation(seq1_path: str, seq2_path: str, output_dir: str):
        """
        验证 seq1 和 seq2 是否互为旋转变体
        逻辑：将 seq1 倍增为 A+A，用 seq2 (B) 去比对。
        """
        from src.assembly.env.wsl_manager import WSLManager
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        doubled_fasta = os.path.abspath(os.path.join(output_dir, "seq1_doubled.fasta"))
        paf_out = os.path.abspath(os.path.join(output_dir, "alignment.paf"))
        seq2_abs = os.path.abspath(seq2_path)
        
        # 1. 物理倍增序列
        try:
            with open(seq1_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                header = lines[0].strip()
                seq_data = "".join([l.strip() for l in lines[1:]])
                # 记录原始长度用于后续百分比计算
                origin_len = len(seq_data)
                doubled_seq = seq_data + seq_data
                
            with open(doubled_fasta, 'w', encoding='utf-8') as f:
                f.write(f"{header} [DOUBLED]\n{doubled_seq}\n")
        except Exception as e:
            return {"success": False, "error": f"Failed to double sequence: {e}"}

        # 2. 调用 Minimap2 (跨系统路径转换)
        try:
            wsl_doubled = WSLManager.to_wsl_path(doubled_fasta)
            wsl_seq2 = WSLManager.to_wsl_path(seq2_abs)
            
            # 使用 -d Ubuntu 并在 root 下运行确保权限
            # 💡 增加 --cs 参数以获取碱基级别的差异详情
            cmd = ["wsl", "-d", "Ubuntu", "-u", "root", "minimap2", "-x", "asm5", "--cs", wsl_doubled, wsl_seq2]
            
            with open(paf_out, 'w', encoding='utf-8') as out_f:
                process = subprocess.run(
                    cmd, 
                    stdout=out_f, 
                    stderr=subprocess.PIPE, 
                    check=True, 
                    encoding='utf-8', 
                    errors='ignore'
                )
        except Exception as e:
            return {"success": False, "error": f"Minimap2 execution failed: {e}"}

        # 3. 解析 PAF
        return RotationChecker.parse_paf(paf_out, origin_len)

    @staticmethod
    def parse_paf(paf_path: str, target_len: int):
        if not os.path.exists(paf_path) or os.path.getsize(paf_path) == 0:
            return {"identity": 0, "rotated": False, "message": "未发现共线性比对匹配项", "blocks": [], "variants": []}

        blocks = []
        variants = [] # 存储具体的 SNP/Indel
        best_hit = None
        max_match = 0
        query_len = 0

        with open(paf_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.split('\t')
                if len(parts) < 12: continue
                
                # PAF columns: 0:qname, 1:qlen, 2:qstart, 3:qend, 4:strand, 5:tname, 6:tlen, 7:tstart, 8:tend, 9:nmatch, 10:nblock, 11:mapq
                q_len = int(parts[1])
                q_start = int(parts[2])
                q_end = int(parts[3])
                strand = parts[4]
                t_start = int(parts[7])
                t_end = int(parts[8])
                match_len = int(parts[9])
                block_len = int(parts[10])
                
                query_len = q_len
                identity = (match_len / block_len) * 100 if block_len > 0 else 0
                
                if block_len > 100:
                    blocks.append({
                        "qs": q_start, "qe": q_end,
                        "ts": t_start, "te": t_end,
                        "strand": strand,
                        "id": round(identity, 2)
                    })
                
                # 寻找 CS 标签并解析变异
                cs_tag = next((p for p in parts if p.startswith("cs:Z:")), None)
                if cs_tag and match_len > max_match:
                    variants = RotationChecker.parse_cs_string(cs_tag[5:], t_start)
                
                if match_len > max_match:
                    max_match = match_len
                    best_hit = parts

        if best_hit:
            match_len = int(best_hit[9])
            block_len = int(best_hit[10])
            identity = (match_len / block_len) * 100
            coverage = (match_len / query_len) * 100
            
            summary = {
                "success": True,
                "identity": round(identity, 2),
                "rotated": (coverage > 98 and identity > 99),
                "offset": int(best_hit[7]),
                "q_len": query_len,
                "t_len": target_len,
                "blocks": blocks,
                "variants": variants[:200], # 限制返回数量防止 UI 挂起
                "variant_count": len(variants),
                "message": ""
            }
            
            if summary["rotated"]:
                summary["message"] = f"检测到高度一致性 ({round(identity,2)}%)，且覆盖度完整。检出 {len(variants)} 处差异点。"
            else:
                summary["message"] = f"比对完成，相似度 {round(identity,2)}%，检出 {len(variants)} 处差异位点。"
            
            return summary
            
        return {"identity": 0, "rotated": False, "message": "解析比对结果失败", "blocks": [], "variants": []}

    @staticmethod
    def parse_cs_string(cs: str, start_pos: int) -> list:
        import re
        variants = []
        curr_ref_pos = start_pos
        tokens = re.findall(r'(:[0-9]+|\*[a-z][a-z]|\+[a-z]+|-[a-z]+)', cs)
        transitions = {('A','G'), ('G','A'), ('C','T'), ('T','C')}
        
        for token in tokens:
            op = token[0]
            if op == ':':
                length = int(token[1:])
                curr_ref_pos += length
            elif op == '*':
                ref, alt = token[1].upper(), token[2].upper()
                is_transition = (ref, alt) in transitions
                variants.append({
                    "pos": curr_ref_pos, "type": "SNP", "ref": ref, "alt": alt,
                    "assessment": "Transition" if is_transition else "Transversion", "len": 1
                })
                curr_ref_pos += 1
            elif op == '+':
                seq = token[1:].upper()
                variants.append({
                    "pos": curr_ref_pos, "type": "INS", "ref": "-", "alt": seq,
                    "assessment": f"Insertion ({len(seq)}bp)", "len": len(seq)
                })
            elif op == '-':
                seq = token[1:].upper()
                variants.append({
                    "pos": curr_ref_pos, "type": "DEL", "ref": seq, "alt": "-",
                    "assessment": f"Deletion ({len(seq)}bp)", "len": len(seq)
                })
                curr_ref_pos += len(seq)
        return variants

def detect_circular_identity(fasta_list: list):
    """
    对输入的多个 fasta 进行交叉验证
    """
    pass
