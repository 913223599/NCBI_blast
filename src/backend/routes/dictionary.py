
import logging
import threading
import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from ..broadcaster import broadcaster

logger = logging.getLogger("api_server")
router = APIRouter(tags=["Dictionary"])

from ...utils.taxonomy_provider import get_taxonomy_provider

# ─── 模型定义 ─────────────────────────────────────────

class TranslateRequest(BaseModel):
    text: str
    category: str = "species"

class BatchTranslateRequest(BaseModel):
    texts: List[str]
    category: str = "species"

class DictTermRequest(BaseModel):
    english: str
    chinese: str
    category: str = "species"

# ─── 翻译接口 ─────────────────────────────────────────

@router.post("/api/translate/single")
async def translate_single(req: TranslateRequest):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        result = translator.translate_text(req.text, category=req.category)
        return {"original": req.text, "translated": result}
    except Exception as exc:
        return {"original": req.text, "translated": req.text, "error": str(exc)}

@router.post("/api/translate/batch")
async def translate_batch(req: BatchTranslateRequest):
    """批量翻译，结果通过 WebSocket 逐条推送"""
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()

        def worker():
            CHUNK_SIZE = 20
            chunks = [req.texts[i:i + CHUNK_SIZE] for i in range(0, len(req.texts), CHUNK_SIZE)]
            for chunk in chunks:
                try:
                    def on_ready(orig, tran):
                        broadcaster.broadcast_sync("translation_done", {
                            "original": orig, 
                            "translated": tran,
                            "success": tran != orig
                        })
                        
                    results = translator.translate_batch(chunk, category=req.category, on_result_ready=on_ready)
                    logger.info(f"批量翻译批次完成: 大小={len(chunk)}, 成功解析={len(results)}")
                except Exception as exc:
                    logger.error(f"批量翻译批次崩溃: {exc}", exc_info=True)

        threading.Thread(target=worker, daemon=True).start()
        logger.info(f"批量翻译任务已启动: 序列数={len(req.texts)}, 类别={req.category}")
        return {"status": "started", "count": len(req.texts)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

# ─── 词典管理 ─────────────────────────────────────────

@router.get("/api/dictionary/search")
async def search_dictionary(query: str, proofread_mode: bool = False):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if not data_mgr: return []
        
        conn = sqlite3.connect(data_mgr.db_path)
        cursor = conn.cursor()
        
        q = f"%{query}%"
        if proofread_mode:
            cursor.execute("SELECT english, chinese, category, source FROM translations WHERE (english LIKE ? OR chinese LIKE ?) AND (source != 'verified' OR source IS NULL) ORDER BY created_at DESC LIMIT 500", (q, q))
        else:
            cursor.execute("SELECT english, chinese, category, source FROM translations WHERE (english LIKE ? OR chinese LIKE ?) ORDER BY created_at DESC LIMIT 500", (q, q))
            
        terms = [{'english': r[0], 'chinese': r[1], 'category': r[2], 'source': r[3]} for r in cursor.fetchall()]
        conn.close()
        return terms
    except Exception as exc:
        logger.error(f"Dict search error: {exc}")
        return []

@router.get("/api/dictionary/all")
async def get_all_terms(
    proofread_mode: bool = False, 
    limit: int = 2000, 
    category: str = "all", 
    query: Optional[str] = None
):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if not data_mgr:
            return []
        conn = sqlite3.connect(data_mgr.db_path)
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if proofread_mode:
            conditions.append("(source != 'verified' OR source IS NULL)")
        if category != "all":
            conditions.append("category = ?")
            params.append(category)
        if query and query.strip():
            q = f"%{query.strip()}%"
            conditions.append("(english LIKE ? OR chinese LIKE ?)")
            params.extend([q, q])
            
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
            
        if limit == -1 or limit > 1000000:
            sql = f"SELECT english, chinese, category, source FROM translations {where_clause} ORDER BY created_at DESC"
            cursor.execute(sql, tuple(params))
        else:
            sql = f"SELECT english, chinese, category, source FROM translations {where_clause} ORDER BY created_at DESC LIMIT ?"
            cursor.execute(sql, tuple(params + [limit]))
            
        terms = [{'english': r[0], 'chinese': r[1], 'category': r[2], 'source': r[3]} for r in cursor.fetchall()]
        conn.close()
        return terms
    except Exception as exc:
        logger.error(f"Dict load error: {exc}")
        return []

@router.get("/api/dictionary/page")
async def get_dictionary_page(
    page: int = 1,
    limit: int = 100,
    query: Optional[str] = None,
    category: str = "all",
    proofread_mode: bool = False
):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if not data_mgr:
            return {"items": [], "total": 0, "page": page, "limit": limit}
            
        conn = sqlite3.connect(data_mgr.db_path)
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if proofread_mode:
            conditions.append("(source != 'verified' OR source IS NULL)")
            
        if category != "all":
            conditions.append("category = ?")
            params.append(category)
            
        if query and query.strip():
            q = f"%{query.strip()}%"
            conditions.append("(english LIKE ? OR chinese LIKE ?)")
            params.extend([q, q])
            
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
            
        # 1. 查询总条数
        count_sql = f"SELECT COUNT(*) FROM translations {where_clause}"
        cursor.execute(count_sql, tuple(params))
        total = cursor.fetchone()[0]
        
        # 2. 查询分页数据
        offset = (page - 1) * limit
        select_sql = f"SELECT english, chinese, category, source FROM translations {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        select_params = params + [limit, offset]
        cursor.execute(select_sql, tuple(select_params))
        
        terms = [{'english': r[0], 'chinese': r[1], 'category': r[2], 'source': r[3]} for r in cursor.fetchall()]
        conn.close()
        
        return {
            "items": terms,
            "total": total,
            "page": page,
            "limit": limit
        }
    except Exception as exc:
        logger.error(f"Dict page load error: {exc}")
        return {"items": [], "total": 0, "page": page, "limit": limit}


@router.get("/api/dictionary/stats")
async def get_dictionary_stats():
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if not data_mgr:
            return {"total": 0, "pending": 0}
            
        conn = sqlite3.connect(data_mgr.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM translations")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM translations WHERE source != 'verified' OR source IS NULL")
        pending = cursor.fetchone()[0]
        
        conn.close()
        return {"total": total, "pending": pending}
    except Exception as exc:
        logger.error(f"Dict stats error: {exc}")
        return {"total": 0, "pending": 0}

@router.post("/api/dictionary/save")
async def save_term(req: DictTermRequest):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        success = translator.translation_data_manager.add_translation(
            req.english, req.chinese, req.category, source='manual_web')
        if success:
            await broadcaster.broadcast("data_updated", {"module": "dictionary"})
        return {"success": success}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@router.delete("/api/dictionary/term")
async def delete_term(english: str = ""):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if data_mgr and data_mgr.db_path.exists():
            conn = sqlite3.connect(data_mgr.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM translations WHERE english = ?', (english,))
            success = conn.total_changes > 0
            conn.commit()
            conn.close()
            if english in data_mgr._cache:
                del data_mgr._cache[english]
            if success:
                await broadcaster.broadcast("data_updated", {"module": "dictionary"})
            return {"success": success}
        return {"success": False}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@router.post("/api/dictionary/verify")
async def verify_term(english: str = ""):
    from ...utils.translation.biology_translator import get_global_biology_translator
    try:
        translator = get_global_biology_translator()
        data_mgr = translator.translation_data_manager
        if data_mgr and data_mgr.db_path.exists():
            conn = sqlite3.connect(data_mgr.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE translations SET source = 'verified' WHERE english = ?", (english,))
            success = conn.total_changes > 0
            conn.commit()
            conn.close()
            if success:
                await broadcaster.broadcast("data_updated", {"module": "dictionary"})
            return {"success": success}
        return {"success": False}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@router.post("/api/taxonomy/audit")
async def audit_taxonomy_batch(req: BatchTranslateRequest):
    """
    通过本地 NCBI 数据库核实一组学名的真实 Rank
    """
    try:
        from ...utils.taxonomy_provider import get_taxonomy_provider
        provider = get_taxonomy_provider()
        if not provider.is_ready:
            return {"success": False, "error": "本地分类学数据库未就绪"}
        
        results = []
        for name in req.texts:
            details = provider.get_lineage_details(name)
            if not details:
                results.append({"name": name, "rank": "unknown", "valid": False})
                continue
            
            # 找到最具体的 rank（通常是最后一条）
            info = details[-1]
            results.append({
                "name": name,
                "rank": info["rank"],
                "taxid": info["taxid"],
                "valid": True
            })
            
        return {"success": True, "results": results}
    except Exception as exc:
        logger.error(f"Taxonomy audit error: {exc}")
        return {"success": False, "error": str(exc)}
