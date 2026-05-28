import os
import sys
import sqlite3
import time
import logging
from pathlib import Path

# 添加项目根目录到 sys.path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils.translation.translation_data_manager import get_translation_data_manager
from src.utils.taxonomy_provider import get_taxonomy_provider
from src.utils.translation.google_free_translator import GoogleFreeTranslator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TaxonomyAutoTranslator:
    def __init__(self, limit=None, ranks=None):
        self.translation_mgr = get_translation_data_manager()
        self.tax_provider = get_taxonomy_provider()
        self.translator = GoogleFreeTranslator()
        self.limit = limit
        self.ranks = ranks or ['species', 'genus', 'family']

    def run(self):
        logger.info("检查 Taxonomy 数据库就绪状态...")
        if not self.tax_provider.is_ready:
            logger.error("Taxonomy 数据库未就绪。")
            return

        db_path = self.tax_provider.db_path
        if not os.path.exists(db_path):
            logger.error(f"找不到 taxa.sqlite: {db_path}")
            return

        logger.info(f"正在从 taxa.sqlite 提取未翻译的学名 (目标分类: {self.ranks})")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 构建分类条件
        ranks_placeholder = ",".join(["?"] * len(self.ranks))
        query = f"SELECT spname, rank FROM species WHERE rank IN ({ranks_placeholder})"
        cursor.execute(query, self.ranks)
        
        # 优化：一次性加载本地库中已有的所有英文词条，避免在循环中执行 245 万次 SQL 查询导致假死
        logger.info("正在加载本地词库索引...")
        existing_terms = set()
        try:
            conn2 = sqlite3.connect(self.translation_mgr.db_path)
            c2 = conn2.cursor()
            c2.execute("SELECT english FROM translations")
            for r in c2.fetchall():
                existing_terms.add(r[0].lower())
            conn2.close()
        except Exception as e:
            logger.error(f"读取本地库索引失败: {e}")
            
        logger.info("索引加载完成，开始按流式读取并筛选词条 (防止内存溢出)...")
        
        to_translate = []
        seen_names = set()
        from src.utils.translation.term_extractor import TermExtractor
        extractor = TermExtractor()

        # 使用流式读取(迭代器)代替 fetchall() 以防内存崩溃
        for row in cursor:
            spname, rank = row
            if not spname or " " not in spname and rank == "species":
                pass
            
            # 过滤提取学术名（去掉编号/株系）
            normalized_name = extractor.normalize_term(spname)
            if not normalized_name or len(normalized_name) < 3:
                continue

            # 高效 O(1) 去重与存在性检查
            norm_lower = normalized_name.lower()
            if norm_lower not in existing_terms and norm_lower not in seen_names:
                seen_names.add(norm_lower)
                to_translate.append((normalized_name, rank))
                if self.limit and len(to_translate) >= self.limit:
                    break
                    
        conn.close()

        limit_text = str(self.limit) if self.limit else "无限制(全部)"
        
        log_file_path = os.path.join(project_root, "translation_progress.log")
        with open(log_file_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 本地缺失待翻译纯学术词条共: {len(to_translate)} 个 (当前限制: {limit_text})\n")

        if not to_translate:
            logger.info("没有需要翻译的新词条。")
            self.verify_translations(to_translate)
            return

        success_count = 0
        logger.info("开始调用 Google 免费翻译接口，进度将输出至 translation_progress.log")
        
        total = len(to_translate)
        batch_size = 100
        
        for i in range(0, total, batch_size):
            batch = to_translate[i:i+batch_size]
            batch_texts = [item[0] for item in batch]
            
            try:
                # 批量送往翻译
                translated_lines = self.translator.translate_batch(batch_texts)
                
                # 即使退化也会保证长度一致，但如果有极端网络故障返回空则跳过
                chn_text = None
                if len(translated_lines) == len(batch):
                    for j, item in enumerate(batch):
                        eng_text = item[0]
                        rank = item[1]
                        chn_text = translated_lines[j]
                        
                        if chn_text:
                            # 修正谷歌翻译在处理拉丁缩写时常犯的中文标点错误
                            chn_text = chn_text.replace('sp。', 'sp.').replace('aff。', 'aff.').replace('var。', 'var.').replace('subsp。', 'subsp.').replace('ssp。', 'ssp.')
                        
                        if chn_text:
                            self.translation_mgr.add_translation(eng_text, chn_text, category=rank, source='auto_google_web')
                            success_count += 1
                else:
                    logger.warning("翻译引擎返回的数据长度异常，跳过本批次。")
                
                # 记录进度
                current_count = min(i + batch_size, total)
                pct = int(current_count / total * 100)
                last_eng = batch_texts[-1][:50]
                last_chn = chn_text[:50] if 'chn_text' in locals() and chn_text else 'N/A'
                with open(log_file_path, "a", encoding="utf-8") as lf:
                    lf.write(f"[{pct}%] ({current_count}/{total}) 批量完成 - 最新示例: {last_eng} -> {last_chn}\n")
                
                # 批次之间的限速，之前是一条 0.5 秒，现在 20 条等 0.5 秒，速度飙升 20 倍
                time.sleep(0.5)
                
            except Exception as e:
                with open(log_file_path, "a", encoding="utf-8") as lf:
                    lf.write(f"[错误] 批次翻译中断 (起始词: {batch_texts[0]}): {e}\n")
                time.sleep(2) # 出错等久一点
                
        with open(log_file_path, "a", encoding="utf-8") as lf:
            lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 自动后台翻译任务完成！成功导入 {success_count}/{total} 条翻译。\n")
        
        # 运行后置校验
        self.verify_translations(to_translate)

    def verify_translations(self, attempted_list):
        """
        后置匹配检查是否有错漏
        """
        print("\n=================================")
        print("开始进行错漏匹配检查...")
        print("=================================")
        missed = []
        for eng_text, rank in attempted_list:
            res = self.translation_mgr.get_translation(eng_text)
            if not res or res.lower() == eng_text.lower():
                missed.append(eng_text)
                
        if missed:
            print(f"发现错漏！共有 {len(missed)} 个词条翻译失败或未能正确入库。")
            print("错漏样本 (前10条):")
            for m in missed[:10]:
                print(f" - {m}")
            print("您可以稍后再次运行脚本，系统会自动尝试补全这些漏网之鱼。")
        else:
            if attempted_list:
                print("完美！本次尝试的所有词条均已成功匹配并入库，无一错漏！")
            else:
                print("当前系统词库处于完整状态，无需核对新词条。")


if __name__ == "__main__":
    # 根据要求设定为全部 (limit=None)
    job = TaxonomyAutoTranslator(limit=None)
    job.run()
