# Project Structure (Simplified) - NCBI blast
```text
NCBI blast/
├── build.bat
├── build_release.py
├── codelookup_debug.json
├── config.json
├── copy_component.py
├── dev.bat
├── NCBI_BLAST_GUI.spec
├── package.json
├── predefined_terms.csv
├── pyrightconfig.json
├── README.md
├── requirements.txt
├── RUN_DEV_ELECTRON.bat
├── setup_wsl.sh
├── translations.db
├── translations_backup.db
├── database/
│   ├── sequences.db
│   ├── strain.db
│   ├── 16S/
│   │   ├── 16S_ribosomal_RNA-nucl-metadata.json
│   │   ├── 16S_ribosomal_RNA.tar.gz
│   │   ├── 16S_ribosomal_RNA.tar.gz.md5
│   ├── taxonomy/
│   │   ├── taxa.sqlite
│   │   ├── taxa.sqlite.traverse.pkl
│   │   ├── taxdump.tar.gz
│   │   ├── taxdump.tar.gz.md5
│   │   ├── taxcat/
│   │   │   ├── categories.dmp
│   │   │   ├── taxcat_readme.txt
│   │   ├── taxdmp/
│   │   │   ├── citations.dmp
│   │   │   ├── delnodes.dmp
│   │   │   ├── division.dmp
│   │   │   ├── gc.prt
│   │   │   ├── gencode.dmp
│   │   │   ├── images.dmp
│   │   │   ├── merged.dmp
│   │   │   ├── names.dmp
│   │   │   ├── nodes.dmp
│   │   │   ├── readme.txt
├── docs/
│   ├── project_structure.md
│   ├── node_studio_records/
│   │   ├── implementation_plan.md
│   │   ├── task.md
│   │   ├── walkthrough.md
├── electron-shell/
│   ├── main.js
│   ├── package-lock.json
│   ├── package.json
│   ├── preload.js
├── resources/
│   ├── help/
│   │   ├── database_manager.md
│   │   ├── history.md
│   │   ├── local_blast.md
│   │   ├── quick_start.md
│   │   ├── settings.md
│   │   ├── translation_debugger.md
├── results/
│   ├── annotations_v2.db
│   ├── blast_meta.db
├── scratch/
│   ├── check_db.py
│   ├── check_history.py
│   ├── cleanup_sp.py
│   ├── clean_styles.py
│   ├── deep_optimize.py
│   ├── deep_scan_v2.py
│   ├── fix_imports.py
│   ├── fix_templates.py
│   ├── heavy_cleanup.py
│   ├── reconstruct_history.py
│   ├── scan_code_anomalies.py
├── scripts/
│   ├── download_externals.ps1
├── src/
│   ├── pyrightconfig.json
│   ├── __init__.py
│   ├── __main__.py
│   ├── analysis/
│   │   ├── ncbi_tree_tool.py
│   │   ├── __init__.py
│   ├── backend/
│   │   ├── api_server.py
│   │   ├── broadcaster.py
│   │   ├── cleanup_translations.py
│   │   ├── diag_db.py
│   │   ├── fully_restore_config.py
│   │   ├── lan_share.py
│   │   ├── populate.py
│   │   ├── populate_pathogens.py
│   │   ├── restore_sources.py
│   │   ├── sequence_db.py
│   │   ├── strain_db.py
│   │   ├── upgrade_dictionaries.py
│   │   ├── routes/
│   │   │   ├── blast.py
│   │   │   ├── common.py
│   │   │   ├── core.py
│   │   │   ├── dictionary.py
│   │   │   ├── settings.py
│   │   │   ├── strains.py
│   │   │   ├── taxonomy.py
│   │   │   ├── tree.py
│   │   │   ├── __init__.py
│   │   ├── scratch/
│   │   ├── utils/
│   │   │   ├── blast_utils.py
│   ├── blast/
│   │   ├── database_manager.py
│   │   ├── engine.py
│   │   ├── executor.py
│   │   ├── local_blast.py
│   │   ├── manager.py
│   │   ├── parser.py
│   │   ├── result_converter.py
│   │   ├── __init__.py
│   ├── modules/
│   │   ├── tooltip/
│   │   │   ├── compat.js
│   │   │   ├── index.js
│   │   │   ├── README.md
│   │   │   ├── tooltip-fix.js
│   │   │   ├── core/
│   │   │   │   ├── TooltipConfig.js
│   │   │   │   ├── TooltipManager.js
│   │   │   │   ├── types.js
│   │   │   ├── handlers/
│   │   │   │   ├── EventHandler.js
│   │   │   │   ├── PositionHandler.js
│   │   │   ├── styles/
│   │   │   │   ├── tooltip.css
│   │   │   ├── ui/
│   │   │   │   ├── DOMAdapter.js
│   │   │   │   ├── Renderer.js
│   │   │   ├── utils/
│   ├── resources/
│   │   ├── locales/
│   │   │   ├── en_US/
│   │   │   │   ├── blast.json
│   │   │   │   ├── common.json
│   │   │   │   ├── dash.json
│   │   │   │   ├── help.json
│   │   │   │   ├── metadata.json
│   │   │   │   ├── node.json
│   │   │   │   ├── others.json
│   │   │   │   ├── param.json
│   │   │   │   ├── strain.json
│   │   │   │   ├── ui.json
│   │   │   ├── zh_CN/
│   │   │   │   ├── blast.json
│   │   │   │   ├── common.json
│   │   │   │   ├── dash.json
│   │   │   │   ├── help.json
│   │   │   │   ├── metadata.json
│   │   │   │   ├── node.json
│   │   │   │   ├── others.json
│   │   │   │   ├── param.json
│   │   │   │   ├── strain.json
│   │   │   │   ├── ui.json
│   ├── utils/
│   │   ├── config_manager.py
│   │   ├── environment_checker.py
│   │   ├── file_handler.py
│   │   ├── hash_checker.py
│   │   ├── help_manager.py
│   │   ├── taxonomy_provider.py
│   │   ├── taxonomy_sync_service.py
│   │   ├── ui_translation_manager.py
│   │   ├── universal_parser.py
│   │   ├── __init__.py
│   │   ├── translation/
│   │   │   ├── biology_translator.py
│   │   │   ├── blast_result_translator.py
│   │   │   ├── classification_rules.json
│   │   │   ├── qwen_translator.py
│   │   │   ├── term_extractor.py
│   │   │   ├── translation_data_manager.py
│   │   │   ├── __init__.py
│   ├── web-next/
│   │   ├── index.html
│   │   ├── LABEL_DISPLAY_MODE_FIX_REPORT.md
│   │   ├── package-lock.json
│   │   ├── package.json
│   │   ├── README.md
│   │   ├── tsconfig.app.json
│   │   ├── tsconfig.json
│   │   ├── tsconfig.node.json
│   │   ├── verify_label_display_mode.js
│   │   ├── vite.config.ts
│   │   ├── public/
│   │   │   ├── vite.svg
│   │   ├── src/
│   │   │   ├── App.vue
│   │   │   ├── main.ts
│   │   │   ├── assets/
│   │   │   │   ├── logo.svg
│   │   │   │   ├── vue.svg
│   │   │   │   ├── styles/
│   │   │   │   │   ├── global.css
│   │   │   ├── bridge/
│   │   │   │   ├── electron-bridge.ts
│   │   │   │   ├── index.ts
│   │   │   │   ├── pyqt-bridge.ts
│   │   │   ├── components/
│   │   │   │   ├── PhylotreeWidget.vue
│   │   │   │   ├── blast/
│   │   │   │   │   ├── AlignmentMap.vue
│   │   │   │   │   ├── BlastDetailDialog.vue
│   │   │   │   │   ├── BlastHistoryPanel.vue
│   │   │   │   │   ├── BlastInputPanel.vue
│   │   │   │   │   ├── BlastParamsPanel.vue
│   │   │   │   │   ├── BlastResultsTable.vue
│   │   │   │   │   ├── BlastVisualModal.vue
│   │   │   │   ├── common/
│   │   │   │   │   ├── NotificationStack.vue
│   │   │   │   │   ├── TranslateSplicer.vue
│   │   │   │   │   ├── UniversalUpload.vue
│   │   │   │   ├── layout/
│   │   │   │   │   ├── AppHeader.vue
│   │   │   │   │   ├── AppSidebar.vue
│   │   │   │   ├── strain/
│   │   │   │   │   ├── AddFreezerDialog.vue
│   │   │   │   │   ├── BatchImportDialog.vue
│   │   │   │   │   ├── CodeLookupManager.vue
│   │   │   │   │   ├── DragDropOverlay.vue
│   │   │   │   │   ├── EditFreezerDialog.vue
│   │   │   │   │   ├── Freezer3DView.vue
│   │   │   │   │   ├── FreezerDetailPanel.vue
│   │   │   │   │   ├── FreezerSidebar.vue
│   │   │   │   │   ├── KeyboardShortcutsHelp.vue
│   │   │   │   │   ├── PositionActionsMenu.vue
│   │   │   │   │   ├── SampleCodeInput.vue
│   │   │   │   │   ├── SampleDetailDialog.vue
│   │   │   │   │   ├── SampleEntryDialog.vue
│   │   │   │   │   ├── SamplePositionBanner.vue
│   │   │   │   │   ├── SearchFilterPanel.vue
│   │   │   │   │   ├── SearchResultsList.vue
│   │   │   │   │   ├── SequenceEntryPanel.vue
│   │   │   │   │   ├── StatisticsPanel.vue
│   │   │   │   │   ├── StrainDataTable.vue
│   │   │   │   │   ├── StrainDetailPanel.vue
│   │   │   │   │   ├── StrainFilterPanel.vue
│   │   │   │   │   ├── StrainHistoryPanel.vue
│   │   │   │   │   ├── StrainImportPanel.vue
│   │   │   │   │   ├── StrainSidebar.vue
│   │   │   │   │   ├── StrainToolbar.vue
│   │   │   │   │   ├── forms/
│   │   │   │   │   │   ├── BaseMetadataForm.vue
│   │   │   │   │   │   ├── CellForm.vue
│   │   │   │   │   │   ├── GeneticForm.vue
│   │   │   │   │   │   ├── MicrobeForm.vue
│   │   │   │   │   │   ├── PhageForm.vue
│   │   │   │   │   │   ├── ProteinForm.vue
│   │   │   │   │   │   ├── VirusForm.vue
│   │   │   │   ├── ui/
│   │   │   │   │   ├── BaseButton.vue
│   │   │   │   │   ├── BaseCard.vue
│   │   │   │   │   ├── BaseInput.vue
│   │   │   │   │   ├── BaseSelect.vue
│   │   │   ├── composables/
│   │   │   │   ├── useBlastDetailViewer.ts
│   │   │   │   ├── useBlastResultHandler.ts
│   │   │   │   ├── useBlastTaskManager.ts
│   │   │   │   ├── useCodeGenerator.ts
│   │   │   │   ├── useCodeLookup.ts
│   │   │   │   ├── useSerialCounter.ts
│   │   │   │   ├── useTaxonomySync.ts
│   │   │   │   ├── useTree.ts
│   │   │   ├── core/
│   │   │   │   ├── tree/
│   │   │   │   │   ├── layout/
│   │   │   │   │   │   ├── LayoutEngine.ts
│   │   │   │   │   ├── models/
│   │   │   │   │   │   ├── TreeModel.ts
│   │   │   │   │   ├── renderer/
│   │   │   │   │   │   ├── HybridRenderer.ts
│   │   │   │   │   │   ├── ScaleBarRenderer.ts
│   │   │   │   │   │   ├── TreeEdgeRenderer.ts
│   │   │   │   │   │   ├── ViewportController.ts
│   │   │   │   │   ├── vendor_phylotree/
│   │   │   │   │   │   ├── alignment.fasta
│   │   │   │   │   │   ├── API.md
│   │   │   │   │   │   ├── CNAME
│   │   │   │   │   │   ├── CODE_OF_CONDUCT.md
│   │   │   │   │   │   ├── CONTRIBUTING.md
│   │   │   │   │   │   ├── eslint.config.mjs
│   │   │   │   │   │   ├── fasta_headers.txt
│   │   │   │   │   │   ├── favicon.ico
│   │   │   │   │   │   ├── functions
│   │   │   │   │   │   ├── index.html
│   │   │   │   │   │   ├── label-tree.bf
│   │   │   │   │   │   ├── LICENSE
│   │   │   │   │   │   ├── package-lock.json
│   │   │   │   │   │   ├── package.json
│   │   │   │   │   │   ├── phylotree.css
│   │   │   │   │   │   ├── README.md
│   │   │   │   │   │   ├── requirements.txt
│   │   │   │   │   │   ├── rollup.config.mjs
│   │   │   │   │   │   ├── sorted.txt
│   │   │   │   │   │   ├── sorted_headers.txt
│   │   │   │   │   │   ├── tips.txt
│   │   │   │   │   │   ├── tree.txt
│   │   │   │   │   │   ├── yarn.lock
│   │   │   │   │   │   ├── bin/
│   │   │   │   │   │   │   ├── phylotree-distance.js
│   │   │   │   │   │   │   ├── phylotree-mrca.js
│   │   │   │   │   │   │   ├── phylotree-neighbor-join.js
│   │   │   │   │   │   │   ├── phylotree-reroot.js
│   │   │   │   │   │   │   ├── phylotree-shuffle.js
│   │   │   │   │   │   │   ├── phylotree-tag.js
│   │   │   │   │   │   │   ├── phylotree-tips.js
│   │   │   │   │   │   │   ├── phylotree-validate.js
│   │   │   │   │   │   │   ├── phylotree.js
│   │   │   │   │   │   │   ├── root-to-tip.js
│   │   │   │   │   │   │   ├── tip-date-extractor.js
│   │   │   │   │   │   ├── data/
│   │   │   │   │   │   │   ├── EU3031.txt
│   │   │   │   │   │   │   ├── Flu_PB2.nwk.txt
│   │   │   │   │   │   │   ├── h1n1_pandemic.txt
│   │   │   │   │   │   │   ├── HCV3876.txt
│   │   │   │   │   │   │   ├── MERS.txt
│   │   │   │   │   │   │   ├── sequences.S.compressed.filtered.fas
│   │   │   │   │   │   │   ├── compartmentalization/
│   │   │   │   │   │   │   │   ├── compartmentalized_NL_NP.csv
│   │   │   │   │   │   │   │   ├── compartmentalized_NL_NP.new
│   │   │   │   │   │   │   │   ├── multiple_BR_LG_LN.csv
│   │   │   │   │   │   │   │   ├── multiple_BR_LG_LN.new
│   │   │   │   │   │   │   │   ├── not_compartmentalized_CL_CP.csv
│   │   │   │   │   │   │   │   ├── not_compartmentalized_CL_CP.new
│   │   │   │   │   │   ├── images/
│   │   │   │   │   │   │   ├── bar.gif
│   │   │   │   │   │   │   ├── structure.gif
│   │   │   │   │   │   ├── src/
│   │   │   │   │   │   │   ├── branches.js
│   │   │   │   │   │   │   ├── export.js
│   │   │   │   │   │   │   ├── extract-dates.js
│   │   │   │   │   │   │   ├── index.js
│   │   │   │   │   │   │   ├── main.js
│   │   │   │   │   │   │   ├── max-parsimony.js
│   │   │   │   │   │   │   ├── neighbor-join.js
│   │   │   │   │   │   │   ├── nodes.js
│   │   │   │   │   │   │   ├── rooting.js
│   │   │   │   │   │   │   ├── transformations.js
│   │   │   │   │   │   │   ├── traversal.js
│   │   │   │   │   │   │   ├── clustering/
│   │   │   │   │   │   │   │   ├── cluster-picker.js
│   │   │   │   │   │   │   │   ├── phylopart.js
│   │   │   │   │   │   │   ├── formats/
│   │   │   │   │   │   │   │   ├── beast.js
│   │   │   │   │   │   │   │   ├── newick.js
│   │   │   │   │   │   │   │   ├── nexml.js
│   │   │   │   │   │   │   │   ├── nexus.js
│   │   │   │   │   │   │   │   ├── phyloxml.js
│   │   │   │   │   │   │   │   ├── registry.js
│   │   │   │   │   │   │   ├── metrics/
│   │   │   │   │   │   │   │   ├── center-of-tree.js
│   │   │   │   │   │   │   │   ├── compute-midpoint.js
│   │   │   │   │   │   │   │   ├── pairwise-distances.js
│   │   │   │   │   │   │   │   ├── root-to-tip.js
│   │   │   │   │   │   │   │   ├── sackins.js
│   │   │   │   │   │   │   ├── msa-parsers/
│   │   │   │   │   │   │   │   ├── fasta.js
│   │   │   │   │   │   │   ├── render/
│   │   │   │   │   │   │   │   ├── cartesian.js
│   │   │   │   │   │   │   │   ├── clades.js
│   │   │   │   │   │   │   │   ├── coordinates.js
│   │   │   │   │   │   │   │   ├── draw.js
│   │   │   │   │   │   │   │   ├── edges.js
│   │   │   │   │   │   │   │   ├── event-emitter.js
│   │   │   │   │   │   │   │   ├── events.js
│   │   │   │   │   │   │   │   ├── helpers.js
│   │   │   │   │   │   │   │   ├── menus.js
│   │   │   │   │   │   │   │   ├── nodes.js
│   │   │   │   │   │   │   │   ├── options.js
│   │   │   │   │   │   │   │   ├── radial.js
│   │   │   │   │   │   │   │   ├── selection-sets.js
│   │   │   │   │   │   │   │   ├── unrooted.js
│   │   │   │   │   │   │   │   ├── styles/
│   │   │   │   │   │   │   │   │   ├── phylotree-menus.css
│   │   │   │   │   │   ├── types/
│   │   │   │   │   │   │   ├── phylotree.d.ts
│   │   │   ├── data/
│   │   │   │   ├── builtinCodes.ts
│   │   │   ├── locales/
│   │   │   │   ├── index.ts
│   │   │   ├── router/
│   │   │   │   ├── index.ts
│   │   │   ├── stores/
│   │   │   │   ├── app.ts
│   │   │   │   ├── blast.ts
│   │   │   │   ├── sequence.ts
│   │   │   │   ├── strain.ts
│   │   │   │   ├── strain/
│   │   │   │   │   ├── actions-freezer.ts
│   │   │   │   │   ├── actions-import.ts
│   │   │   │   │   ├── actions-records.ts
│   │   │   │   │   ├── actions-sync.ts
│   │   │   │   │   ├── index.ts
│   │   │   │   │   ├── state.ts
│   │   │   │   │   ├── types.ts
│   │   │   ├── types/
│   │   │   │   ├── codeSystem.ts
│   │   │   ├── utils/
│   │   │   │   ├── mockStrainData.ts
│   │   │   │   ├── storage.ts
│   │   │   ├── views/
│   │   │   │   ├── BlastView.vue
│   │   │   │   ├── DashboardView.vue
│   │   │   │   ├── HelpView.vue
│   │   │   │   ├── SettingsView.vue
│   │   │   │   ├── StrainView.vue
│   │   │   │   ├── TreeView.vue
│   ├── workbench/
│   │   ├── __init__.py
│   │   ├── bin/
│   │   ├── models/
│   │   │   ├── annotation_manager.py
│   │   │   ├── gpu_manager.py
│   │   │   ├── task_manager.py
│   │   │   ├── tool_config.py
│   │   │   ├── __init__.py
│   │   ├── pipelines/
│   │   │   ├── analysis_pipeline.py
│   │   │   ├── __init__.py
│   │   ├── wrappers/
│   │   │   ├── base_wrapper.py
│   │   │   ├── iqtree_wrapper.py
│   │   │   ├── mafft_wrapper.py
│   │   │   ├── mrbayes_wrapper.py
│   │   │   ├── tree_archive_manager.py
│   │   │   ├── tree_builder.py
│   │   │   ├── tree_distance_calculator.py
│   │   │   ├── tree_factory.py
│   │   │   ├── tree_format_converter.py
│   │   │   ├── tree_id_manager.py
│   │   │   ├── tree_sequence_processor.py
│   │   │   ├── __init__.py
├── tools/
│   ├── 1.py
│   ├── fix_imports_batch.py
│   ├── fix_init_files.py
│   ├── fix_json_comments.py
│   ├── fix_ncbi_component.py
│   ├── generate_help_docs.py
│   ├── project_fixer.py
│   ├── quick_fix_component.py
│   ├── scan_docs_errors.py
│   ├── docs/
│   │   ├── ncbi-vdb.txt
│   │   ├── ngs-sdk.txt
│   │   ├── sra-tools.txt
│   │   ├── tree-tools.txt
│   │   ├── detailed/
│   │   │   ├── abi-dump.exe.txt
│   │   │   ├── additive.exe.txt
│   │   │   ├── align-info.exe.txt
│   │   │   ├── align2html.exe.txt
│   │   │   ├── ascii.exe.txt
│   │   │   ├── asm_gap.exe.txt
│   │   │   ├── asnt.exe.txt
│   │   │   ├── asnt2tree.exe.txt
│   │   │   ├── blast2ani.exe.txt
│   │   │   ├── blast2cons.exe.txt
│   │   │   ├── blastmat.exe.txt
│   │   │   ├── blastn2mlst.exe.txt
│   │   │   ├── blastp2exons.exe.txt
│   │   │   ├── blastp_merge.exe.txt
│   │   │   ├── blast_best_hits.exe.txt
│   │   │   ├── cache-mgr.exe.txt
│   │   │   ├── check-corrupt.exe.txt
│   │   │   ├── combine_dissims.exe.txt
│   │   │   ├── compareTrees.exe.txt
│   │   │   ├── connectPairs.exe.txt
│   │   │   ├── contig2read_coverage.exe.txt
│   │   │   ├── conv_comb.exe.txt
│   │   │   ├── csv2tab.exe.txt
│   │   │   ├── disruption2genesymbol.exe.txt
│   │   │   ├── distTree_new.exe.txt
│   │   │   ├── distTree_refresh_dissim.exe.txt
│   │   │   ├── dm2feature.exe.txt
│   │   │   ├── dna2prots.exe.txt
│   │   │   ├── dna2stat.exe.txt
│   │   │   ├── dna_align_service.exe.txt
│   │   │   ├── dna_complexity.exe.txt
│   │   │   ├── dna_consensus.exe.txt
│   │   │   ├── dna_coverage.exe.txt
│   │   │   ├── dna_cut.exe.txt
│   │   │   ├── dna_diff.exe.txt
│   │   │   ├── dna_find.exe.txt
│   │   │   ├── dna_gc_skew.exe.txt
│   │   │   ├── dna_pair2dissim.exe.txt
│   │   │   ├── dna_rev.exe.txt
│   │   │   ├── dna_trim.exe.txt
│   │   │   ├── effectiveSize.exe.txt
│   │   │   ├── extractPairs.exe.txt
│   │   │   ├── fasta2dissim.exe.txt
│   │   │   ├── fasta2feature.exe.txt
│   │   │   ├── fasta2GC.exe.txt
│   │   │   ├── fasta2hash.exe.txt
│   │   │   ├── fasta2len.exe.txt
│   │   │   ├── fasta2lines.exe.txt
│   │   │   ├── fastaAddGi.exe.txt
│   │   │   ├── fastaDna2pairs.exe.txt
│   │   │   ├── fasta_prefix.exe.txt
│   │   │   ├── fasterq-dump-driver.exe.txt
│   │   │   ├── fasterq-dump.exe.txt
│   │   │   ├── fastq-dump.exe.txt
│   │   │   ├── feature2dissim.exe.txt
│   │   │   ├── feature2gain_loss.exe.txt
│   │   │   ├── feature_request2dissim.exe.txt
│   │   │   ├── file2hash.exe.txt
│   │   │   ├── filterFasta.exe.txt
│   │   │   ├── fixed2tsv.exe.txt
│   │   │   ├── genbank_grep.exe.txt
│   │   │   ├── GeneMark2CDS.exe.txt
│   │   │   ├── hash2dissim.exe.txt
│   │   │   ├── hash_request2dissim.exe.txt
│   │   │   ├── hello.exe.txt
│   │   │   ├── hmm2prot.exe.txt
│   │   │   ├── hmmAddCutoff.exe.txt
│   │   │   ├── hmmExtract.exe.txt
│   │   │   ├── hmmNAME2ACC.exe.txt
│   │   │   ├── hmmsearch2besthits.exe.txt
│   │   │   ├── hmmSplit.exe.txt
│   │   │   ├── hmm_tc1.exe.txt
│   │   │   ├── illumina-dump.exe.txt
│   │   │   ├── index_find.exe.txt
│   │   │   ├── interSeq.exe.txt
│   │   │   ├── islander.exe.txt
│   │   │   ├── kdbmeta.exe.txt
│   │   │   ├── kmerIndex_add.exe.txt
│   │   │   ├── kmerIndex_find.exe.txt
│   │   │   ├── kmerIndex_make.exe.txt
│   │   │   ├── kmerIndex_stat.exe.txt
│   │   │   ├── list2pairs.exe.txt
│   │   │   ├── loci_request2dissim.exe.txt
│   │   │   ├── main_ortholog.exe.txt
│   │   │   ├── makeDistTree.exe.txt
│   │   │   ├── makeFeatureTree.exe.txt
│   │   │   ├── mergePairs.exe.txt
│   │   │   ├── min_spanning_forest.exe.txt
│   │   │   ├── mlst2dissim.exe.txt
│   │   │   ├── mlst2hash.exe.txt
│   │   │   ├── multilist2subset.exe.txt
│   │   │   ├── mutation2feature.exe.txt
│   │   │   ├── mutation_dna2prot.exe.txt
│   │   │   ├── mutation_tab.exe.txt
│   │   │   ├── newick2tree.exe.txt
│   │   │   ├── ngs-pileup.exe.txt
│   │   │   ├── objHash_find.exe.txt
│   │   │   ├── orf2prot.exe.txt
│   │   │   ├── orthodb2fasta.exe.txt
│   │   │   ├── pairs2tsv.exe.txt
│   │   │   ├── prefetch.exe.txt
│   │   │   ├── printDistTree.exe.txt
│   │   │   ├── prot2triplets.exe.txt
│   │   │   ├── prots2hmm_signature.exe.txt
│   │   │   ├── prots_pair2stat.exe.txt
│   │   │   ├── prot_check.exe.txt
│   │   │   ├── prot_clust.exe.txt
│   │   │   ├── prot_collection2dissim.exe.txt
│   │   │   ├── prot_complexity.exe.txt
│   │   │   ├── prot_consensus.exe.txt
│   │   │   ├── prot_find.exe.txt
│   │   │   ├── prot_grep_short.exe.txt
│   │   │   ├── randomDistTree.exe.txt
│   │   │   ├── random_words.exe.txt
│   │   │   ├── rcexplain.exe.txt
│   │   │   ├── ref-variation.exe.txt
│   │   │   ├── replaceDistTree_match.exe.txt
│   │   │   ├── replaceDistTree_reroot.exe.txt
│   │   │   ├── replaceFastaHeader.exe.txt
│   │   │   ├── replace_dict.exe.txt
│   │   │   ├── sam-dump-driver.exe.txt
│   │   │   ├── sam-dump.exe.txt
│   │   │   ├── seq2dissim.exe.txt
│   │   │   ├── seq_print.exe.txt
│   │   │   ├── setMinus.exe.txt
│   │   │   ├── setRandOrd.exe.txt
│   │   │   ├── sff-dump.exe.txt
│   │   │   ├── splitFasta.exe.txt
│   │   │   ├── splitList.exe.txt
│   │   │   ├── sra-info.exe.txt
│   │   │   ├── sra-pileup-driver.exe.txt
│   │   │   ├── sra-pileup.exe.txt
│   │   │   ├── sra-search.exe.txt
│   │   │   ├── sra-stat.exe.txt
│   │   │   ├── srapath.exe.txt
│   │   │   ├── sratools.exe.txt
│   │   │   ├── statDistTree.exe.txt
│   │   │   ├── str2hash.exe.txt
│   │   │   ├── symbet.exe.txt
│   │   │   ├── symbet_blastp.exe.txt
│   │   │   ├── tblastn2disruption.exe.txt
│   │   │   ├── tblastn2marker_euk.exe.txt
│   │   │   ├── tblastn2orfs.exe.txt
│   │   │   ├── trav.exe.txt
│   │   │   ├── tree2genogroup.exe.txt
│   │   │   ├── tree2indiscern.exe.txt
│   │   │   ├── triple2tsv.exe.txt
│   │   │   ├── tsv2html.exe.txt
│   │   │   ├── tsv2insert.exe.txt
│   │   │   ├── tsv2triple.exe.txt
│   │   │   ├── tsv_aggr_comp.exe.txt
│   │   │   ├── tsv_cat.exe.txt
│   │   │   ├── tsv_cluster.exe.txt
│   │   │   ├── tsv_comp.exe.txt
│   │   │   ├── tsv_group.exe.txt
│   │   │   ├── tsv_join.exe.txt
│   │   │   ├── tsv_null.exe.txt
│   │   │   ├── tsv_rename.exe.txt
│   │   │   ├── tsv_schema.exe.txt
│   │   │   ├── tsv_shift.exe.txt
│   │   │   ├── tsv_split.exe.txt
│   │   │   ├── uniqProtRef.exe.txt
│   │   │   ├── uniqSeq.exe.txt
│   │   │   ├── var-expand.exe.txt
│   │   │   ├── vdb-config.exe.txt
│   │   │   ├── vdb-decrypt.exe.txt
│   │   │   ├── vdb-dump-driver.exe.txt
│   │   │   ├── vdb-dump.exe.txt
│   │   │   ├── vdb-encrypt.exe.txt
│   │   │   ├── vdb-validate.exe.txt
│   │   │   ├── xml2schema.exe.txt
│   │   │   ├── xml_bin2txt.exe.txt
│   │   │   ├── xml_find.exe.txt
│   │   │   ├── xml_merge_schemas.exe.txt
│   │   │   ├── xml_print.exe.txt
│   │   │   ├── xml_schema2ddl.exe.txt
│   │   │   ├── xml_schema2flat.exe.txt
│   │   │   ├── xml_txt2bin.exe.txt
│   ├── iqtree3_win/
│   │   ├── iqtree-3.1.1-Windows/
│   │   │   ├── example.cf
│   │   │   ├── example.nex
│   │   │   ├── example.phy
│   │   │   ├── models.nex
│   │   │   ├── bin/
│   ├── iqtree_new/
│   │   ├── iqtree-2.4.0-Windows/
│   │   │   ├── example.cf
│   │   │   ├── example.nex
│   │   │   ├── example.phy
│   │   │   ├── models.nex
│   │   │   ├── bin/
│   ├── mafft/
│   │   ├── mafft-win/
│   │   │   ├── mafft-signed.ps1
│   │   │   ├── mafft.bat
│   │   │   ├── tmp/
│   │   │   ├── usr/
│   │   │   │   ├── bin/
│   │   │   │   │   ├── mafft
│   │   │   │   │   ├── mafft-homologs.rb
│   │   │   │   ├── lib/
│   │   │   │   │   ├── mafft/
│   │   │   │   │   │   ├── mafft-homologs.1
│   │   │   │   │   │   ├── mafft.1
│   │   │   │   │   │   ├── mafftash_premafft.pl
│   │   │   │   │   │   ├── seekquencer_premafft.pl
│   │   │   │   ├── share/
│   │   │   │   │   ├── misc/
│   │   │   │   │   │   ├── magic
│   ├── ncbi_dist/
│   │   ├── bin/
│   │   │   ├── sra-tools/
│   │   │   ├── tree-tools/
│   │   │   │   ├── f2d_help.txt
│   │   │   │   ├── f2h_help.txt
│   │   │   │   ├── h2d_help.txt
│   │   │   │   ├── mafft.bat
│   │   │   │   ├── s2d_help.txt
│   │   │   │   ├── split_help.txt
│   │   ├── lib/
│   │   │   ├── ncbi-vdb/
│   │   │   │   ├── libalign-access.a
│   │   │   │   ├── libalign-reader.a
│   │   │   │   ├── libalign-writer.a
│   │   │   │   ├── libaxf.a
│   │   │   │   ├── libbz2.a
│   │   │   │   ├── libcloud.a
│   │   │   │   ├── libjudy.a
│   │   │   │   ├── libkdb.a
│   │   │   │   ├── libkdbtext.a
│   │   │   │   ├── libkfc.a
│   │   │   │   ├── libkfg.a
│   │   │   │   ├── libkfs-nommap.a
│   │   │   │   ├── libkfs.a
│   │   │   │   ├── libklib.a
│   │   │   │   ├── libkns.a
│   │   │   │   ├── libkproc.a
│   │   │   │   ├── libkq.a
│   │   │   │   ├── libkrypto.a
│   │   │   │   ├── libktst.a
│   │   │   │   ├── libmbedcrypto.a
│   │   │   │   ├── libmbedtls.a
│   │   │   │   ├── libmbedx509.a
│   │   │   │   ├── libncbi-bam.a
│   │   │   │   ├── libncbi-vdb.a
│   │   │   │   ├── libncbi-vdb.dll.a
│   │   │   │   ├── libncbi-wvdb.a
│   │   │   │   ├── libncbi-wvdb.dll.a
│   │   │   │   ├── libsam-extract.a
│   │   │   │   ├── libschema.a
│   │   │   │   ├── libsradb.a
│   │   │   │   ├── libsrareader.a
│   │   │   │   ├── libsraxf.a
│   │   │   │   ├── libvdb-blast.a
│   │   │   │   ├── libvdb.a
│   │   │   │   ├── libvdbapp.a
│   │   │   │   ├── libvfs.a
│   │   │   │   ├── libvxf.a
│   │   │   │   ├── libwaxf.a
│   │   │   │   ├── libwgsxf.a
│   │   │   │   ├── libwsradb.a
│   │   │   │   ├── libwsraxf.a
│   │   │   │   ├── libwvdb.a
│   │   │   │   ├── libwvxf.a
│   │   │   │   ├── libwwgsxf.a
│   │   │   │   ├── libz.a
│   │   │   │   ├── libzstd.a
│   │   │   │   ├── objects.a
│   │   │   ├── ngs-sdk/
│   │   │   │   ├── libngs-sdk.a
│   ├── _deprecated/
├── vendor/
│   ├── __init__.py
│   ├── ete4/
│   │   ├── CODE_OF_CONDUCT.md
│   │   ├── CONTRIBUTING.md
│   │   ├── LICENSE
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── setup.py
│   │   ├── THANKS.md
│   │   ├── VERSION
│   │   ├── doc/
│   │   │   ├── about.rst
│   │   │   ├── conf.py
│   │   │   ├── faqs.rst
│   │   │   ├── index.rst
│   │   │   ├── make.bat
│   │   │   ├── Makefile
│   │   │   ├── images/
│   │   │   │   ├── collapsed.png
│   │   │   │   ├── combined.png
│   │   │   │   ├── context_menu.png
│   │   │   │   ├── draw_node.png
│   │   │   │   ├── example_layout_functions.png
│   │   │   │   ├── face_aligned.png
│   │   │   │   ├── face_borders.png
│   │   │   │   ├── face_bottom.png
│   │   │   │   ├── face_bottom2.png
│   │   │   │   ├── face_positions.png
│   │   │   │   ├── face_properties.png
│   │   │   │   ├── gallery.png
│   │   │   │   ├── gui.png
│   │   │   │   ├── layout_example.png
│   │   │   │   ├── my_layout.png
│   │   │   │   ├── node_backgrounds.png
│   │   │   │   ├── node_id.png
│   │   │   │   ├── node_style_red_and_blue_nodes.png
│   │   │   │   ├── node_style_red_nodes.png
│   │   │   │   ├── not_collapsed.png
│   │   │   │   ├── panel.png
│   │   │   │   ├── panel_advanced.png
│   │   │   │   ├── panel_main.png
│   │   │   │   ├── panel_selections.png
│   │   │   │   ├── preorder.png
│   │   │   │   ├── rotated_tree.png
│   │   │   │   ├── scale_x.png
│   │   │   │   ├── scale_y.png
│   │   │   │   ├── semi_circular_tree.png
│   │   │   │   ├── show_info.png
│   │   │   │   ├── size.png
│   │   │   │   ├── tree.png
│   │   │   │   ├── tree_parts.png
│   │   │   │   ├── vowels.png
│   │   │   │   ├── walk.png
│   │   │   ├── internals/
│   │   │   │   ├── index.rst
│   │   │   │   ├── internals_api.rst
│   │   │   │   ├── internals_detailed_layout.rst
│   │   │   │   ├── internals_drawing.rst
│   │   │   │   ├── internals_essentials.rst
│   │   │   │   ├── internals_overview.rst
│   │   │   ├── reference/
│   │   │   │   ├── index.rst
│   │   │   │   ├── reference_operations.rst
│   │   │   │   ├── reference_parsers.rst
│   │   │   │   ├── reference_phylo.rst
│   │   │   │   ├── reference_seqgroup.rst
│   │   │   │   ├── reference_smartview.rst
│   │   │   │   ├── reference_taxonomy.rst
│   │   │   │   ├── reference_tree.rst
│   │   │   │   ├── reference_treematcher.rst
│   │   │   │   ├── reference_treeview.rst
│   │   │   ├── tutorial/
│   │   │   │   ├── index.rst
│   │   │   │   ├── tutorial_phylogeny.rst
│   │   │   │   ├── tutorial_smartview.rst
│   │   │   │   ├── tutorial_taxonomy.rst
│   │   │   │   ├── tutorial_treematcher.rst
│   │   │   │   ├── tutorial_trees.rst
│   │   │   │   ├── tutorial_treeview.rst
│   │   │   ├── _static/
│   │   │   │   ├── favicon.ico
│   │   ├── ete4/
│   │   │   ├── citation.py
│   │   │   ├── config.py
│   │   │   ├── utils.py
│   │   │   ├── version.py
│   │   │   ├── __init__.py
│   │   │   ├── core/
│   │   │   │   ├── operations.c
│   │   │   │   ├── operations.cp313-win_amd64.pyd
│   │   │   │   ├── operations.pyx
│   │   │   │   ├── seqgroup.py
│   │   │   │   ├── text_viz.py
│   │   │   │   ├── tree.c
│   │   │   │   ├── tree.cp313-win_amd64.pyd
│   │   │   │   ├── tree.pyx
│   │   │   │   ├── __init__.py
│   │   │   ├── evol/
│   │   │   │   ├── control.py
│   │   │   │   ├── evoltree.py
│   │   │   │   ├── model.py
│   │   │   │   ├── utils.py
│   │   │   │   ├── __init__.py
│   │   │   │   ├── parser/
│   │   │   │   │   ├── codemlparser.py
│   │   │   │   │   ├── slrparser.py
│   │   │   │   │   ├── __init__.py
│   │   │   ├── gtdb_taxonomy/
│   │   │   │   ├── gtdbquery.py
│   │   │   │   ├── __init__.py
│   │   │   ├── ncbi_taxonomy/
│   │   │   │   ├── ncbiquery.py
│   │   │   │   ├── __init__.py
│   │   │   │   ├── SQLite-Levenshtein/
│   │   │   │   │   ├── EXAMPLE
│   │   │   │   │   ├── Makefile
│   │   │   │   │   ├── README
│   │   │   │   │   ├── src/
│   │   │   │   │   │   ├── levenshtein.c
│   │   │   ├── orthoxml/
│   │   │   │   ├── _orthoxml.py
│   │   │   │   ├── __init__.py
│   │   │   ├── parser/
│   │   │   │   ├── ete_format.py
│   │   │   │   ├── fasta.py
│   │   │   │   ├── indent.py
│   │   │   │   ├── newick.c
│   │   │   │   ├── newick.cp313-win_amd64.pyd
│   │   │   │   ├── newick.pyx
│   │   │   │   ├── nexus.py
│   │   │   │   ├── paml.py
│   │   │   │   ├── phylip.py
│   │   │   │   ├── __init__.py
│   │   │   ├── phylo/
│   │   │   │   ├── evolevents.py
│   │   │   │   ├── phylotree.py
│   │   │   │   ├── reconciliation.py
│   │   │   │   ├── spoverlap.py
│   │   │   │   ├── __init__.py
│   │   │   ├── phyloxml/
│   │   │   │   ├── _phyloxml.py
│   │   │   │   ├── _phyloxml_tree.py
│   │   │   │   ├── __init__.py
│   │   │   ├── smartview/
│   │   │   │   ├── coordinates.py
│   │   │   │   ├── draw.py
│   │   │   │   ├── explorer.py
│   │   │   │   ├── faces.py
│   │   │   │   ├── graphics.py
│   │   │   │   ├── layout.py
│   │   │   │   ├── __init__.py
│   │   │   │   ├── static/
│   │   │   │   │   ├── gui.css
│   │   │   │   │   ├── gui.html
│   │   │   │   │   ├── upload.css
│   │   │   │   │   ├── upload.html
│   │   │   │   │   ├── external/
│   │   │   │   │   │   ├── pixi.min.mjs
│   │   │   │   │   │   ├── readme.md
│   │   │   │   │   │   ├── sweetalert2.min.js
│   │   │   │   │   │   ├── tweakpane.min.js
│   │   │   │   │   ├── images/
│   │   │   │   │   │   ├── icon.png
│   │   │   │   │   │   ├── spritesheet.json
│   │   │   │   │   │   ├── spritesheet.png
│   │   │   │   │   ├── js/
│   │   │   │   │   │   ├── api.js
│   │   │   │   │   │   ├── collapse.js
│   │   │   │   │   │   ├── contextmenu.js
│   │   │   │   │   │   ├── download.js
│   │   │   │   │   │   ├── drag.js
│   │   │   │   │   │   ├── draw.js
│   │   │   │   │   │   ├── events.js
│   │   │   │   │   │   ├── gui.js
│   │   │   │   │   │   ├── label.js
│   │   │   │   │   │   ├── menu.js
│   │   │   │   │   │   ├── minimap.js
│   │   │   │   │   │   ├── pixi.js
│   │   │   │   │   │   ├── search.js
│   │   │   │   │   │   ├── tag.js
│   │   │   │   │   │   ├── upload.js
│   │   │   │   │   │   ├── zoom.js
│   │   │   ├── tools/
│   │   │   │   ├── common.py
│   │   │   │   ├── ete.py
│   │   │   │   ├── ete_annotate.py
│   │   │   │   ├── ete_build.cfg
│   │   │   │   ├── ete_build.py
│   │   │   │   ├── ete_compare.py
│   │   │   │   ├── ete_diff.py
│   │   │   │   ├── ete_evol.py
│   │   │   │   ├── ete_expand.py
│   │   │   │   ├── ete_explore.py
│   │   │   │   ├── ete_extract.py
│   │   │   │   ├── ete_generate.py
│   │   │   │   ├── ete_maptrees.py
│   │   │   │   ├── ete_mod.py
│   │   │   │   ├── ete_ncbiquery.py
│   │   │   │   ├── ete_split.py
│   │   │   │   ├── ete_upgrade_tools.py
│   │   │   │   ├── ete_view.py
│   │   │   │   ├── utils.py
│   │   │   │   ├── __init__.py
│   │   │   │   ├── ete_build_lib/
│   │   │   │   │   ├── apps.py
│   │   │   │   │   ├── configcheck.py
│   │   │   │   │   ├── configobj.py
│   │   │   │   │   ├── curses_gui.py
│   │   │   │   │   ├── db.py
│   │   │   │   │   ├── errors.py
│   │   │   │   │   ├── getch.py
│   │   │   │   │   ├── interface.py
│   │   │   │   │   ├── logger.py
│   │   │   │   │   ├── master_job.py
│   │   │   │   │   ├── master_task.py
│   │   │   │   │   ├── scheduler.py
│   │   │   │   │   ├── seqio.py
│   │   │   │   │   ├── sge.py
│   │   │   │   │   ├── utils.py
│   │   │   │   │   ├── validate.py
│   │   │   │   │   ├── visualize.py
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── task/
│   │   │   │   │   │   ├── clustalo.py
│   │   │   │   │   │   ├── cog_creator.py
│   │   │   │   │   │   ├── cog_selector.py
│   │   │   │   │   │   ├── concat_alg.py
│   │   │   │   │   │   ├── dialigntx.py
│   │   │   │   │   │   ├── dummyalg.py
│   │   │   │   │   │   ├── dummytree.py
│   │   │   │   │   │   ├── fasttree.py
│   │   │   │   │   │   ├── iqtree.py
│   │   │   │   │   │   ├── mafft.py
│   │   │   │   │   │   ├── merger.py
│   │   │   │   │   │   ├── meta_aligner.py
│   │   │   │   │   │   ├── msf.py
│   │   │   │   │   │   ├── muscle.py
│   │   │   │   │   │   ├── phyml.py
│   │   │   │   │   │   ├── raxml.py
│   │   │   │   │   │   ├── tcoffee.py
│   │   │   │   │   │   ├── trimal.py
│   │   │   │   │   │   ├── uhire.py
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── workflow/
│   │   │   │   │   │   ├── common.py
│   │   │   │   │   │   ├── genetree.py
│   │   │   │   │   │   ├── supermatrix.py
│   │   │   │   │   │   ├── __init__.py
│   │   │   ├── treematcher/
│   │   │   │   ├── treematcher.py
│   │   │   │   ├── __init__.py
│   │   │   ├── treeview/
│   │   │   │   ├── about.ui
│   │   │   │   ├── clean_search.png
│   │   │   │   ├── drawer.py
│   │   │   │   ├── ete_icon.png
│   │   │   │   ├── ete_logo.png
│   │   │   │   ├── ete_qt4app.ui
│   │   │   │   ├── ete_resources.qrc
│   │   │   │   ├── ete_resources_rc.py
│   │   │   │   ├── export_pdf.png
│   │   │   │   ├── faces.py
│   │   │   │   ├── fileopen.png
│   │   │   │   ├── filesave.png
│   │   │   │   ├── fit_region.png
│   │   │   │   ├── fit_tree.png
│   │   │   │   ├── force_topo.png
│   │   │   │   ├── image_properties.ui
│   │   │   │   ├── layouts.py
│   │   │   │   ├── main.py
│   │   │   │   ├── node_gui_actions.py
│   │   │   │   ├── open_newick.ui
│   │   │   │   ├── qt.py
│   │   │   │   ├── qt4_compile_resources.sh
│   │   │   │   ├── qt_circular_render.py
│   │   │   │   ├── qt_face_render.py
│   │   │   │   ├── qt_gui.py
│   │   │   │   ├── qt_rect_render.py
│   │   │   │   ├── qt_render.py
│   │   │   │   ├── search.png
│   │   │   │   ├── search_dialog.ui
│   │   │   │   ├── show_dist.png
│   │   │   │   ├── show_names.png
│   │   │   │   ├── show_newick.png
│   │   │   │   ├── show_newick.ui
│   │   │   │   ├── show_support.png
│   │   │   │   ├── templates.py
│   │   │   │   ├── x_expand.png
│   │   │   │   ├── x_reduce.png
│   │   │   │   ├── y_expand.png
│   │   │   │   ├── y_reduce.png
│   │   │   │   ├── zoom_in.png
│   │   │   │   ├── zoom_out.png
│   │   │   │   ├── _about.py
│   │   │   │   ├── _mainwindow.py
│   │   │   │   ├── _open_newick.py
│   │   │   │   ├── _search_dialog.py
│   │   │   │   ├── _show_codeml.py
│   │   │   │   ├── _show_newick.py
│   │   │   │   ├── __init__.py
│   │   ├── ete4.egg-info/
│   │   │   ├── dependency_links.txt
│   │   │   ├── entry_points.txt
│   │   │   ├── PKG-INFO
│   │   │   ├── requires.txt
│   │   │   ├── SOURCES.txt
│   │   │   ├── top_level.txt
│   │   ├── examples/
│   │   │   ├── evol/
│   │   │   │   ├── 1_freeratio.py
│   │   │   │   ├── 2_sites_model.py
│   │   │   │   ├── 4_branch_models.py
│   │   │   │   ├── 6_ancestral_sequence.py
│   │   │   │   ├── 7_slr.py
│   │   │   │   ├── measuring_evolution_trees.py
│   │   │   │   ├── README
│   │   │   ├── general/
│   │   │   │   ├── add_features.py
│   │   │   │   ├── byoperand_search.py
│   │   │   │   ├── chimp.png
│   │   │   │   ├── copy_and_paste_trees.py
│   │   │   │   ├── create_trees_from_scratch.py
│   │   │   │   ├── custom_search.py
│   │   │   │   ├── custom_tree_traversing.py
│   │   │   │   ├── custom_tree_visualization.py
│   │   │   │   ├── dog.png
│   │   │   │   ├── fish.png
│   │   │   │   ├── fly.png
│   │   │   │   ├── genes_tree.nh
│   │   │   │   ├── getting_leaves.py
│   │   │   │   ├── get_common_ancestor.py
│   │   │   │   ├── get_distances_between_nodes.py
│   │   │   │   ├── get_midpoint_outgroup.py
│   │   │   │   ├── human.png
│   │   │   │   ├── iterators.py
│   │   │   │   ├── label_nodes.py
│   │   │   │   ├── mouse.png
│   │   │   │   ├── nhx_format.py
│   │   │   │   ├── prune_tree.py
│   │   │   │   ├── random_tree.png
│   │   │   │   ├── read_newick.py
│   │   │   │   ├── remove_and_delete_nodes.py
│   │   │   │   ├── render_tree_images.py
│   │   │   │   ├── rooting_subtrees.py
│   │   │   │   ├── rooting_trees.py
│   │   │   │   ├── search_nodes.py
│   │   │   │   ├── tree_basis.py
│   │   │   │   ├── tree_traverse.py
│   │   │   │   ├── write_newick.py
│   │   │   ├── phylogenies/
│   │   │   │   ├── dating_evolutionary_events.py
│   │   │   │   ├── link_sequences_to_phylogenies.py
│   │   │   │   ├── orthology_and_paralogy_prediction.py
│   │   │   │   ├── phylotree.png
│   │   │   │   ├── phylotree_visualization.py
│   │   │   │   ├── species_aware_phylogenies.py
│   │   │   │   ├── tree_reconciliation.py
│   │   │   ├── phyloxml/
│   │   │   │   ├── apaf.xml
│   │   │   │   ├── bcl_2.xml
│   │   │   │   ├── example1.xml
│   │   │   │   ├── example2.xml
│   │   │   │   ├── example3.xml
│   │   │   │   ├── multiple_supports.xml
│   │   │   │   ├── phyloxml_examples.xml
│   │   │   │   ├── phyloxml_from_scratch.py
│   │   │   │   ├── phyloxml_parser.py
│   │   │   ├── treeview/
│   │   │   │   ├── barcharts.png
│   │   │   │   ├── barchart_and_piechart_faces.py
│   │   │   │   ├── bubble_map.png
│   │   │   │   ├── bubble_map.py
│   │   │   │   ├── face_grid.py
│   │   │   │   ├── face_grid_tutorial.py
│   │   │   │   ├── face_positions.py
│   │   │   │   ├── face_rotation.py
│   │   │   │   ├── floating_piecharts.py
│   │   │   │   ├── float_piechart.png
│   │   │   │   ├── item_faces.png
│   │   │   │   ├── item_faces.py
│   │   │   │   ├── new_seq_face.py
│   │   │   │   ├── node_background.png
│   │   │   │   ├── node_background.py
│   │   │   │   ├── node_style.png
│   │   │   │   ├── node_style.py
│   │   │   │   ├── random_draw.py
│   │   │   │   ├── rotated_faces.png
│   │   │   │   ├── seqmotif.png
│   │   │   │   ├── seq_motif_faces.png
│   │   │   │   ├── seq_motif_faces.py
│   │   │   │   ├── tree_faces.png
│   │   │   │   ├── tree_faces.py
│   │   │   │   ├── img_faces/
│   │   │   │   │   ├── chimp.png
│   │   │   │   │   ├── dog.png
│   │   │   │   │   ├── fish.png
│   │   │   │   │   ├── fly.png
│   │   │   │   │   ├── human.png
│   │   │   │   │   ├── img_faces.png
│   │   │   │   │   ├── img_faces.py
│   │   │   │   │   ├── mouse.png
│   │   ├── utils/
│   │   │   ├── FILE_HEADER.txt
│   │   │   ├── release.py
│   │   │   ├── update_license.py
│   │   │   ├── conda_build/
│   │   │   │   ├── build.sh.template
│   │   │   │   ├── meta.yaml.template
│   │   │   │   ├── release_conda.sh
│   ├── fasttree/
│   │   ├── LICENSE
│   ├── iqtree3/
│   │   ├── iqtree_help_full.txt
│   │   ├── LICENSE
│   ├── iqtree3_linux/
│   │   ├── example.cf
│   │   ├── example.nex
│   │   ├── example.phy
│   │   ├── iqtree_linux.tar.gz
│   │   ├── models.nex
│   │   ├── bin/
│   │   │   ├── iqtree2
│   ├── MrBayes/
│   │   ├── COPYING
```