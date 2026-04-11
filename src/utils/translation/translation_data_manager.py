import csv
import logging
import os
import sqlite3
import threading
import sys
from pathlib import Path
from typing import Dict, Optional, List


class TranslationDataManager:
    """
    翻译数据管理器
    负责管理翻译数据的加载、存储和检索 - SQLite 后端
    """

    def preload(self):
        """
        [启动优化] 在 GUI 启动前确保数据库就绪。
        仅在首次运行或数据库由于损坏被重置时才显示迁移提示。
        """
        self._init_db()
        self._check_and_migrate_with_progress()

    def _check_and_migrate_with_progress(self):
        """带进度显示的迁移逻辑"""
        if self._get_count() > 0:
            return

        print(f"\n[!] 检测到新环境，正在将预置词库同步到 SQLite 数据库...", flush=True)

        csv_files = [
            self.project_root / "translation_data.csv",
            self.project_root / "predefined_terms.csv"
        ]
        
        total_files = sum(1 for f in csv_files if f.exists())
        if total_files == 0: return

        processed_files = 0
        migrated_count = 0
        from .term_extractor import TermExtractor
        extractor = TermExtractor()

        for csv_file in csv_files:
            if csv_file.exists():
                processed_files += 1
                try:
                    # 预读总行数以显示进度
                    with open(csv_file, 'r', encoding='utf-8') as f:
                        line_count = sum(1 for _ in f) - 1 # exclude header
                    
                    with open(csv_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        current_row = 0
                        for row in reader:
                            current_row += 1
                            english = row.get('english', '').strip()
                            chinese = row.get('chinese', '').strip()
                            category = row.get('category', 'other').strip() or 'other'
                            
                            if english and chinese:
                                if self._insert_if_not_exists(english, chinese, category, "migration"):
                                    migrated_count += 1
                            
                            # 每 100 行显式一次进度，避免性能损耗
                            if current_row % 100 == 0:
                                pct = int((current_row / line_count) * 100)
                                sys.stdout.write(f"\r -> [{processed_files}/{total_files}] 正在迁移 {csv_file.name}: {pct}%")
                                sys.stdout.flush()
                        
                        sys.stdout.write(f"\r -> [{processed_files}/{total_files}] 正在迁移 {csv_file.name}: 100% [完成]\n")
                        sys.stdout.flush()
                except Exception as e:
                    logging.error(f"迁移文件 {csv_file.name} 时出错: {e}")
        
        if migrated_count > 0:
            logging.info(f"数据迁移完成，共导入 {migrated_count} 条记录")

    def __init__(self):
        """
        初始化翻译数据管理器
        """
        # 强制使用固定文件名，防止外部传入非法路径（如 CSV 路径）导致锁冲突
        db_file = "translations.db"
        backup_file = "translations_backup.db"
        
        # 使用项目根目录为基准
        self.project_root = Path(__file__).resolve().parents[3]
        self.db_path = self.project_root / db_file
        self.backup_path = self.project_root / backup_file
        
        logging.info(f"翻译数据库初始化: A={self.db_path.name}, B={self.backup_path.name}")
        
        self._lock = threading.Lock()
        self._cache: Dict[str, dict] = {}
        
        # 1. 启动时的冷热备份恢复检查
        self._startup_recovery()
        
        # 2. 初始化数据库 (确保表结构)
        self._init_db()
        
        # [OPT] 持久化连接优化：在 Windows 下频繁 connect 会导致显著卡顿。
        # 使用单个持久连接并配合现有锁进行线程隔离。
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row # 使结果可通过列名访问
        
        # 3. 首次启动时自动迁移旧数据
        self._check_and_migrate_with_progress()

    def _check_integrity(self, path: Path) -> bool:
        """检查 SQLite 文件的完整性"""
        if not path.exists():
            return False
        try:
            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()[0]
            conn.close()
            return result == "ok"
        except Exception:
            return False

    def _sync_files(self, src: Path, dst: Path):
        """物理同步数据库文件"""
        try:
            import shutil
            if src.exists():
                shutil.copy2(src, dst)
                logging.info(f"数据库同步成功: {src.name} -> {dst.name}")
        except Exception as e:
            logging.error(f"同步数据库失败: {e}")

    def _startup_recovery(self):
        """
        [冷热备份策略] 启动阶段的健康诊断与同步
        根据 A (热库) 和 B (冷库) 的健康状况决定同步方向
        """
        # 1. 检查物理存在但不健康的文件，主动清理
        if self.db_path.exists() and not self._check_integrity(self.db_path):
            logging.warning(f"检测到热库 A ({self.db_path.name}) 损坏，正在清理...")
            try:
                os.remove(self.db_path)
            except Exception as e:
                logging.error(f"无法删除损坏的热库文件: {e}")

        if self.backup_path.exists() and not self._check_integrity(self.backup_path):
            logging.warning(f"检测到冷库 B ({self.backup_path.name}) 损坏，正在清理...")
            try:
                os.remove(self.backup_path)
            except Exception as e:
                logging.error(f"无法删除损坏的冷库文件: {e}")

        # 2. 重新评估健康状态
        a_healthy = self._check_integrity(self.db_path)
        b_healthy = self._check_integrity(self.backup_path)

        logging.info(f"启动自愈诊断: 库A稳定={a_healthy}, 库B稳定={b_healthy}")

        # 情况1: 热库丢失/损坏已删，冷库完好 -> 从冷库恢复 A
        if not a_healthy and b_healthy:
            logging.warning("正在从稳定备份库 B 恢复数据到 A...")
            self._sync_files(self.backup_path, self.db_path)
        
        # 情况2: 热库完好，冷库丢失/损坏已删 -> 将 A 同步到 B 建立备份
        elif a_healthy and not b_healthy:
            logging.info("正在将当前热库 A 同步到冷库 B...")
            self._sync_files(self.db_path, self.backup_path)
            
        # 情况3: 两者均完好，但可能 B 更“全” (异常退出兜底)
        elif a_healthy and b_healthy:
            a_count = self._get_count_direct(self.db_path)
            b_count = self._get_count_direct(self.backup_path)
            if b_count > a_count:
                logging.warning(f"检测到冷库 B 条目 ({b_count}) 多于 A ({a_count})，执行恢复")
                self._sync_files(self.backup_path, self.db_path)
        
        # 情况4: 两者均不存在 -> 由后续 _init_db 创建并 _check_and_migrate 迁移

    def _get_count_direct(self, path: Path) -> int:
        """直接从指定路径获取行数，不使用实例连接"""
        try:
            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM translations')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def prepare_shutdown(self):
        """
        [冷热备份策略] 应用退出前的同步钩子
        将最新的热库 A 同步到备份库 B
        """
        logging.info("执行应用关闭同步逻辑 (A -> B)...")
        self._sync_files(self.db_path, self.backup_path)

    def _init_db(self):
        """初始化 SQLite 数据库表结构"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                # english 为规范化后的原文，作为主键
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS translations (
                        english TEXT PRIMARY KEY,
                        chinese TEXT NOT NULL,
                        category TEXT,
                        source TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # 创建索引优化分类查询
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON translations(category)')
                conn.commit()
                conn.close()
            except Exception as e:
                logging.error(f"初始化翻译数据库失败: {e}")

    def _insert_if_not_exists(self, english: str, chinese: str, category: str, source: str) -> bool:
        """[内部方法] 插入数据（如果不存在）"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO translations (english, chinese, category, source)
                VALUES (?, ?, ?, ?)
            ''', (english, chinese, category, source))
            changed = conn.total_changes > 0
            conn.commit()
            conn.close()
            return changed
        except Exception:
            return False

    def _get_count(self) -> int:
        """获取总行数"""
        try:
            # 迁移逻辑依然使用独立连接以确保原子性，或复用 _conn (需注意初始化顺序)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM translations')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def get_translation(self, english_text: str, category: str = None) -> Optional[str]:
        """
        获取中文翻译
        优先从内存缓存读取，缓存穿透则读库并回填
        """
        english_text = english_text.strip()
        if not english_text:
            return None

        # 1. 尝试内存缓存
        if english_text in self._cache:
            data = self._cache[english_text]
            # 优先返回分类匹配的
            if not category or data['category'] == category:
                return data['chinese']
            # 如果不匹配，继续走后面数据库逻辑尝试兜底

        # 2. 查询数据库
        try:
            # 使用持久连接提高响应速度
            with self._lock:
                cursor = self._conn.cursor()
                
                row = None
                # A. 尝试精确匹配（原文 + 分类）
                if category:
                    cursor.execute('SELECT chinese, category FROM translations WHERE english = ? AND category = ?', (english_text, category))
                    row = cursor.fetchone()
                
                # B. 如果 A 没找到且指定了分类，尝试兜底匹配（仅原文）
                if not row:
                    cursor.execute('SELECT chinese, category FROM translations WHERE english = ?', (english_text,))
                    row = cursor.fetchone()
                
                if row:
                    chinese, db_cat = row['chinese'], row['category']
                    # 回填缓存
                    self._cache[english_text] = {'chinese': chinese, 'category': db_cat}
                    return chinese
        except Exception as e:
            logging.error(f"查询翻译失败 ({english_text}): {e}")
        
        return None

    def add_translation(self, english: str, chinese: str, category: str = 'other', source: str = 'manual') -> bool:
        """添加或更新翻译条目"""
        english = english.strip()
        chinese = chinese.strip()
        if not english or not chinese:
            return False

        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute('''
                    INSERT INTO translations (english, chinese, category, source)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(english) DO UPDATE SET
                        chinese = excluded.chinese,
                        category = excluded.category,
                        source = excluded.source,
                        created_at = CURRENT_TIMESTAMP
                ''', (english, chinese, category, source))
                self._conn.commit()
                # 同步更新内存缓存
                self._cache[english] = {'chinese': chinese, 'category': category}
                return True
            except Exception as e:
                logging.error(f"保存翻译到 SQL 失败: {e}")
                return False

    def update_translation(self, english: str, chinese: str, category: str = 'species'):
        """更新翻译条目（别名）"""
        self.add_translation(english, chinese, category)

    def contains(self, english_text: str, category: str = None) -> bool:
        """检查是否存在"""
        return self.get_translation(english_text, category) is not None

    def get_all_terms(self) -> Dict[str, str]:
        """获取所有翻译条目（用于兼容旧界面）"""
        results = {}
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute('SELECT english, chinese FROM translations')
                for row in cursor.fetchall():
                    results[row['english']] = row['chinese']
        except Exception as e:
            logging.error(f"拉取全量翻译失败: {e}")
        return results

    def get_terms_by_category(self, category: str) -> Dict[str, str]:
        """按分类拉取"""
        results = {}
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT english, chinese FROM translations WHERE category = ?', (category,))
            for eng, chi in cursor.fetchall():
                results[eng] = chi
            conn.close()
        except Exception as e:
            logging.error(f"按类拉取翻译失败: {e}")
        return results

    def search_translations(self, query: str, limit: int = 50) -> List[Dict[str, str]]:
        """
        搜索翻译条目 (模糊匹配)
        返回: [{'english':..., 'chinese':..., 'category':..., 'source':...}, ...]
        """
        results = []
        if not query:
            return results
        
        try:
            with self._lock:
                cursor = self._conn.cursor()
                wildcard = f"%{query}%"
                # 搜索英文、中文或来源
                cursor.execute('''
                    SELECT english, chinese, category, source 
                    FROM translations 
                    WHERE english LIKE ? OR chinese LIKE ? OR source LIKE ?
                    LIMIT ?
                ''', (wildcard, wildcard, wildcard, limit))
                
                for row in cursor.fetchall():
                    results.append({
                        'english': row['english'],
                        'chinese': row['chinese'],
                        'category': row['category'],
                        'source': row['source']
                    })
        except Exception as e:
            logging.error(f"搜索翻译失败: {e}")
        return results

    def intelligent_repair_categories(self) -> dict:
        """
        智能修复分类：针对标记为 'other' 的条目，利用 TermExtractor 重新判定
        """
        results = {"total": 0, "fixed": 0, "remained": 0}
        from .term_extractor import TermExtractor
        extractor = TermExtractor()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. 找出所有分类为 'other' 的记录
            cursor.execute("SELECT english, chinese FROM translations WHERE category = 'other'")
            others = cursor.fetchall()
            results["total"] = len(others)
            
            updates = []
            for english, chinese in others:
                # 重新判定分类
                new_cat = extractor._determine_category(english)
                if new_cat != 'other':
                    updates.append((new_cat, english))
            
            # 2. 批量更新
            if updates:
                cursor.executemany("UPDATE translations SET category = ? WHERE english = ?", updates)
                conn.commit()
                results["fixed"] = len(updates)
                
                # 同步更新内存缓存
                with self._lock:
                    for new_cat, english in updates:
                        if english in self._cache:
                            self._cache[english]['category'] = new_cat
            
            conn.close()
            results["remained"] = results["total"] - results["fixed"]
            
        except Exception as e:
            logging.error(f"智能修复分类失败: {e}")
            
        return results

    def update_translation_entry(self, english: str, new_chinese: str, category: str = 'species') -> bool:
        """
        更新特定条目的中文翻译 (支持新增/覆盖)
        """
        return self.add_translation(english, new_chinese, category=category, source='manual_correction')


# 全局单例管理器实例
_global_data_manager = None
_manager_lock = threading.Lock()

def get_translation_data_manager() -> TranslationDataManager:
    """获取翻译数据管理器实例（单例模式）"""
    global _global_data_manager
    with _manager_lock:
        if _global_data_manager is None:
            _global_data_manager = TranslationDataManager()
        return _global_data_manager