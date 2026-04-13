<template>
  <div class="form-section">
    <h4 class="section-label">序列数据 (FASTA)</h4>
    <textarea
      :value="modelValue"
      @input="updateValue"
      class="text-input textarea"
      placeholder=">Sequence_Title&#10;ATGCGATCG..."
      rows="4"
    ></textarea>
    
    <!-- 基因库同步选项 -->
    <div class="gene-sync-opt" v-if="modelValue">
      <label class="checkbox-container">
        <input type="checkbox" :checked="syncEnabled" @change="e => emit('update:syncEnabled', (e.target as HTMLInputElement).checked)" />
        <span class="checkmark"></span>
        <span class="checkbox-label">同步录入到基因数据库 (Gene DB)</span>
      </label>
      
      <div v-if="syncEnabled" class="gene-details-panel">
        <div class="form-row">
          <div class="form-group">
            <label>测序类型</label>
            <div class="custom-select" @click.stop="toggleDropdown('seqType')">
              <div class="select-trigger">
                {{ getGeneSeqTypeLabel() }}
                <span class="arrow">▾</span>
              </div>
              <div v-if="openDropdown === 'seqType'" class="select-dropdown">
                <div
                  v-for="opt in GENE_SEQ_TYPE_OPTIONS"
                  :key="opt.value"
                  class="select-option"
                  @click.stop="handleSelect('seqType', opt.value)"
                >
                  {{ opt.label }}
                </div>
              </div>
            </div>
          </div>
          <div class="form-group">
            <label>测序标题/批次</label>
            <input 
              :value="geneTitle" 
              @input="e => emit('update:geneTitle', (e.target as HTMLInputElement).value)"
              class="text-input" 
              placeholder="默认：[样本编号]-[类型]" 
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  modelValue: string
  syncEnabled: boolean
  geneSeqType: string
  geneTitle: string
}>()

const emit = defineEmits(['update:modelValue', 'update:syncEnabled', 'update:geneSeqType', 'update:geneTitle'])

const openDropdown = ref<string | null>(null)

const GENE_SEQ_TYPE_OPTIONS = [
  { value: '16S', label: '16S rRNA' },
  { value: 'ITS', label: 'ITS' },
  { value: 'WGS', label: '全基因组 (WGS)' },
  { value: 'Plasmid', label: '质粒全长' },
  { value: 'TargetGen', label: '目标基因' }
]

function updateValue(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

function getGeneSeqTypeLabel(): string {
  return GENE_SEQ_TYPE_OPTIONS.find(o => o.value === props.geneSeqType)?.label || '16S rRNA'
}

function toggleDropdown(name: string) {
  openDropdown.value = openDropdown.value === name ? null : name
}

function handleSelect(field: string, value: string) {
  emit('update:geneSeqType', value)
  openDropdown.value = null
}
</script>

<style scoped>
/* 包含必要的样式片段 */
.form-section { margin-bottom: 24px; }
.section-label { font-size: 0.85rem; font-weight: 700; color: #64748b; margin-bottom: 12px; }
.text-input { width: 100%; padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 8px; }
.textarea { font-family: monospace; font-size: 0.85rem; resize: vertical; }
.gene-sync-opt { margin-top: 12px; padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px dashed #cbd5e1; }
.gene-details-panel { margin-top: 12px; padding-top: 12px; border-top: 1px solid #e2e8f0; }
.form-row { display: flex; gap: 16px; }
.form-group { flex: 1; margin-bottom: 12px; }
.custom-select { position: relative; cursor: pointer; }
.select-trigger { padding: 10px 14px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; display: flex; justify-content: space-between; }
.select-dropdown { position: absolute; top: 100%; left: 0; width: 100%; background: white; border: 1px solid #e2e8f0; border-radius: 8px; z-index: 100; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
.select-option { padding: 10px 14px; cursor: pointer; }
.select-option:hover { background: #f1f5f9; }
</style>
