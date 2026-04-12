import os
import sys
import logging
import json
from pathlib import Path

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PopulatePathogens")

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils.taxonomy_provider import get_taxonomy_provider
from src.utils.taxonomy_sync_service import get_taxonomy_sync_service
from src.backend.strain_db import get_strain_db_manager

# 1. 定义常见病原菌属列表
PATHOGENIC_GENERA = [
    # 革兰氏阳性球菌
    "Staphylococcus", "Streptococcus", "Enterococcus",
    # 肠杆菌科/目
    "Escherichia", "Salmonella", "Shigella", "Klebsiella", "Enterobacter", 
    "Citrobacter", "Serratia", "Proteus", "Yersinia", "Morganella", "Providencia",
    # 非发酵/弧菌/气单胞菌
    "Pseudomonas", "Acinetobacter", "Stenotrophomonas", "Burkholderia",
    "Vibrio", "Aeromonas", "Plesiomonas",
    # 革兰氏阳性杆菌/分枝杆菌
    "Bacillus", "Listeria", "Corynebacterium", "Clostridium", "Mycobacterium", "Nocardia",
    # 呼吸道/动物源性/其他
    "Neisseria", "Haemophilus", "Campylobacter", "Helicobacter", "Legionella",
    "Bordetella", "Brucella", "Francisella", "Pasteurella", "Moraxella", "Mycoplasma"
]

def run_pre_encoding():
    tax_provider = get_taxonomy_provider()
    if not tax_provider.is_ready:
        logger.error("Taxonomy 数据库未就绪。请确保 ETE4 已完成离线数据库构建。")
        return

    # 获取 ETE4 实例
    ncbi = tax_provider.ncbi
    sync_service = get_taxonomy_sync_service()
    
    logger.info(f"开始为 {len(PATHOGENIC_GENERA)} 个属拉取全量种名进行预编码...")
    
    total_added = 0
    for genus in PATHOGENIC_GENERA:
        try:
            # 获取属的 TaxID
            name2id = ncbi.get_name_translator([genus])
            if not name2id:
                logger.warning(f"无法在数据库中找到属: {genus}，跳过。")
                continue
            
            genus_id = name2id[genus][0]
            # 获取所有后代 TaxID
            descendants = ncbi.get_descendant_taxa(genus_id, intermediate_nodes=False)
            if not descendants:
                # 有些属下面可能没有后代（虽然罕见），只对属本身进行一次同步
                sync_service.sync_taxonomy_from_name(genus)
                continue

            # 获取 Rank 信息进行过滤
            ranks = ncbi.get_rank(descendants)
            species_taxids = [tid for tid, rank in ranks.items() if rank == "species"]
            
            # 翻译回名称并进行去重
            species_names_dict = ncbi.get_taxid_translator(species_taxids)
            # 使用 set 去重，防止相同的 "Genus sp." 被处理成百上千次
            unique_species_names = set(species_names_dict.values())
            
            # 过滤掉噪点：只保留有意义的物种名，忽略不明确的 "sp." 或 "uncultured"
            filtered_names = [
                name for name in unique_species_names 
                if " sp." not in name and "uncultured" not in name.lower() and " environmental" not in name.lower()
            ]
            
            logger.info(f"属 [{genus}]: 原始提取 {len(unique_species_names)} 个名，过滤后保留 {len(filtered_names)} 个有效种。正在同步编码...")
            
            count = 0
            for sp_name in filtered_names:
                # 已经是标准学名，直接同步
                res = sync_service.sync_taxonomy_from_name(sp_name)
                if res.get('success'):
                    count += 1
            
            total_added += count
            logger.info(f"属 [{genus}]: 同步完成，成功预编码 {count} 项。")
            
        except Exception as e:
            logger.error(f"处理属 [{genus}] 时发生错误: {e}")

    logger.info(f"所有任务执行完毕！累计为对照编码库新增/更新了 {total_added} 个物种层级关系。")

if __name__ == "__main__":
    run_pre_encoding()
