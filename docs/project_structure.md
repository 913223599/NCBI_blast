# NCBI BLAST Project Structure
> Status: Auto-generated (Filtered test and temp files)
> Time: 2026-04-14 14:40:03

```text
|-- .lingma
|   \-- rules
|       \-- PROJECT_RULES.md
|-- database
|   |-- 16S
|   |   |-- 16S_ribosomal_RNA-nucl-metadata.json
|   |   \-- 16S_ribosomal_RNA.tar.gz
|   \-- taxonomy
|       |-- taxcat
|       |   |-- categories.dmp
|       |   \-- taxcat_readme.txt
|       |-- taxdmp
|       |   |-- citations.dmp
|       |   |-- delnodes.dmp
|       |   |-- division.dmp
|       |   |-- gc.prt
|       |   |-- gencode.dmp
|       |   |-- images.dmp
|       |   |-- merged.dmp
|       |   |-- names.dmp
|       |   |-- nodes.dmp
|       |   \-- readme.txt
|       |-- taxa.sqlite
|       |-- taxa.sqlite.traverse.pkl
|       \-- taxdump.tar.gz
|-- docs
|   |-- node_studio_records
|   |   |-- implementation_plan.md
|   |   |-- task.md
|   |   \-- walkthrough.md
|   \-- project_structure.md
|-- electron-shell
|   |-- main.js
|   |-- package-lock.json
|   |-- package.json
|   \-- preload.js
|-- logs
|   \-- application_20260210_094116.log
|-- resources
|   \-- help
|       |-- database_manager.md
|       |-- history.md
|       |-- local_blast.md
|       |-- quick_start.md
|       |-- settings.md
|       \-- translation_debugger.md
|-- results
|   |-- 2026-04-14 11_01_19
|   |   |-- sequences
|   |   |   |-- 2.27F.SP604130470002.seq
|   |   |   |-- 3.27F.SP604130470003.seq
|   |   |   |-- 4.27F.SP604130470004.seq
|   |   |   |-- 5.27F.SP604130470005.seq
|   |   |   |-- 6.27F.SP604130470006.seq
|   |   |   |-- 7.27F.SP604130470007.seq
|   |   |   |-- 8.27F.SP604130470008.seq
|   |   |   \-- 9.27F.SP604130470009.seq
|   |   |-- 2_27F_SP604130470002.csv
|   |   |-- 3_27F_SP604130470003.csv
|   |   |-- 4_27F_SP604130470004.csv
|   |   |-- 5_27F_SP604130470005.csv
|   |   |-- 6_27F_SP604130470006.csv
|   |   |-- 7_27F_SP604130470007.csv
|   |   |-- 8_27F_SP604130470008.csv
|   |   |-- 9_27F_SP604130470009.csv
|   |   |-- batch_1776135744_0.xml
|   |   |-- batch_1776135744_1.xml
|   |   |-- batch_1776135744_2.xml
|   |   |-- batch_1776135744_3.xml
|   |   |-- batch_1776135744_4.xml
|   |   |-- batch_1776135744_5.xml
|   |   |-- batch_1776135744_6.xml
|   |   |-- batch_1776135744_7.xml
|   |   \-- params.json
|   |-- extracted
|   |   |-- staged_1776133097_28012
|   |   \-- staged_1776135674_28012
|   |-- tree_results
|   \-- tree_workspace
|       |-- 1.27F.SP604100380001.ab1
|       |-- 1.27F.SP604100380001.seq
|       |-- 2.27F.SP604100380002.ab1
|       |-- 2.27F.SP604100380002.seq
|       |-- 3.27F.SP604100380003.ab1
|       |-- 3.27F.SP604100380003.seq
|       \-- SP60410038(本次发送）.zip
|-- scripts
|   |-- download_externals.ps1
|   \-- generate_project_tree.ps1
|-- src
|   |-- analysis
|   |   |-- ncbi_tree_tool.py
|   |   \-- __init__.py
|   |-- backend
|   |   |-- routes
|   |   |   |-- blast.py
|   |   |   |-- common.py
|   |   |   |-- core.py
|   |   |   |-- dictionary.py
|   |   |   |-- settings.py
|   |   |   |-- strains.py
|   |   |   |-- taxonomy.py
|   |   |   |-- tree.py
|   |   |   \-- __init__.py
|   |   |-- utils
|   |   |   \-- blast_utils.py
|   |   |-- api_server.py
|   |   |-- broadcaster.py
|   |   |-- cleanup_translations.py
|   |   |-- diag_db.py
|   |   |-- fully_restore_config.py
|   |   |-- lan_share.py
|   |   |-- populate.py
|   |   |-- populate_pathogens.py
|   |   |-- restore_sources.py
|   |   |-- sequence_db.py
|   |   |-- strain_db.py
|   |   \-- upgrade_dictionaries.py
|   |-- blast
|   |   |-- database_manager.py
|   |   |-- engine.py
|   |   |-- executor.py
|   |   |-- local_blast.py
|   |   |-- manager.py
|   |   |-- parser.py
|   |   |-- result_converter.py
|   |   \-- __init__.py
|   |-- modules
|   |   \-- tooltip
|   |       |-- core
|   |       |   |-- TooltipConfig.js
|   |       |   |-- TooltipManager.js
|   |       |   \-- types.js
|   |       |-- handlers
|   |       |   |-- EventHandler.js
|   |       |   \-- PositionHandler.js
|   |       |-- styles
|   |       |   \-- tooltip.css
|   |       |-- ui
|   |       |   |-- DOMAdapter.js
|   |       |   \-- Renderer.js
|   |       |-- utils
|   |       |-- compat.js
|   |       |-- index.js
|   |       |-- README.md
|   |       \-- tooltip-fix.js
|   |-- resources
|   |   \-- locales
|   |       |-- en_US
|   |       |   |-- blast.json
|   |       |   |-- common.json
|   |       |   |-- dash.json
|   |       |   |-- help.json
|   |       |   |-- metadata.json
|   |       |   |-- node.json
|   |       |   |-- others.json
|   |       |   |-- param.json
|   |       |   |-- strain.json
|   |       |   \-- ui.json
|   |       \-- zh_CN
|   |           |-- blast.json
|   |           |-- common.json
|   |           |-- dash.json
|   |           |-- help.json
|   |           |-- metadata.json
|   |           |-- node.json
|   |           |-- others.json
|   |           |-- param.json
|   |           |-- strain.json
|   |           \-- ui.json
|   |-- utils
|   |   |-- translation
|   |   |   |-- biology_translator.py
|   |   |   |-- blast_result_translator.py
|   |   |   |-- classification_rules.json
|   |   |   |-- qwen_translator.py
|   |   |   |-- term_extractor.py
|   |   |   |-- translation_data_manager.py
|   |   |   \-- __init__.py
|   |   |-- config_manager.py
|   |   |-- environment_checker.py
|   |   |-- file_handler.py
|   |   |-- hash_checker.py
|   |   |-- help_manager.py
|   |   |-- taxonomy_provider.py
|   |   |-- taxonomy_sync_service.py
|   |   |-- ui_translation_manager.py
|   |   |-- universal_parser.py
|   |   \-- __init__.py
|   |-- web-next
|   |   |-- public
|   |   |   \-- vite.svg
|   |   |-- src
|   |   |   |-- assets
|   |   |   |   |-- styles
|   |   |   |   |   \-- global.css
|   |   |   |   |-- logo.svg
|   |   |   |   \-- vue.svg
|   |   |   |-- bridge
|   |   |   |   |-- electron-bridge.ts
|   |   |   |   |-- index.ts
|   |   |   |   \-- pyqt-bridge.ts
|   |   |   |-- components
|   |   |   |   |-- blast
|   |   |   |   |   |-- AlignmentMap.vue
|   |   |   |   |   |-- BlastDetailDialog.vue
|   |   |   |   |   |-- BlastHistoryPanel.vue
|   |   |   |   |   |-- BlastInputPanel.vue
|   |   |   |   |   |-- BlastParamsPanel.vue
|   |   |   |   |   |-- BlastResultsTable.vue
|   |   |   |   |   \-- BlastVisualModal.vue
|   |   |   |   |-- common
|   |   |   |   |   |-- NotificationStack.vue
|   |   |   |   |   |-- TranslateSplicer.vue
|   |   |   |   |   \-- UniversalUpload.vue
|   |   |   |   |-- layout
|   |   |   |   |   |-- AppHeader.vue
|   |   |   |   |   \-- AppSidebar.vue
|   |   |   |   |-- strain
|   |   |   |   |   |-- forms
|   |   |   |   |   |   |-- BaseMetadataForm.vue
|   |   |   |   |   |   |-- CellForm.vue
|   |   |   |   |   |   |-- GeneticForm.vue
|   |   |   |   |   |   |-- MicrobeForm.vue
|   |   |   |   |   |   |-- PhageForm.vue
|   |   |   |   |   |   |-- ProteinForm.vue
|   |   |   |   |   |   \-- VirusForm.vue
|   |   |   |   |   |-- list
|   |   |   |   |   |   |-- StrainListAdvancedSearch.vue
|   |   |   |   |   |   |-- StrainListContainer.vue
|   |   |   |   |   |   |-- StrainListTable.vue
|   |   |   |   |   |   \-- StrainListToolbar.vue
|   |   |   |   |   |-- AddFreezerDialog.vue
|   |   |   |   |   |-- BatchImportDialog.vue
|   |   |   |   |   |-- CodeLookupManager.vue
|   |   |   |   |   |-- DragDropOverlay.vue
|   |   |   |   |   |-- EditFreezerDialog.vue
|   |   |   |   |   |-- Freezer3DView.vue
|   |   |   |   |   |-- FreezerDetailPanel.vue
|   |   |   |   |   |-- FreezerSidebar.vue
|   |   |   |   |   |-- KeyboardShortcutsHelp.vue
|   |   |   |   |   |-- PositionActionsMenu.vue
|   |   |   |   |   |-- SampleCodeInput.vue
|   |   |   |   |   |-- SampleDetailDialog.vue
|   |   |   |   |   |-- SampleEntryDialog.vue
|   |   |   |   |   |-- SamplePositionBanner.vue
|   |   |   |   |   |-- SearchFilterPanel.vue
|   |   |   |   |   |-- SearchResultsList.vue
|   |   |   |   |   |-- SequenceEntryPanel.vue
|   |   |   |   |   |-- StatisticsPanel.vue
|   |   |   |   |   |-- StrainDetailPanel.vue
|   |   |   |   |   |-- StrainFilterPanel.vue
|   |   |   |   |   |-- StrainHistoryPanel.vue
|   |   |   |   |   |-- StrainImportPanel.vue
|   |   |   |   |   |-- StrainSidebar.vue
|   |   |   |   |   \-- StrainToolbar.vue
|   |   |   |   |-- ui
|   |   |   |   |   |-- BaseButton.vue
|   |   |   |   |   |-- BaseCard.vue
|   |   |   |   |   |-- BaseInput.vue
|   |   |   |   |   \-- BaseSelect.vue
|   |   |   |   \-- PhylotreeWidget.vue
|   |   |   |-- composables
|   |   |   |   |-- useBlastDetailViewer.ts
|   |   |   |   |-- useBlastResultHandler.ts
|   |   |   |   |-- useBlastTaskManager.ts
|   |   |   |   |-- useCodeGenerator.ts
|   |   |   |   |-- useCodeLookup.ts
|   |   |   |   |-- useSerialCounter.ts
|   |   |   |   |-- useTaxonomySync.ts
|   |   |   |   \-- useTree.ts
|   |   |   |-- core
|   |   |   |   \-- tree
|   |   |   |       |-- layout
|   |   |   |       |   \-- LayoutEngine.ts
|   |   |   |       |-- models
|   |   |   |       |   \-- TreeModel.ts
|   |   |   |       |-- renderer
|   |   |   |       |   |-- HybridRenderer.ts
|   |   |   |       |   |-- ScaleBarRenderer.ts
|   |   |   |       |   |-- TreeEdgeRenderer.ts
|   |   |   |       |   \-- ViewportController.ts
|   |   |   |       \-- vendor_phylotree
|   |   |   |           |-- .github
|   |   |   |           |   \-- workflows
|   |   |   |           |       |-- ci.yml
|   |   |   |           |       |-- codeql.yml
|   |   |   |           |       |-- docs-site.yml
|   |   |   |           |       \-- docs.yml
|   |   |   |           |-- bin
|   |   |   |           |   |-- phylotree-distance.js
|   |   |   |           |   |-- phylotree-mrca.js
|   |   |   |           |   |-- phylotree-neighbor-join.js
|   |   |   |           |   |-- phylotree-reroot.js
|   |   |   |           |   |-- phylotree-shuffle.js
|   |   |   |           |   |-- phylotree-tag.js
|   |   |   |           |   |-- phylotree-tips.js
|   |   |   |           |   |-- phylotree-validate.js
|   |   |   |           |   |-- phylotree.js
|   |   |   |           |   |-- root-to-tip.js
|   |   |   |           |   \-- tip-date-extractor.js
|   |   |   |           |-- data
|   |   |   |           |   |-- compartmentalization
|   |   |   |           |   |   |-- compartmentalized_NL_NP.csv
|   |   |   |           |   |   |-- compartmentalized_NL_NP.new
|   |   |   |           |   |   |-- multiple_BR_LG_LN.csv
|   |   |   |           |   |   |-- multiple_BR_LG_LN.new
|   |   |   |           |   |   |-- not_compartmentalized_CL_CP.csv
|   |   |   |           |   |   \-- not_compartmentalized_CL_CP.new
|   |   |   |           |   |-- EU3031.txt
|   |   |   |           |   |-- Flu_PB2.nwk.txt
|   |   |   |           |   |-- h1n1_pandemic.txt
|   |   |   |           |   |-- HCV3876.txt
|   |   |   |           |   |-- MERS.txt
|   |   |   |           |   \-- sequences.S.compressed.filtered.fas
|   |   |   |           |-- images
|   |   |   |           |   |-- bar.gif
|   |   |   |           |   \-- structure.gif
|   |   |   |           |-- src
|   |   |   |           |   |-- clustering
|   |   |   |           |   |   |-- cluster-picker.js
|   |   |   |           |   |   \-- phylopart.js
|   |   |   |           |   |-- formats
|   |   |   |           |   |   |-- beast.js
|   |   |   |           |   |   |-- newick.js
|   |   |   |           |   |   |-- nexml.js
|   |   |   |           |   |   |-- nexus.js
|   |   |   |           |   |   |-- phyloxml.js
|   |   |   |           |   |   \-- registry.js
|   |   |   |           |   |-- metrics
|   |   |   |           |   |   |-- center-of-tree.js
|   |   |   |           |   |   |-- compute-midpoint.js
|   |   |   |           |   |   |-- pairwise-distances.js
|   |   |   |           |   |   |-- root-to-tip.js
|   |   |   |           |   |   \-- sackins.js
|   |   |   |           |   |-- msa-parsers
|   |   |   |           |   |   \-- fasta.js
|   |   |   |           |   |-- render
|   |   |   |           |   |   |-- styles
|   |   |   |           |   |   |   \-- phylotree-menus.css
|   |   |   |           |   |   |-- cartesian.js
|   |   |   |           |   |   |-- clades.js
|   |   |   |           |   |   |-- coordinates.js
|   |   |   |           |   |   |-- draw.js
|   |   |   |           |   |   |-- edges.js
|   |   |   |           |   |   |-- event-emitter.js
|   |   |   |           |   |   |-- events.js
|   |   |   |           |   |   |-- helpers.js
|   |   |   |           |   |   |-- menus.js
|   |   |   |           |   |   |-- nodes.js
|   |   |   |           |   |   |-- options.js
|   |   |   |           |   |   |-- radial.js
|   |   |   |           |   |   |-- selection-sets.js
|   |   |   |           |   |   \-- unrooted.js
|   |   |   |           |   |-- branches.js
|   |   |   |           |   |-- export.js
|   |   |   |           |   |-- extract-dates.js
|   |   |   |           |   |-- index.js
|   |   |   |           |   |-- main.js
|   |   |   |           |   |-- max-parsimony.js
|   |   |   |           |   |-- neighbor-join.js
|   |   |   |           |   |-- nodes.js
|   |   |   |           |   |-- rooting.js
|   |   |   |           |   |-- transformations.js
|   |   |   |           |   \-- traversal.js
|   |   |   |           |-- types
|   |   |   |           |   \-- phylotree.d.ts
|   |   |   |           |-- .gitignore
|   |   |   |           |-- .tern-project
|   |   |   |           |-- alignment.fasta
|   |   |   |           |-- API.md
|   |   |   |           |-- CNAME
|   |   |   |           |-- CODE_OF_CONDUCT.md
|   |   |   |           |-- CONTRIBUTING.md
|   |   |   |           |-- eslint.config.mjs
|   |   |   |           |-- fasta_headers.txt
|   |   |   |           |-- favicon.ico
|   |   |   |           |-- functions
|   |   |   |           |-- index.html
|   |   |   |           |-- label-tree.bf
|   |   |   |           |-- LICENSE
|   |   |   |           |-- package-lock.json
|   |   |   |           |-- package.json
|   |   |   |           |-- phylotree.css
|   |   |   |           |-- README.md
|   |   |   |           |-- requirements.txt
|   |   |   |           |-- rollup.config.mjs
|   |   |   |           |-- sorted.txt
|   |   |   |           |-- sorted_headers.txt
|   |   |   |           |-- tips.txt
|   |   |   |           |-- tree.txt
|   |   |   |           \-- yarn.lock
|   |   |   |-- data
|   |   |   |   \-- builtinCodes.ts
|   |   |   |-- locales
|   |   |   |   \-- index.ts
|   |   |   |-- router
|   |   |   |   \-- index.ts
|   |   |   |-- stores
|   |   |   |   |-- strain
|   |   |   |   |   |-- actions-freezer.ts
|   |   |   |   |   |-- actions-import.ts
|   |   |   |   |   |-- actions-records.ts
|   |   |   |   |   |-- actions-sync.ts
|   |   |   |   |   |-- index.ts
|   |   |   |   |   |-- state.ts
|   |   |   |   |   \-- types.ts
|   |   |   |   |-- app.ts
|   |   |   |   |-- blast.ts
|   |   |   |   |-- sequence.ts
|   |   |   |   \-- strain.ts
|   |   |   |-- types
|   |   |   |   \-- codeSystem.ts
|   |   |   |-- utils
|   |   |   |   |-- mockStrainData.ts
|   |   |   |   \-- storage.ts
|   |   |   |-- views
|   |   |   |   |-- BlastView.vue
|   |   |   |   |-- DashboardView.vue
|   |   |   |   |-- HelpView.vue
|   |   |   |   |-- SettingsView.vue
|   |   |   |   |-- StrainView.vue
|   |   |   |   \-- TreeView.vue
|   |   |   |-- App.vue
|   |   |   \-- main.ts
|   |   |-- .gitignore
|   |   |-- index.html
|   |   |-- LABEL_DISPLAY_MODE_FIX_REPORT.md
|   |   |-- package-lock.json
|   |   |-- package.json
|   |   |-- README.md
|   |   |-- tsconfig.app.json
|   |   |-- tsconfig.json
|   |   |-- tsconfig.node.json
|   |   |-- verify_label_display_mode.js
|   |   \-- vite.config.ts
|   |-- workbench
|   |   |-- bin
|   |   |   |-- FastTree.exe
|   |   |   |-- mafft.exe
|   |   |   \-- muscle.exe
|   |   |-- models
|   |   |   |-- annotation_manager.py
|   |   |   |-- gpu_manager.py
|   |   |   |-- task_manager.py
|   |   |   |-- tool_config.py
|   |   |   \-- __init__.py
|   |   |-- pipelines
|   |   |   |-- analysis_pipeline.py
|   |   |   \-- __init__.py
|   |   |-- wrappers
|   |   |   |-- base_wrapper.py
|   |   |   |-- iqtree_wrapper.py
|   |   |   |-- mafft_wrapper.py
|   |   |   |-- mrbayes_wrapper.py
|   |   |   |-- tree_archive_manager.py
|   |   |   |-- tree_builder.py
|   |   |   |-- tree_distance_calculator.py
|   |   |   |-- tree_factory.py
|   |   |   |-- tree_format_converter.py
|   |   |   |-- tree_id_manager.py
|   |   |   |-- tree_sequence_processor.py
|   |   |   \-- __init__.py
|   |   \-- __init__.py
|   |-- pyrightconfig.json
|   |-- __init__.py
|   \-- __main__.py
|-- storage
|   \-- web
|       |-- blob_storage
|       |   \-- 22e05973-3db4-4426-8d39-394221c96425
|       |-- DawnGraphiteCache
|       |   |-- data_0
|       |   |-- data_1
|       |   |-- data_2
|       |   |-- data_3
|       |   \-- index
|       |-- DawnWebGPUCache
|       |   |-- data_0
|       |   |-- data_1
|       |   |-- data_2
|       |   |-- data_3
|       |   \-- index
|       |-- GPUCache
|       |   |-- data_0
|       |   |-- data_1
|       |   |-- data_2
|       |   |-- data_3
|       |   \-- index
|       |-- Local Storage
|       |   \-- leveldb
|       |       |-- 000137.ldb
|       |       |-- 000139.ldb
|       |       |-- 000142.log
|       |       |-- 000143.ldb
|       |       |-- CURRENT
|       |       |-- LOCK
|       |       |-- LOG
|       |       |-- LOG.old
|       |       \-- MANIFEST-000001
|       |-- Session Storage
|       |   |-- 000004.log
|       |   |-- 000005.ldb
|       |   |-- CURRENT
|       |   |-- LOCK
|       |   |-- LOG
|       |   |-- LOG.old
|       |   \-- MANIFEST-000001
|       |-- Shared Dictionary
|       |   |-- cache
|       |   |   |-- index-dir
|       |   |   |   \-- the-real-index
|       |   |   \-- index
|       |   |-- db
|       |   \-- db-journal
|       |-- Cookies
|       |-- Cookies-journal
|       |-- Favicons
|       |-- Favicons-journal
|       |-- History
|       |-- History-journal
|       |-- Network Persistent State
|       |-- SharedStorage
|       |-- Trust Tokens
|       |-- Trust Tokens-journal
|       |-- user_prefs.json
|       \-- Visited Links
|-- temp_uploads
|-- tools
|   |-- docs
|   |   |-- detailed
|   |   |   |-- abi-dump.exe.txt
|   |   |   |-- additive.exe.txt
|   |   |   |-- align-info.exe.txt
|   |   |   |-- align2html.exe.txt
|   |   |   |-- ascii.exe.txt
|   |   |   |-- asm_gap.exe.txt
|   |   |   |-- asnt.exe.txt
|   |   |   |-- asnt2tree.exe.txt
|   |   |   |-- blast2ani.exe.txt
|   |   |   |-- blast2cons.exe.txt
|   |   |   |-- blastmat.exe.txt
|   |   |   |-- blastn2mlst.exe.txt
|   |   |   |-- blastp2exons.exe.txt
|   |   |   |-- blastp_merge.exe.txt
|   |   |   |-- blast_best_hits.exe.txt
|   |   |   |-- cache-mgr.exe.txt
|   |   |   |-- check-corrupt.exe.txt
|   |   |   |-- combine_dissims.exe.txt
|   |   |   |-- compareTrees.exe.txt
|   |   |   |-- connectPairs.exe.txt
|   |   |   |-- contig2read_coverage.exe.txt
|   |   |   |-- conv_comb.exe.txt
|   |   |   |-- csv2tab.exe.txt
|   |   |   |-- disruption2genesymbol.exe.txt
|   |   |   |-- distTree_new.exe.txt
|   |   |   |-- distTree_refresh_dissim.exe.txt
|   |   |   |-- dm2feature.exe.txt
|   |   |   |-- dna2prots.exe.txt
|   |   |   |-- dna2stat.exe.txt
|   |   |   |-- dna_align_service.exe.txt
|   |   |   |-- dna_complexity.exe.txt
|   |   |   |-- dna_consensus.exe.txt
|   |   |   |-- dna_coverage.exe.txt
|   |   |   |-- dna_cut.exe.txt
|   |   |   |-- dna_diff.exe.txt
|   |   |   |-- dna_find.exe.txt
|   |   |   |-- dna_gc_skew.exe.txt
|   |   |   |-- dna_pair2dissim.exe.txt
|   |   |   |-- dna_rev.exe.txt
|   |   |   |-- dna_trim.exe.txt
|   |   |   |-- effectiveSize.exe.txt
|   |   |   |-- extractPairs.exe.txt
|   |   |   |-- fasta2dissim.exe.txt
|   |   |   |-- fasta2feature.exe.txt
|   |   |   |-- fasta2GC.exe.txt
|   |   |   |-- fasta2hash.exe.txt
|   |   |   |-- fasta2len.exe.txt
|   |   |   |-- fasta2lines.exe.txt
|   |   |   |-- fastaAddGi.exe.txt
|   |   |   |-- fastaDna2pairs.exe.txt
|   |   |   |-- fasta_prefix.exe.txt
|   |   |   |-- fasterq-dump-driver.exe.txt
|   |   |   |-- fasterq-dump.exe.txt
|   |   |   |-- fastq-dump.exe.txt
|   |   |   |-- feature2dissim.exe.txt
|   |   |   |-- feature2gain_loss.exe.txt
|   |   |   |-- feature_request2dissim.exe.txt
|   |   |   |-- file2hash.exe.txt
|   |   |   |-- filterFasta.exe.txt
|   |   |   |-- fixed2tsv.exe.txt
|   |   |   |-- genbank_grep.exe.txt
|   |   |   |-- GeneMark2CDS.exe.txt
|   |   |   |-- hash2dissim.exe.txt
|   |   |   |-- hash_request2dissim.exe.txt
|   |   |   |-- hello.exe.txt
|   |   |   |-- hmm2prot.exe.txt
|   |   |   |-- hmmAddCutoff.exe.txt
|   |   |   |-- hmmExtract.exe.txt
|   |   |   |-- hmmNAME2ACC.exe.txt
|   |   |   |-- hmmsearch2besthits.exe.txt
|   |   |   |-- hmmSplit.exe.txt
|   |   |   |-- hmm_tc1.exe.txt
|   |   |   |-- illumina-dump.exe.txt
|   |   |   |-- index_find.exe.txt
|   |   |   |-- interSeq.exe.txt
|   |   |   |-- islander.exe.txt
|   |   |   |-- kdbmeta.exe.txt
|   |   |   |-- kmerIndex_add.exe.txt
|   |   |   |-- kmerIndex_find.exe.txt
|   |   |   |-- kmerIndex_make.exe.txt
|   |   |   |-- kmerIndex_stat.exe.txt
|   |   |   |-- list2pairs.exe.txt
|   |   |   |-- loci_request2dissim.exe.txt
|   |   |   |-- main_ortholog.exe.txt
|   |   |   |-- makeDistTree.exe.txt
|   |   |   |-- makeFeatureTree.exe.txt
|   |   |   |-- mergePairs.exe.txt
|   |   |   |-- min_spanning_forest.exe.txt
|   |   |   |-- mlst2dissim.exe.txt
|   |   |   |-- mlst2hash.exe.txt
|   |   |   |-- multilist2subset.exe.txt
|   |   |   |-- mutation2feature.exe.txt
|   |   |   |-- mutation_dna2prot.exe.txt
|   |   |   |-- mutation_tab.exe.txt
|   |   |   |-- newick2tree.exe.txt
|   |   |   |-- ngs-pileup.exe.txt
|   |   |   |-- objHash_find.exe.txt
|   |   |   |-- orf2prot.exe.txt
|   |   |   |-- orthodb2fasta.exe.txt
|   |   |   |-- pairs2tsv.exe.txt
|   |   |   |-- prefetch.exe.txt
|   |   |   |-- printDistTree.exe.txt
|   |   |   |-- prot2triplets.exe.txt
|   |   |   |-- prots2hmm_signature.exe.txt
|   |   |   |-- prots_pair2stat.exe.txt
|   |   |   |-- prot_check.exe.txt
|   |   |   |-- prot_clust.exe.txt
|   |   |   |-- prot_collection2dissim.exe.txt
|   |   |   |-- prot_complexity.exe.txt
|   |   |   |-- prot_consensus.exe.txt
|   |   |   |-- prot_find.exe.txt
|   |   |   |-- prot_grep_short.exe.txt
|   |   |   |-- randomDistTree.exe.txt
|   |   |   |-- random_words.exe.txt
|   |   |   |-- rcexplain.exe.txt
|   |   |   |-- ref-variation.exe.txt
|   |   |   |-- replaceDistTree_match.exe.txt
|   |   |   |-- replaceDistTree_reroot.exe.txt
|   |   |   |-- replaceFastaHeader.exe.txt
|   |   |   |-- replace_dict.exe.txt
|   |   |   |-- sam-dump-driver.exe.txt
|   |   |   |-- sam-dump.exe.txt
|   |   |   |-- seq2dissim.exe.txt
|   |   |   |-- seq_print.exe.txt
|   |   |   |-- setMinus.exe.txt
|   |   |   |-- setRandOrd.exe.txt
|   |   |   |-- sff-dump.exe.txt
|   |   |   |-- splitFasta.exe.txt
|   |   |   |-- splitList.exe.txt
|   |   |   |-- sra-info.exe.txt
|   |   |   |-- sra-pileup-driver.exe.txt
|   |   |   |-- sra-pileup.exe.txt
|   |   |   |-- sra-search.exe.txt
|   |   |   |-- sra-stat.exe.txt
|   |   |   |-- srapath.exe.txt
|   |   |   |-- sratools.exe.txt
|   |   |   |-- statDistTree.exe.txt
|   |   |   |-- str2hash.exe.txt
|   |   |   |-- symbet.exe.txt
|   |   |   |-- symbet_blastp.exe.txt
|   |   |   |-- tblastn2disruption.exe.txt
|   |   |   |-- tblastn2marker_euk.exe.txt
|   |   |   |-- tblastn2orfs.exe.txt
|   |   |   |-- trav.exe.txt
|   |   |   |-- tree2genogroup.exe.txt
|   |   |   |-- tree2indiscern.exe.txt
|   |   |   |-- triple2tsv.exe.txt
|   |   |   |-- tsv2html.exe.txt
|   |   |   |-- tsv2insert.exe.txt
|   |   |   |-- tsv2triple.exe.txt
|   |   |   |-- tsv_aggr_comp.exe.txt
|   |   |   |-- tsv_cat.exe.txt
|   |   |   |-- tsv_cluster.exe.txt
|   |   |   |-- tsv_comp.exe.txt
|   |   |   |-- tsv_group.exe.txt
|   |   |   |-- tsv_join.exe.txt
|   |   |   |-- tsv_null.exe.txt
|   |   |   |-- tsv_rename.exe.txt
|   |   |   |-- tsv_schema.exe.txt
|   |   |   |-- tsv_shift.exe.txt
|   |   |   |-- tsv_split.exe.txt
|   |   |   |-- uniqProtRef.exe.txt
|   |   |   |-- uniqSeq.exe.txt
|   |   |   |-- var-expand.exe.txt
|   |   |   |-- vdb-config.exe.txt
|   |   |   |-- vdb-decrypt.exe.txt
|   |   |   |-- vdb-dump-driver.exe.txt
|   |   |   |-- vdb-dump.exe.txt
|   |   |   |-- vdb-encrypt.exe.txt
|   |   |   |-- vdb-validate.exe.txt
|   |   |   |-- xml2schema.exe.txt
|   |   |   |-- xml_bin2txt.exe.txt
|   |   |   |-- xml_find.exe.txt
|   |   |   |-- xml_merge_schemas.exe.txt
|   |   |   |-- xml_print.exe.txt
|   |   |   |-- xml_schema2ddl.exe.txt
|   |   |   |-- xml_schema2flat.exe.txt
|   |   |   \-- xml_txt2bin.exe.txt
|   |   |-- ncbi-vdb.txt
|   |   |-- ngs-sdk.txt
|   |   |-- sra-tools.txt
|   |   \-- tree-tools.txt
|   |-- iqtree3_win
|   |   \-- iqtree-3.1.1-Windows
|   |       |-- bin
|   |       |   |-- iqtree3-click.exe
|   |       |   |-- iqtree3.exe
|   |       |   \-- libiomp5md.dll
|   |       |-- example.cf
|   |       |-- example.nex
|   |       |-- example.phy
|   |       \-- models.nex
|   |-- iqtree_new
|   |   \-- iqtree-2.4.0-Windows
|   |       |-- bin
|   |       |   |-- iqtree2-click.exe
|   |       |   |-- iqtree2.exe
|   |       |   \-- libiomp5md.dll
|   |       |-- example.cf
|   |       |-- example.nex
|   |       |-- example.phy
|   |       \-- models.nex
|   |-- mafft
|   |   \-- mafft-win
|   |       |-- tmp
|   |       |-- usr
|   |       |   |-- bin
|   |       |   |   |-- awk.exe
|   |       |   |   |-- basename.exe
|   |       |   |   |-- bash.exe
|   |       |   |   |-- cat.exe
|   |       |   |   |-- chmod.exe
|   |       |   |   |-- comm.exe
|   |       |   |   |-- cp.exe
|   |       |   |   |-- cut.exe
|   |       |   |   |-- date.exe
|   |       |   |   |-- dirname.exe
|   |       |   |   |-- echo.exe
|   |       |   |   |-- env.exe
|   |       |   |   |-- expr.exe
|   |       |   |   |-- false.exe
|   |       |   |   |-- file.exe
|   |       |   |   |-- fold.exe
|   |       |   |   |-- grep.exe
|   |       |   |   |-- gzip.exe
|   |       |   |   |-- head.exe
|   |       |   |   |-- id.exe
|   |       |   |   |-- info.exe
|   |       |   |   |-- join.exe
|   |       |   |   |-- ln.exe
|   |       |   |   |-- ls.exe
|   |       |   |   |-- mafft
|   |       |   |   |-- mafft-homologs.rb
|   |       |   |   |-- md5sum.exe
|   |       |   |   |-- mkdir.exe
|   |       |   |   |-- mktemp.exe
|   |       |   |   |-- more.exe
|   |       |   |   |-- msys-2.0.dll
|   |       |   |   |-- msys-gcc_s-seh-1.dll
|   |       |   |   |-- msys-gmp-10.dll
|   |       |   |   |-- msys-iconv-2.dll
|   |       |   |   |-- msys-intl-8.dll
|   |       |   |   |-- msys-magic-1.dll
|   |       |   |   |-- msys-mpfr-4.dll
|   |       |   |   |-- msys-ncursesw6.dll
|   |       |   |   |-- msys-pcre-1.dll
|   |       |   |   |-- msys-readline6.dll
|   |       |   |   |-- msys-z.dll
|   |       |   |   |-- mv.exe
|   |       |   |   |-- od.exe
|   |       |   |   |-- paste.exe
|   |       |   |   |-- printf.exe
|   |       |   |   |-- ps.exe
|   |       |   |   |-- pwd.exe
|   |       |   |   |-- rm.exe
|   |       |   |   |-- rmdir.exe
|   |       |   |   |-- sed.exe
|   |       |   |   |-- sh.exe
|   |       |   |   |-- sleep.exe
|   |       |   |   |-- sort.exe
|   |       |   |   |-- split.exe
|   |       |   |   |-- stty.exe
|   |       |   |   |-- tail.exe
|   |       |   |   |-- tar.exe
|   |       |   |   |-- touch.exe
|   |       |   |   |-- tr.exe
|   |       |   |   |-- true.exe
|   |       |   |   |-- uname.exe
|   |       |   |   |-- uniq.exe
|   |       |   |   |-- wc.exe
|   |       |   |   |-- which.exe
|   |       |   |   \-- xargs.exe
|   |       |   |-- lib
|   |       |   |   \-- mafft
|   |       |   |       |-- addsingle.exe
|   |       |   |       |-- contrafoldwrap.exe
|   |       |   |       |-- countlen.exe
|   |       |   |       |-- dash_client.exe
|   |       |   |       |-- disttbfast.exe
|   |       |   |       |-- dndblast.exe
|   |       |   |       |-- dndfast7.exe
|   |       |   |       |-- dndpre.exe
|   |       |   |       |-- dvtditr.exe
|   |       |   |       |-- f2cl.exe
|   |       |   |       |-- filter.exe
|   |       |   |       |-- getlag.exe
|   |       |   |       |-- hex2maffttext.exe
|   |       |   |       |-- mafft-distance.exe
|   |       |   |       |-- mafft-homologs.1
|   |       |   |       |-- mafft-profile.exe
|   |       |   |       |-- mafft.1
|   |       |   |       |-- mafftash_premafft.pl
|   |       |   |       |-- maffttext2hex.exe
|   |       |   |       |-- makedirectionlist.exe
|   |       |   |       |-- mccaskillwrap.exe
|   |       |   |       |-- multi2hat3s.exe
|   |       |   |       |-- nodepair.exe
|   |       |   |       |-- pairash.exe
|   |       |   |       |-- pairlocalalign.exe
|   |       |   |       |-- regtable2seq.exe
|   |       |   |       |-- replaceu.exe
|   |       |   |       |-- restoreu.exe
|   |       |   |       |-- score.exe
|   |       |   |       |-- seekquencer_premafft.pl
|   |       |   |       |-- seq2regtable.exe
|   |       |   |       |-- setcore.exe
|   |       |   |       |-- setdirection.exe
|   |       |   |       |-- sextet5.exe
|   |       |   |       |-- splittbfast.exe
|   |       |   |       |-- tbfast.exe
|   |       |   |       \-- version.exe
|   |       |   \-- share
|   |       |       \-- misc
|   |       |           \-- magic
|   |       |-- mafft-signed.ps1
|   |       \-- mafft.bat
|   |-- ncbi_dist
|   |   |-- bin
|   |   |   |-- sra-tools
|   |   |   |   |-- abi-dump.exe
|   |   |   |   |-- fasterq-dump.exe
|   |   |   |   |-- fastq-dump.exe
|   |   |   |   |-- illumina-dump.exe
|   |   |   |   |-- ngs-pileup.exe
|   |   |   |   |-- prefetch.exe
|   |   |   |   |-- sam-dump.exe
|   |   |   |   |-- sff-dump.exe
|   |   |   |   |-- sra-info.exe
|   |   |   |   |-- sra-pileup.exe
|   |   |   |   |-- sra-search.exe
|   |   |   |   |-- sra-stat.exe
|   |   |   |   |-- srapath.exe
|   |   |   |   |-- sratools.exe
|   |   |   |   |-- vdb-config.exe
|   |   |   |   |-- vdb-decrypt.exe
|   |   |   |   |-- vdb-encrypt.exe
|   |   |   |   \-- vdb-validate.exe
|   |   |   \-- tree-tools
|   |   |       |-- additive.exe
|   |   |       |-- align2html.exe
|   |   |       |-- asm_gap.exe
|   |   |       |-- asnt.exe
|   |   |       |-- asnt2tree.exe
|   |   |       |-- blast2ani.exe
|   |   |       |-- blast2cons.exe
|   |   |       |-- blastmat.exe
|   |   |       |-- blastn2mlst.exe
|   |   |       |-- blastp2exons.exe
|   |   |       |-- blastp_merge.exe
|   |   |       |-- blast_best_hits.exe
|   |   |       |-- combine_dissims.exe
|   |   |       |-- compareTrees.exe
|   |   |       |-- connectPairs.exe
|   |   |       |-- contig2read_coverage.exe
|   |   |       |-- conv_comb.exe
|   |   |       |-- csv2tab.exe
|   |   |       |-- disruption2genesymbol.exe
|   |   |       |-- distTree_new.exe
|   |   |       |-- distTree_refresh_dissim.exe
|   |   |       |-- dna2prots.exe
|   |   |       |-- dna2stat.exe
|   |   |       |-- dna_align_service.exe
|   |   |       |-- dna_complexity.exe
|   |   |       |-- dna_consensus.exe
|   |   |       |-- dna_coverage.exe
|   |   |       |-- dna_cut.exe
|   |   |       |-- dna_diff.exe
|   |   |       |-- dna_find.exe
|   |   |       |-- dna_gc_skew.exe
|   |   |       |-- dna_pair2dissim.exe
|   |   |       |-- dna_rev.exe
|   |   |       |-- dna_trim.exe
|   |   |       |-- effectiveSize.exe
|   |   |       |-- extractPairs.exe
|   |   |       |-- f2d_help.txt
|   |   |       |-- f2h_help.txt
|   |   |       |-- fasta2dissim.exe
|   |   |       |-- fasta2GC.exe
|   |   |       |-- fasta2hash.exe
|   |   |       |-- fasta2len.exe
|   |   |       |-- fasta2lines.exe
|   |   |       |-- fastaAddGi.exe
|   |   |       |-- FastTree.exe
|   |   |       |-- feature2dissim.exe
|   |   |       |-- feature_request2dissim.exe
|   |   |       |-- file2hash.exe
|   |   |       |-- filterFasta.exe
|   |   |       |-- fixed2tsv.exe
|   |   |       |-- genbank_grep.exe
|   |   |       |-- h2d_help.txt
|   |   |       |-- hash2dissim.exe
|   |   |       |-- hash_request2dissim.exe
|   |   |       |-- hmm2prot.exe
|   |   |       |-- hmmAddCutoff.exe
|   |   |       |-- hmmExtract.exe
|   |   |       |-- hmmNAME2ACC.exe
|   |   |       |-- hmmsearch2besthits.exe
|   |   |       |-- hmmSplit.exe
|   |   |       |-- hmm_tc1.exe
|   |   |       |-- index_find.exe
|   |   |       |-- interSeq.exe
|   |   |       |-- islander.exe
|   |   |       |-- kmerIndex_add.exe
|   |   |       |-- kmerIndex_find.exe
|   |   |       |-- kmerIndex_make.exe
|   |   |       |-- kmerIndex_stat.exe
|   |   |       |-- libatomic-1.dll
|   |   |       |-- libgcc_s_seh-1.dll
|   |   |       |-- libgfortran-5.dll
|   |   |       |-- libgomp-1.dll
|   |   |       |-- libquadmath-0.dll
|   |   |       |-- libstdc++-6.dll
|   |   |       |-- libwinpthread-1.dll
|   |   |       |-- list2pairs.exe
|   |   |       |-- loci_request2dissim.exe
|   |   |       |-- mafft.bat
|   |   |       |-- main_ortholog.exe
|   |   |       |-- makeDistTree.exe
|   |   |       |-- makeFeatureTree.exe
|   |   |       |-- mergePairs.exe
|   |   |       |-- min_spanning_forest.exe
|   |   |       |-- mlst2dissim.exe
|   |   |       |-- mlst2hash.exe
|   |   |       |-- multilist2subset.exe
|   |   |       |-- muscle.exe
|   |   |       |-- mutation2feature.exe
|   |   |       |-- mutation_dna2prot.exe
|   |   |       |-- mutation_tab.exe
|   |   |       |-- newick2tree.exe
|   |   |       |-- objHash_find.exe
|   |   |       |-- orf2prot.exe
|   |   |       |-- orthodb2fasta.exe
|   |   |       |-- pairs2tsv.exe
|   |   |       |-- printDistTree.exe
|   |   |       |-- prot2triplets.exe
|   |   |       |-- prots2hmm_signature.exe
|   |   |       |-- prots_pair2stat.exe
|   |   |       |-- prot_check.exe
|   |   |       |-- prot_clust.exe
|   |   |       |-- prot_collection2dissim.exe
|   |   |       |-- prot_complexity.exe
|   |   |       |-- prot_consensus.exe
|   |   |       |-- prot_grep_short.exe
|   |   |       |-- replaceDistTree_match.exe
|   |   |       |-- replaceDistTree_reroot.exe
|   |   |       |-- replaceFastaHeader.exe
|   |   |       |-- replace_dict.exe
|   |   |       |-- s2d_help.txt
|   |   |       |-- seq2dissim.exe
|   |   |       |-- seq_print.exe
|   |   |       |-- setRandOrd.exe
|   |   |       |-- splitFasta.exe
|   |   |       |-- splitList.exe
|   |   |       |-- split_help.txt
|   |   |       |-- statDistTree.exe
|   |   |       |-- str2hash.exe
|   |   |       |-- symbet.exe
|   |   |       |-- tblastn2disruption.exe
|   |   |       |-- tblastn2marker_euk.exe
|   |   |       |-- tblastn2orfs.exe
|   |   |       |-- tree2genogroup.exe
|   |   |       |-- tree2indiscern.exe
|   |   |       |-- triple2tsv.exe
|   |   |       |-- tsv2html.exe
|   |   |       |-- tsv2insert.exe
|   |   |       |-- tsv2triple.exe
|   |   |       |-- tsv_aggr_comp.exe
|   |   |       |-- tsv_cat.exe
|   |   |       |-- tsv_cluster.exe
|   |   |       |-- tsv_comp.exe
|   |   |       |-- tsv_group.exe
|   |   |       |-- tsv_join.exe
|   |   |       |-- tsv_null.exe
|   |   |       |-- tsv_rename.exe
|   |   |       |-- tsv_shift.exe
|   |   |       |-- tsv_split.exe
|   |   |       |-- uniqProtRef.exe
|   |   |       |-- uniqSeq.exe
|   |   |       |-- xml_bin2txt.exe
|   |   |       |-- xml_find.exe
|   |   |       |-- xml_merge_schemas.exe
|   |   |       |-- xml_print.exe
|   |   |       \-- xml_txt2bin.exe
|   |   \-- lib
|   |       |-- ncbi-vdb
|   |       |   |-- libalign-access.a
|   |       |   |-- libalign-reader.a
|   |       |   |-- libalign-writer.a
|   |       |   |-- libaxf.a
|   |       |   |-- libbz2.a
|   |       |   |-- libcloud.a
|   |       |   |-- libjudy.a
|   |       |   |-- libkdb.a
|   |       |   |-- libkdbtext.a
|   |       |   |-- libkfc.a
|   |       |   |-- libkfg.a
|   |       |   |-- libkfs-nommap.a
|   |       |   |-- libkfs.a
|   |       |   |-- libklib.a
|   |       |   |-- libkns.a
|   |       |   |-- libkproc.a
|   |       |   |-- libkq.a
|   |       |   |-- libkrypto.a
|   |       |   |-- libktst.a
|   |       |   |-- libmbedcrypto.a
|   |       |   |-- libmbedtls.a
|   |       |   |-- libmbedx509.a
|   |       |   |-- libncbi-bam.a
|   |       |   |-- libncbi-vdb.a
|   |       |   |-- libncbi-vdb.dll.a
|   |       |   |-- libncbi-wvdb.a
|   |       |   |-- libncbi-wvdb.dll.a
|   |       |   |-- libsam-extract.a
|   |       |   |-- libschema.a
|   |       |   |-- libsradb.a
|   |       |   |-- libsrareader.a
|   |       |   |-- libsraxf.a
|   |       |   |-- libvdb-blast.a
|   |       |   |-- libvdb.a
|   |       |   |-- libvdbapp.a
|   |       |   |-- libvfs.a
|   |       |   |-- libvxf.a
|   |       |   |-- libwaxf.a
|   |       |   |-- libwgsxf.a
|   |       |   |-- libwsradb.a
|   |       |   |-- libwsraxf.a
|   |       |   |-- libwvdb.a
|   |       |   |-- libwvxf.a
|   |       |   |-- libwwgsxf.a
|   |       |   |-- libz.a
|   |       |   |-- libzstd.a
|   |       |   \-- objects.a
|   |       \-- ngs-sdk
|   |           \-- libngs-sdk.a
|   |-- _deprecated
|   |   |-- align-info.exe
|   |   |-- ascii.exe
|   |   |-- cache-mgr.exe
|   |   |-- check-corrupt.exe
|   |   |-- dm2feature.exe
|   |   |-- fasta2feature.exe
|   |   |-- fastaDna2pairs.exe
|   |   |-- fasta_prefix.exe
|   |   |-- fasterq-dump-driver.exe
|   |   |-- feature2gain_loss.exe
|   |   |-- GeneMark2CDS.exe
|   |   |-- hello.exe
|   |   |-- kdbmeta.exe
|   |   |-- libatomic-1.dll
|   |   |-- libgcc_s_seh-1.dll
|   |   |-- libgfortran-5.dll
|   |   |-- libgomp-1.dll
|   |   |-- libquadmath-0.dll
|   |   |-- libstdc++-6.dll
|   |   |-- libwinpthread-1.dll
|   |   |-- prot_find.exe
|   |   |-- randomDistTree.exe
|   |   |-- random_words.exe
|   |   |-- rcexplain.exe
|   |   |-- ref-variation.exe
|   |   |-- sam-dump-driver.exe
|   |   |-- setMinus.exe
|   |   |-- sra-pileup-driver.exe
|   |   |-- symbet_blastp.exe
|   |   |-- trav.exe
|   |   |-- tsv_schema.exe
|   |   |-- var-expand.exe
|   |   |-- vdb-dump-driver.exe
|   |   |-- vdb-dump.exe
|   |   |-- xml2schema.exe
|   |   |-- xml_schema2ddl.exe
|   |   \-- xml_schema2flat.exe
|   |-- 1.py
|   |-- fix_imports_batch.py
|   |-- fix_init_files.py
|   |-- fix_json_comments.py
|   |-- fix_ncbi_component.py
|   |-- generate_help_docs.py
|   |-- project_fixer.py
|   |-- quick_fix_component.py
|   \-- scan_docs_errors.py
|-- vendor
|   |-- ete4
|   |   |-- .github
|   |   |   |-- workflows
|   |   |   |   \-- update_docs.yml
|   |   |   \-- FUNDING.yml
|   |   |-- doc
|   |   |   |-- images
|   |   |   |   |-- collapsed.png
|   |   |   |   |-- combined.png
|   |   |   |   |-- context_menu.png
|   |   |   |   |-- draw_node.png
|   |   |   |   |-- example_layout_functions.png
|   |   |   |   |-- face_aligned.png
|   |   |   |   |-- face_borders.png
|   |   |   |   |-- face_bottom.png
|   |   |   |   |-- face_bottom2.png
|   |   |   |   |-- face_positions.png
|   |   |   |   |-- face_properties.png
|   |   |   |   |-- gallery.png
|   |   |   |   |-- gui.png
|   |   |   |   |-- layout_example.png
|   |   |   |   |-- my_layout.png
|   |   |   |   |-- node_backgrounds.png
|   |   |   |   |-- node_id.png
|   |   |   |   |-- node_style_red_and_blue_nodes.png
|   |   |   |   |-- node_style_red_nodes.png
|   |   |   |   |-- not_collapsed.png
|   |   |   |   |-- panel.png
|   |   |   |   |-- panel_advanced.png
|   |   |   |   |-- panel_main.png
|   |   |   |   |-- panel_selections.png
|   |   |   |   |-- preorder.png
|   |   |   |   |-- rotated_tree.png
|   |   |   |   |-- scale_x.png
|   |   |   |   |-- scale_y.png
|   |   |   |   |-- semi_circular_tree.png
|   |   |   |   |-- show_info.png
|   |   |   |   |-- size.png
|   |   |   |   |-- tree.png
|   |   |   |   |-- tree_parts.png
|   |   |   |   |-- vowels.png
|   |   |   |   \-- walk.png
|   |   |   |-- internals
|   |   |   |   |-- index.rst
|   |   |   |   |-- internals_api.rst
|   |   |   |   |-- internals_detailed_layout.rst
|   |   |   |   |-- internals_drawing.rst
|   |   |   |   |-- internals_essentials.rst
|   |   |   |   \-- internals_overview.rst
|   |   |   |-- reference
|   |   |   |   |-- index.rst
|   |   |   |   |-- reference_operations.rst
|   |   |   |   |-- reference_parsers.rst
|   |   |   |   |-- reference_phylo.rst
|   |   |   |   |-- reference_seqgroup.rst
|   |   |   |   |-- reference_smartview.rst
|   |   |   |   |-- reference_taxonomy.rst
|   |   |   |   |-- reference_tree.rst
|   |   |   |   |-- reference_treematcher.rst
|   |   |   |   \-- reference_treeview.rst
|   |   |   |-- tutorial
|   |   |   |   |-- index.rst
|   |   |   |   |-- tutorial_phylogeny.rst
|   |   |   |   |-- tutorial_smartview.rst
|   |   |   |   |-- tutorial_taxonomy.rst
|   |   |   |   |-- tutorial_treematcher.rst
|   |   |   |   |-- tutorial_trees.rst
|   |   |   |   \-- tutorial_treeview.rst
|   |   |   |-- _static
|   |   |   |   \-- favicon.ico
|   |   |   |-- about.rst
|   |   |   |-- conf.py
|   |   |   |-- faqs.rst
|   |   |   |-- index.rst
|   |   |   |-- make.bat
|   |   |   \-- Makefile
|   |   |-- ete4
|   |   |   |-- core
|   |   |   |   |-- operations.c
|   |   |   |   |-- operations.cp313-win_amd64.pyd
|   |   |   |   |-- operations.pyx
|   |   |   |   |-- seqgroup.py
|   |   |   |   |-- text_viz.py
|   |   |   |   |-- tree.c
|   |   |   |   |-- tree.cp313-win_amd64.pyd
|   |   |   |   |-- tree.pyx
|   |   |   |   \-- __init__.py
|   |   |   |-- evol
|   |   |   |   |-- parser
|   |   |   |   |   |-- codemlparser.py
|   |   |   |   |   |-- slrparser.py
|   |   |   |   |   \-- __init__.py
|   |   |   |   |-- control.py
|   |   |   |   |-- evoltree.py
|   |   |   |   |-- model.py
|   |   |   |   |-- utils.py
|   |   |   |   \-- __init__.py
|   |   |   |-- gtdb_taxonomy
|   |   |   |   |-- gtdbquery.py
|   |   |   |   \-- __init__.py
|   |   |   |-- ncbi_taxonomy
|   |   |   |   |-- SQLite-Levenshtein
|   |   |   |   |   |-- src
|   |   |   |   |   |   \-- levenshtein.c
|   |   |   |   |   |-- .gitignore
|   |   |   |   |   |-- EXAMPLE
|   |   |   |   |   |-- Makefile
|   |   |   |   |   \-- README
|   |   |   |   |-- ncbiquery.py
|   |   |   |   \-- __init__.py
|   |   |   |-- orthoxml
|   |   |   |   |-- _orthoxml.py
|   |   |   |   \-- __init__.py
|   |   |   |-- parser
|   |   |   |   |-- ete_format.py
|   |   |   |   |-- fasta.py
|   |   |   |   |-- indent.py
|   |   |   |   |-- newick.c
|   |   |   |   |-- newick.cp313-win_amd64.pyd
|   |   |   |   |-- newick.pyx
|   |   |   |   |-- nexus.py
|   |   |   |   |-- paml.py
|   |   |   |   |-- phylip.py
|   |   |   |   \-- __init__.py
|   |   |   |-- phylo
|   |   |   |   |-- evolevents.py
|   |   |   |   |-- phylotree.py
|   |   |   |   |-- reconciliation.py
|   |   |   |   |-- spoverlap.py
|   |   |   |   \-- __init__.py
|   |   |   |-- phyloxml
|   |   |   |   |-- _phyloxml.py
|   |   |   |   |-- _phyloxml_tree.py
|   |   |   |   \-- __init__.py
|   |   |   |-- smartview
|   |   |   |   |-- static
|   |   |   |   |   |-- external
|   |   |   |   |   |   |-- pixi.min.mjs
|   |   |   |   |   |   |-- readme.md
|   |   |   |   |   |   |-- sweetalert2.min.js
|   |   |   |   |   |   \-- tweakpane.min.js
|   |   |   |   |   |-- images
|   |   |   |   |   |   |-- icon.png
|   |   |   |   |   |   |-- spritesheet.json
|   |   |   |   |   |   \-- spritesheet.png
|   |   |   |   |   |-- js
|   |   |   |   |   |   |-- api.js
|   |   |   |   |   |   |-- collapse.js
|   |   |   |   |   |   |-- contextmenu.js
|   |   |   |   |   |   |-- download.js
|   |   |   |   |   |   |-- drag.js
|   |   |   |   |   |   |-- draw.js
|   |   |   |   |   |   |-- events.js
|   |   |   |   |   |   |-- gui.js
|   |   |   |   |   |   |-- label.js
|   |   |   |   |   |   |-- menu.js
|   |   |   |   |   |   |-- minimap.js
|   |   |   |   |   |   |-- pixi.js
|   |   |   |   |   |   |-- search.js
|   |   |   |   |   |   |-- tag.js
|   |   |   |   |   |   |-- upload.js
|   |   |   |   |   |   \-- zoom.js
|   |   |   |   |   |-- gui.css
|   |   |   |   |   |-- gui.html
|   |   |   |   |   |-- upload.css
|   |   |   |   |   \-- upload.html
|   |   |   |   |-- coordinates.py
|   |   |   |   |-- draw.py
|   |   |   |   |-- explorer.py
|   |   |   |   |-- faces.py
|   |   |   |   |-- graphics.py
|   |   |   |   |-- layout.py
|   |   |   |   \-- __init__.py
|   |   |   |-- tools
|   |   |   |   |-- ete_build_lib
|   |   |   |   |   |-- task
|   |   |   |   |   |   |-- clustalo.py
|   |   |   |   |   |   |-- cog_creator.py
|   |   |   |   |   |   |-- cog_selector.py
|   |   |   |   |   |   |-- concat_alg.py
|   |   |   |   |   |   |-- dialigntx.py
|   |   |   |   |   |   |-- dummyalg.py
|   |   |   |   |   |   |-- dummytree.py
|   |   |   |   |   |   |-- fasttree.py
|   |   |   |   |   |   |-- iqtree.py
|   |   |   |   |   |   |-- mafft.py
|   |   |   |   |   |   |-- merger.py
|   |   |   |   |   |   |-- meta_aligner.py
|   |   |   |   |   |   |-- msf.py
|   |   |   |   |   |   |-- muscle.py
|   |   |   |   |   |   |-- phyml.py
|   |   |   |   |   |   |-- raxml.py
|   |   |   |   |   |   |-- tcoffee.py
|   |   |   |   |   |   |-- trimal.py
|   |   |   |   |   |   |-- uhire.py
|   |   |   |   |   |   \-- __init__.py
|   |   |   |   |   |-- workflow
|   |   |   |   |   |   |-- common.py
|   |   |   |   |   |   |-- genetree.py
|   |   |   |   |   |   |-- supermatrix.py
|   |   |   |   |   |   \-- __init__.py
|   |   |   |   |   |-- apps.py
|   |   |   |   |   |-- configcheck.py
|   |   |   |   |   |-- configobj.py
|   |   |   |   |   |-- curses_gui.py
|   |   |   |   |   |-- db.py
|   |   |   |   |   |-- errors.py
|   |   |   |   |   |-- getch.py
|   |   |   |   |   |-- interface.py
|   |   |   |   |   |-- logger.py
|   |   |   |   |   |-- master_job.py
|   |   |   |   |   |-- master_task.py
|   |   |   |   |   |-- scheduler.py
|   |   |   |   |   |-- seqio.py
|   |   |   |   |   |-- sge.py
|   |   |   |   |   |-- utils.py
|   |   |   |   |   |-- validate.py
|   |   |   |   |   |-- visualize.py
|   |   |   |   |   \-- __init__.py
|   |   |   |   |-- common.py
|   |   |   |   |-- ete.py
|   |   |   |   |-- ete_annotate.py
|   |   |   |   |-- ete_build.cfg
|   |   |   |   |-- ete_build.py
|   |   |   |   |-- ete_compare.py
|   |   |   |   |-- ete_diff.py
|   |   |   |   |-- ete_evol.py
|   |   |   |   |-- ete_expand.py
|   |   |   |   |-- ete_explore.py
|   |   |   |   |-- ete_extract.py
|   |   |   |   |-- ete_generate.py
|   |   |   |   |-- ete_maptrees.py
|   |   |   |   |-- ete_mod.py
|   |   |   |   |-- ete_ncbiquery.py
|   |   |   |   |-- ete_split.py
|   |   |   |   |-- ete_upgrade_tools.py
|   |   |   |   |-- ete_view.py
|   |   |   |   |-- utils.py
|   |   |   |   \-- __init__.py
|   |   |   |-- treematcher
|   |   |   |   |-- treematcher.py
|   |   |   |   \-- __init__.py
|   |   |   |-- treeview
|   |   |   |   |-- about.ui
|   |   |   |   |-- clean_search.png
|   |   |   |   |-- drawer.py
|   |   |   |   |-- ete_icon.png
|   |   |   |   |-- ete_logo.png
|   |   |   |   |-- ete_qt4app.ui
|   |   |   |   |-- ete_resources.qrc
|   |   |   |   |-- ete_resources_rc.py
|   |   |   |   |-- export_pdf.png
|   |   |   |   |-- faces.py
|   |   |   |   |-- fileopen.png
|   |   |   |   |-- filesave.png
|   |   |   |   |-- fit_region.png
|   |   |   |   |-- fit_tree.png
|   |   |   |   |-- force_topo.png
|   |   |   |   |-- image_properties.ui
|   |   |   |   |-- layouts.py
|   |   |   |   |-- main.py
|   |   |   |   |-- node_gui_actions.py
|   |   |   |   |-- open_newick.ui
|   |   |   |   |-- qt.py
|   |   |   |   |-- qt4_compile_resources.sh
|   |   |   |   |-- qt_circular_render.py
|   |   |   |   |-- qt_face_render.py
|   |   |   |   |-- qt_gui.py
|   |   |   |   |-- qt_rect_render.py
|   |   |   |   |-- qt_render.py
|   |   |   |   |-- search.png
|   |   |   |   |-- search_dialog.ui
|   |   |   |   |-- show_dist.png
|   |   |   |   |-- show_names.png
|   |   |   |   |-- show_newick.png
|   |   |   |   |-- show_newick.ui
|   |   |   |   |-- show_support.png
|   |   |   |   |-- templates.py
|   |   |   |   |-- x_expand.png
|   |   |   |   |-- x_reduce.png
|   |   |   |   |-- y_expand.png
|   |   |   |   |-- y_reduce.png
|   |   |   |   |-- zoom_in.png
|   |   |   |   |-- zoom_out.png
|   |   |   |   |-- _about.py
|   |   |   |   |-- _mainwindow.py
|   |   |   |   |-- _open_newick.py
|   |   |   |   |-- _search_dialog.py
|   |   |   |   |-- _show_codeml.py
|   |   |   |   |-- _show_newick.py
|   |   |   |   \-- __init__.py
|   |   |   |-- citation.py
|   |   |   |-- config.py
|   |   |   |-- utils.py
|   |   |   |-- version.py
|   |   |   \-- __init__.py
|   |   |-- ete4.egg-info
|   |   |   |-- dependency_links.txt
|   |   |   |-- entry_points.txt
|   |   |   |-- PKG-INFO
|   |   |   |-- requires.txt
|   |   |   |-- SOURCES.txt
|   |   |   \-- top_level.txt
|   |   |-- examples
|   |   |   |-- evol
|   |   |   |   |-- 1_freeratio.py
|   |   |   |   |-- 2_sites_model.py
|   |   |   |   |-- 4_branch_models.py
|   |   |   |   |-- 6_ancestral_sequence.py
|   |   |   |   |-- 7_slr.py
|   |   |   |   |-- measuring_evolution_trees.py
|   |   |   |   \-- README
|   |   |   |-- general
|   |   |   |   |-- add_features.py
|   |   |   |   |-- byoperand_search.py
|   |   |   |   |-- chimp.png
|   |   |   |   |-- copy_and_paste_trees.py
|   |   |   |   |-- create_trees_from_scratch.py
|   |   |   |   |-- custom_search.py
|   |   |   |   |-- custom_tree_traversing.py
|   |   |   |   |-- custom_tree_visualization.py
|   |   |   |   |-- dog.png
|   |   |   |   |-- fish.png
|   |   |   |   |-- fly.png
|   |   |   |   |-- genes_tree.nh
|   |   |   |   |-- getting_leaves.py
|   |   |   |   |-- get_common_ancestor.py
|   |   |   |   |-- get_distances_between_nodes.py
|   |   |   |   |-- get_midpoint_outgroup.py
|   |   |   |   |-- human.png
|   |   |   |   |-- iterators.py
|   |   |   |   |-- label_nodes.py
|   |   |   |   |-- mouse.png
|   |   |   |   |-- nhx_format.py
|   |   |   |   |-- prune_tree.py
|   |   |   |   |-- random_tree.png
|   |   |   |   |-- read_newick.py
|   |   |   |   |-- remove_and_delete_nodes.py
|   |   |   |   |-- render_tree_images.py
|   |   |   |   |-- rooting_subtrees.py
|   |   |   |   |-- rooting_trees.py
|   |   |   |   |-- search_nodes.py
|   |   |   |   |-- tree_basis.py
|   |   |   |   |-- tree_traverse.py
|   |   |   |   \-- write_newick.py
|   |   |   |-- phylogenies
|   |   |   |   |-- dating_evolutionary_events.py
|   |   |   |   |-- link_sequences_to_phylogenies.py
|   |   |   |   |-- orthology_and_paralogy_prediction.py
|   |   |   |   |-- phylotree.png
|   |   |   |   |-- phylotree_visualization.py
|   |   |   |   \-- tree_reconciliation.py
|   |   |   |-- phyloxml
|   |   |   |   |-- apaf.xml
|   |   |   |   |-- bcl_2.xml
|   |   |   |   |-- example1.xml
|   |   |   |   |-- example2.xml
|   |   |   |   |-- example3.xml
|   |   |   |   |-- multiple_supports.xml
|   |   |   |   |-- phyloxml_examples.xml
|   |   |   |   |-- phyloxml_from_scratch.py
|   |   |   |   \-- phyloxml_parser.py
|   |   |   \-- treeview
|   |   |       |-- img_faces
|   |   |       |   |-- chimp.png
|   |   |       |   |-- dog.png
|   |   |       |   |-- fish.png
|   |   |       |   |-- fly.png
|   |   |       |   |-- human.png
|   |   |       |   |-- img_faces.png
|   |   |       |   |-- img_faces.py
|   |   |       |   \-- mouse.png
|   |   |       |-- barcharts.png
|   |   |       |-- barchart_and_piechart_faces.py
|   |   |       |-- bubble_map.png
|   |   |       |-- bubble_map.py
|   |   |       |-- face_grid.py
|   |   |       |-- face_grid_tutorial.py
|   |   |       |-- face_positions.py
|   |   |       |-- face_rotation.py
|   |   |       |-- floating_piecharts.py
|   |   |       |-- float_piechart.png
|   |   |       |-- item_faces.png
|   |   |       |-- item_faces.py
|   |   |       |-- new_seq_face.py
|   |   |       |-- node_background.png
|   |   |       |-- node_background.py
|   |   |       |-- node_style.png
|   |   |       |-- node_style.py
|   |   |       |-- random_draw.py
|   |   |       |-- rotated_faces.png
|   |   |       |-- seqmotif.png
|   |   |       |-- seq_motif_faces.png
|   |   |       |-- seq_motif_faces.py
|   |   |       |-- tree_faces.png
|   |   |       \-- tree_faces.py
|   |   |-- utils
|   |   |   |-- conda_build
|   |   |   |   |-- build.sh.template
|   |   |   |   |-- meta.yaml.template
|   |   |   |   \-- release_conda.sh
|   |   |   |-- FILE_HEADER.txt
|   |   |   |-- release.py
|   |   |   \-- update_license.py
|   |   |-- .gitignore
|   |   |-- CODE_OF_CONDUCT.md
|   |   |-- CONTRIBUTING.md
|   |   |-- LICENSE
|   |   |-- pyproject.toml
|   |   |-- README.md
|   |   |-- setup.py
|   |   |-- THANKS.md
|   |   \-- VERSION
|   |-- fasttree
|   |   |-- FastTree.exe
|   |   \-- LICENSE
|   |-- iqtree3
|   |   |-- hmsbeagle-cpu-sse64-40.dll
|   |   |-- hmsbeagle-cpu64-40.dll
|   |   |-- hmsbeagle-cuda64-40.dll
|   |   |-- hmsbeagle-opencl64-40.dll
|   |   |-- hmsbeagle-x64.dll
|   |   |-- hmsbeagle64.dll
|   |   |-- iqtree.exe
|   |   |-- iqtree_help_full.txt
|   |   |-- libiomp5md.dll
|   |   \-- LICENSE
|   |-- iqtree3_linux
|   |   |-- bin
|   |   |   \-- iqtree2
|   |   |-- example.cf
|   |   |-- example.nex
|   |   |-- example.phy
|   |   |-- iqtree_linux.tar.gz
|   |   \-- models.nex
|   |-- MrBayes
|   |   |-- COPYING
|   |   \-- mb.exe
|   \-- __init__.py
|-- .gitattributes
|-- .gitignore
|-- build.bat
|-- build_release.py
|-- codelookup_debug.json
|-- config.json
|-- copy_component.py
|-- dev.bat
|-- package.json
|-- predefined_terms.csv
|-- pyrightconfig.json
|-- README.md
|-- requirements.txt
|-- RUN_DEV_ELECTRON.bat
\-- setup_wsl.sh
```