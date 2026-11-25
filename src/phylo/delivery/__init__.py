# -*- coding: utf-8 -*-
"""
PhyloCore 交付套件包：iTOL 注释模板生成、6 项质检审计与交付 ZIP 打包
"""
from .bundle_exporter import DeliveryBundleExporter
from .clade_detector import MonophyleticClade, detect_monophyletic_clades
from .itol_client import ItolBatchClient
from .itol_generator import ItolTemplateGenerator
from .label_formatter import clean_phage_description, enrich_node_metadata, format_leaf_label
from .publication_palettes import (
    PALETTES,
    JournalPalette,
    build_top_genus_palette,
    build_top_taxon_palette,
    choose_macro_taxon_rank,
    compute_nice_scale_bar,
    compute_ring_elbow_leaders,
    gc_value_to_hex,
    get_journal_palette,
    is_formal_taxon_name,
    pick_font_family,
)
from .publication_renderer import PublicationTreeRenderer
from .qc_auditor import PhageDeliveryQcAuditor
from .subtree_extractor import extract_query_focus_subtree

__all__ = [
    "DeliveryBundleExporter",
    "ItolBatchClient",
    "ItolTemplateGenerator",
    "JournalPalette",
    "MonophyleticClade",
    "PALETTES",
    "PublicationTreeRenderer",
    "PhageDeliveryQcAuditor",
    "build_top_genus_palette",
    "build_top_taxon_palette",
    "choose_macro_taxon_rank",
    "clean_phage_description",
    "compute_nice_scale_bar",
    "compute_ring_elbow_leaders",
    "detect_monophyletic_clades",
    "enrich_node_metadata",
    "extract_query_focus_subtree",
    "format_leaf_label",
    "gc_value_to_hex",
    "get_journal_palette",
    "is_formal_taxon_name",
    "pick_font_family",
]
