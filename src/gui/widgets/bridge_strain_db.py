# -*- coding: utf-8 -*-
"""
WebBridge Mixin: 样本库 & 基因库 CRUD 接口
职责：所有与 strain.db / sequences.db 交互的 pyqtSlot
"""
import json

from PyQt6.QtCore import pyqtSlot

from src.backend.sequence_db import get_sequence_db_manager
from src.backend.strain_db import get_strain_db_manager


class StrainDBMixin:
    """样本数据库桥接 Mixin（含冰箱、记录、编码、基因库）"""

    # --- Strain Database Slots ---
    @pyqtSlot(str, result=bool)
    def db_save_freezer(self, freezer_json):
        try:
            data = json.loads(freezer_json)
            return get_strain_db_manager().save_freezer(data)
        except Exception as exc:
            self.logger.error(f"DB Error (Save Freezer): {exc}")
            return False

    @pyqtSlot(str, result=bool)
    def db_delete_freezer(self, freezer_id):
        return get_strain_db_manager().delete_freezer(freezer_id)

    @pyqtSlot(str, result=bool)
    def db_save_record(self, record_json):
        try:
            data = json.loads(record_json)
            return get_strain_db_manager().save_record(data)
        except Exception as exc:
            self.logger.error(f"DB Error (Save Record): {exc}")
            return False

    @pyqtSlot(str, result=bool)
    def db_delete_record(self, record_id):
        return get_strain_db_manager().delete_record(record_id)

    @pyqtSlot(str, result=bool)
    def db_save_code_lookup(self, lookup_json):
        try:
            data = json.loads(lookup_json)
            return get_strain_db_manager().save_sys_config('codeLookup', data)
        except Exception as exc:
            self.logger.error(f"DB Error (Save Code Lookup): {exc}")
            return False

    @pyqtSlot(result=str)
    def db_load_all(self):
        try:
            data = get_strain_db_manager().load_all_data()
            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            self.logger.error(f"DB Error (Load All): {exc}")
            return '{"freezers":[], "records":[]}'

    @pyqtSlot(result=bool)
    def db_clear_all(self):
        return get_strain_db_manager().clear_all()

    # --- Sequence (Gene) Database Slots ---
    @pyqtSlot(str, result=bool)
    def db_save_sequence(self, seq_json):
        try:
            data = json.loads(seq_json)
            return get_sequence_db_manager().save_sequence(data)
        except Exception as exc:
            self.logger.error(f"DB Error (Save Sequence): {exc}")
            return False

    @pyqtSlot(str, result=str)
    def db_load_sequences_by_sample(self, sample_id):
        try:
            data = get_sequence_db_manager().load_sequences_by_sample(sample_id)
            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            self.logger.error(f"DB Error (Load Sequences): {exc}")
            return "[]"

    @pyqtSlot(str, result=str)
    def db_search_sequences(self, keyword):
        try:
            data = get_sequence_db_manager().search_sequences(keyword)
            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            self.logger.error(f"DB Error (Search Sequences): {exc}")
            return "[]"

    @pyqtSlot(str, result=bool)
    def db_delete_sequence(self, seq_id):
        return get_sequence_db_manager().delete_sequence(seq_id)
