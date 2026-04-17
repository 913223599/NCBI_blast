<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getBridge } from '../../bridge'
import { useBlastStore } from '../../stores/blast'
import { useI18n } from '../../locales'

const props = defineProps<{
  openDropdown: string | null
}>()

const emit = defineEmits<{
  (e: 'toggleDropdown', id: string, event: Event): void
  (e: 'selectOption', id: string, value: any): void
}>()

const blast = useBlastStore()
const { t } = useI18n()

/* -------- 数据常量与状态 -------- */
const dbOptions = ref<{ nucleotide: any[], protein: any[] }>({
  nucleotide: [
    { value: 'nt', label: 'nt - 全球核酸库' },
    { value: 'refseq_rna', label: 'refseq_rna - 参考 RNA' },
    { value: 'refseq_genomic', label: 'refseq_genomic - 参考基因组' }
  ],
  protein: [
    { value: 'nr', label: 'nr - 非冗余蛋白库' },
    { value: 'swissprot', label: 'swissprot - Swiss-Prot' }
  ]
})

async function fetchDatabases() {
  try {
    const res = await getBridge().get_blast_databases()
    if (Array.isArray(res)) {
       // 将本地库加入列表
       res.forEach(db => {
         const opt = { value: db.name, label: db.display_name || db.name }
         if (db.type === 'prot') {
            if (!dbOptions.value.protein.find((o: any) => o.value === opt.value))
              dbOptions.value.protein.push(opt)
         } else {
            if (!dbOptions.value.nucleotide.find((o: any) => o.value === opt.value))
              dbOptions.value.nucleotide.push(opt)
         }
       })
    }
  } catch (e) {
    console.error('Failed to fetch blast databases', e)
  }
}

onMounted(() => {
  fetchDatabases()
})

const MATRIX_OPTIONS = [{ value: 'BLOSUM62', label: 'BLOSUM62' }, { value: 'PAM30', label: 'PAM30' }]
const PROGRAM_OPTIONS = [
  { value: 'auto', label: '自动识别' },
  { value: 'blastn', label: 'blastn (核酸)' },
  { value: 'blastp', label: 'blastp (蛋白)' }
]

function getProgramLabel() { return PROGRAM_OPTIONS.find(o => o.value === blast.params.program)?.label || '核酸/蛋白' }
function getDatabaseLabel() { 
  const all = [...dbOptions.value.nucleotide, ...dbOptions.value.protein]
  return all.find(o => o.value === blast.params.database)?.label || blast.params.database || '选择库'
}
function getMatrixLabel() { return MATRIX_OPTIONS.find(o => o.value === blast.params.matrix)?.label || '选择矩阵' }
</script>

<template>
  <div class="panel-section">
    <h3 class="section-title">{{ t('blast.param.title') }}</h3>
    <div class="form-group">
      <label>{{ t('blast.param.prog') }}</label>
      <div class="select-box-neo" @click.stop="emit('toggleDropdown', 'program', $event)">
        {{ getProgramLabel() }} <span class="arrow">▼</span>
        <div v-if="openDropdown === 'program'" class="dropdown-list">
          <div v-for="o in PROGRAM_OPTIONS" :key="o.value" class="opt" @click="emit('selectOption', 'program', o.value)">{{ o.label }}</div>
        </div>
      </div>
    </div>
    <div class="form-group">
      <label>{{ t('blast.param.db') }}</label>
      <div class="select-box-neo" @click.stop="emit('toggleDropdown', 'db', $event)">
         {{ getDatabaseLabel() }} <span class="arrow">▼</span>
         <div v-if="openDropdown === 'db'" class="dropdown-list">
            <div class="group">核酸</div>
            <div v-for="o in dbOptions.nucleotide" :key="o.value" class="opt" @click="emit('selectOption', 'database', o.value)">{{ o.label }}</div>
            <div class="group">蛋白</div>
            <div v-for="o in dbOptions.protein" :key="o.value" class="opt" @click="emit('selectOption', 'database', o.value)">{{ o.label }}</div>
         </div>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>{{ t('blast.param.eval') }}</label>
        <input type="number" v-model="blast.params.evalue" class="neo-input" />
      </div>
      <div class="form-group">
        <label>{{ t('blast.param.max') }}</label>
        <input type="number" v-model="blast.params.maxHits" class="neo-input" />
      </div>
    </div>
    <div class="form-group">
      <label>{{ t('blast.param.threads') }}</label>
      <input type="number" v-model="blast.params.threads" class="neo-input" min="1" max="128" />
    </div>
    <div class="form-group checkbox-group">
      <input type="checkbox" id="filter-complex" v-model="blast.params.filterLowComplexity" />
      <label for="filter-complex">{{ t('blast.param.filter') }}</label>
    </div>

    <h3 class="section-title sub">{{ t('blast.model.title') }}</h3>
    <div class="form-group">
      <label>{{ t('blast.model.matrix') }}</label>
      <div class="select-box-neo" @click.stop="emit('toggleDropdown', 'matrix', $event)">
        {{ getMatrixLabel() }} <span class="arrow">▼</span>
        <div v-if="openDropdown === 'matrix'" class="dropdown-list">
          <div v-for="o in MATRIX_OPTIONS" :key="o.value" class="opt" @click="emit('selectOption', 'matrix', o.value)">
            {{ o.label }}</div>
        </div>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Gap Open</label>
        <input type="number" v-model="blast.params.gapOpen" class="neo-input" />
      </div>
      <div class="form-group">
        <label>Gap Extend</label>
        <input type="number" v-model="blast.params.gapExtend" class="neo-input" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 16px;
}

.section-title.sub {
  margin-top: 24px;
  font-size: 0.8rem;
  opacity: 0.7;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 6px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.neo-input {
  width: 100%;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 0.85rem;
  color: #334155;
  outline: none;
  transition: all 0.2s;
}

.neo-input:focus {
  border-color: #2563eb;
  background: white;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.select-box-neo {
  width: 100%;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 0.85rem;
  color: #334155;
  cursor: pointer;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.select-box-neo:hover {
  border-color: #cbd5e1;
}

.select-box-neo .arrow {
  font-size: 0.6rem;
  opacity: 0.5;
}

.dropdown-list {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  z-index: 50;
  max-height: 250px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 6px;
}

.dropdown-list .opt {
  padding: 8px 12px;
  font-size: 0.82rem;
  border-radius: 6px;
  color: #475569;
}

.dropdown-list .opt:hover {
  background: #f1f5f9;
  color: #2563eb;
}

.dropdown-list .group {
  padding: 8px 12px;
  font-size: 0.7rem;
  font-weight: 800;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: #f8fafc;
  margin: 4px -6px;
  pointer-events: none;
}

.checkbox-group {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.checkbox-group input {
  width: 16px;
  height: 16px;
  accent-color: #2563eb;
  cursor: pointer;
}

.checkbox-group label {
  margin-bottom: 0;
  cursor: pointer;
}
</style>
