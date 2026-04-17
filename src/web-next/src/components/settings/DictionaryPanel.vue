<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { getBridge, onEvent } from '../../bridge'
import { useAppStore } from '../../stores/app'
import { useVirtualList } from '@vueuse/core'

const appStore = useAppStore()

const dictQuery = ref('')
const selectedCategory = ref('all')
const dictResults = ref<any[]>([])
const loadingDict = ref(false)
const proofreadMode = ref(false)
const newTermEn = ref('')
const newTermZh = ref('')
const newTermCat = ref('species')
const isAuditing = ref(false)

const dictCategories = [
  { id: 'all', label: '全部类别' },
  { id: 'kingdom', label: '界 (Kingdom)' },
  { id: 'phylum', label: '门 (Phylum)' },
  { id: 'class_rank', label: '纲 (Class)' },
  { id: 'order', label: '目 (Order)' },
  { id: 'family', label: '科 (Family)' },
  { id: 'genus', label: '属 (Genus)' },
  { id: 'species', label: '物种 (Species)' },
  { id: 'gene', label: '基因 (Gene)' },
  { id: 'location', label: '地理/来源 (Location)' },
  { id: 'other', label: '其他 (Other)' }
]

// 过滤后的显示数据
const filteredResults = computed(() => {
  if (selectedCategory.value === 'all') return dictResults.value
  return dictResults.value.filter(t => t.category === selectedCategory.value)
})

const { list, containerProps, wrapperProps } = useVirtualList(filteredResults, { itemHeight: 52 })

function loadDictionary() {
  loadingDict.value = true
  getBridge().get_all_dictionary_terms(proofreadMode.value, (termsStr: string) => {
    loadingDict.value = false
    try { 
      const data = JSON.parse(termsStr)
      dictResults.value = Array.isArray(data) ? data : []
    } catch { 
      dictResults.value = []
    }
  })
}

function toggleProofreadMode() {
  proofreadMode.value = !proofreadMode.value
  loadDictionary()
}

let searchTimer: any = null
function searchDictionary() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    if (!dictQuery.value.trim()) { loadDictionary(); return }
    loadingDict.value = true
    getBridge().search_dictionary(dictQuery.value.trim(), proofreadMode.value, (resStr: string) => {
      loadingDict.value = false
      try { dictResults.value = JSON.parse(resStr) } catch (e) { }
    })
  }, 300)
}

function saveTerm() {
  const en = newTermEn.value.trim()
  const zh = newTermZh.value.trim()
  if (!en) return
  getBridge().save_dictionary_term(en, zh, newTermCat.value, (ok: boolean) => {
    if (ok) { 
      appStore.showNotification(`词条 "${en}" 已保存`, 'success')
      newTermEn.value = ''; newTermZh.value = ''; loadDictionary()
    }
  })
}

function verifyTerm(english: string) {
  getBridge().verify_dictionary_term(english, (ok: boolean) => { 
    if (ok) {
      // 局部更新状态而不重刷全表，提升体验
      const idx = dictResults.value.findIndex(t => t.english === english)
      if (idx !== -1) {
        dictResults.value[idx].source = (dictResults.value[idx].source || '') + ',verified'
      }
    }
  })
}

function editTerm(item: any) {
  newTermEn.value = item.english
  newTermZh.value = item.chinese
  newTermCat.value = item.category
  appStore.showNotification(`正在编辑: ${item.english}`, 'info')
}

function deleteTerm(english: string) {
  if (!confirm(`确认彻底删除 "${english}"?`)) return
  getBridge().delete_dictionary_term(english, (ok: boolean) => { if (ok) loadDictionary() })
}

/** 导出逻辑完善 */
function exportDictionaryCSV() {
  const terms = filteredResults.value
  if (terms.length === 0) return
  
  let csvContent = "\ufeffEnglish,Chinese,Category,Source\n"
  terms.forEach((t: any) => { 
    csvContent += `"${t.english}","${t.chinese}","${t.category}","${t.source || ''}"\n` 
  })
  
  const filename = `BioDict_${selectedCategory.value}_${new Date().toISOString().slice(0,10)}.csv`
  getBridge().save_file(csvContent, filename, (ok: boolean) => { 
    if (ok) appStore.showNotification('导出成功', 'success') 
  })
}



/** NCBI 分类学批量审计优化 */
function handleTaxonomyAudit() {
  const terms = filteredResults.value.filter(t => t.english).map(t => t.english)
  if (terms.length === 0) return
  if (!confirm(`将对当前显示区域的 ${terms.length} 条记录执行 NCBI 在线校核，这可能需要一些时间。`)) return
  
  isAuditing.value = true
  getBridge().taxonomy_audit_batch(terms, (res: any) => {
    if (res && res.success && res.results) {
      const results = res.results
      let count = 0
      const total = results.length
      
      const processResults = async () => {
        for (const item of results) {
          if (item.valid && item.rank) {
             // 仅当本地没有或不一致时更新，并直接标记为已验证
             await new Promise(resolve => {
               getBridge().save_dictionary_term(item.name, '', item.rank, () => {
                 getBridge().verify_dictionary_term(item.name, () => {
                   count++
                   resolve(null)
                 })
               })
             })
          } else {
             count++
          }
        }
        isAuditing.value = false
        appStore.showNotification(`NCBI 审计完成，更新了 ${count} 条记录`, 'success')
        loadDictionary()
      }
      processResults()
    } else { 
      isAuditing.value = false 
      appStore.showNotification('校核失败：服务器未响应或网络不通', 'error')
    }
  })
}

let eventCleanup: (() => void) | null = null

onMounted(() => {
  loadDictionary()
  // 监听后台推送的消息（如异步翻译结果）
  eventCleanup = onEvent((type, data) => {
    if (type === 'data_updated') {
      loadDictionary()
    }
  })
})

onUnmounted(() => {
  if (eventCleanup) eventCleanup()
})
</script>

<template>
  <div class="panel">
    <header class="panel-header">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; width: 100%;">
        <div>
          <h2>📖 词典 & 术语中心</h2>
          <p class="desc">管理多语言对照词库，支持物种分类等级自动补全与 NCBI 分类学在线校核。</p>
        </div>
        <div class="stats-badges">
           <span class="p-badge" style="background: #eff6ff; color: #3b82f6;">总计: {{ dictResults.length }}</span>
           <span class="p-badge" v-if="dictResults.some(t => !t.source?.includes('verified'))" style="background: #fff7ed; color: #f97316;">
             待核: {{ dictResults.filter(t => !t.source?.includes('verified')).length }}
           </span>
        </div>
      </div>
    </header>

    <div class="p-card no-p">
       <!-- 快速添加区（已移动到顶部） -->
       <div class="add-term-box">
         <div class="add-box-header">⚡ 快速录入/编辑</div>
         <div class="add-box-fields">
           <input v-model="newTermEn" class="p-input" placeholder="原词 (English)" />
           <input v-model="newTermZh" class="p-input" placeholder="翻译 (Chinese)" />
           <select v-model="newTermCat" class="p-input" style="width: 160px">
             <option v-for="c in dictCategories.slice(1)" :key="c.id" :value="c.id">{{ c.label }}</option>
           </select>
           <button class="p-btn p-btn-primary" @click="saveTerm" style="min-width: 100px">💾 保存</button>
         </div>
       </div>

       <!-- 搜索与工具栏 -->
       <div class="toolbar">
         <div class="search-actions">
            <input v-model="dictQuery" class="p-input search-input" placeholder="搜索原词、翻译或分类..." @input="searchDictionary" />
            
            <select v-model="selectedCategory" class="p-input category-select">
              <option v-for="c in dictCategories" :key="c.id" :value="c.id">{{ c.label }}</option>
            </select>

            <button 
              class="p-btn p-btn-outline" 
              :class="{ 'btn-active-proof': proofreadMode }"
              @click="toggleProofreadMode"
            >
              {{ proofreadMode ? '🔍 全部数据' : '🧐 只看待校对' }}
            </button>
         </div>

         <div class="global-actions">
           <button class="p-btn p-btn-outline" @click="handleTaxonomyAudit" :disabled="isAuditing">
             {{ isAuditing ? '🧬 校核中...' : '🧬 NCBI 校核' }}
           </button>

           <button class="p-btn p-btn-outline" @click="exportDictionaryCSV">📤 导出</button>
         </div>
       </div>

       <!-- 虚拟滚动表格 -->
       <div class="dict-table-header">
         <div class="col-en">英文原词 (English)</div>
         <div class="col-zh">中文翻译 (Translation)</div>
         <div class="col-cat">分类等级</div>
         <div class="col-act">操作</div>
       </div>

       <div v-bind="containerProps" class="dict-scroll-area">
          <div v-if="loadingDict" class="loading-overlay">
            <div class="spinner"></div>
            <span>正在检索词库...</span>
          </div>
          
          <div v-if="filteredResults.length === 0 && !loadingDict" class="empty-placeholder">
             📭 没有找到相关词条
          </div>

         <div v-bind="wrapperProps">
           <div v-for="item in list" :key="item.index" class="p-table-row dict-row" :class="{ 'row-verified': item.data.source?.includes('verified') }">
             <div class="col-en">
               <span class="en-text">{{ item.data.english }}</span>
               <span v-if="!item.data.source?.includes('verified')" class="unverified-tag">待核</span>
             </div>
             <div class="col-zh">
               <span v-if="item.data.chinese" class="zh-text">{{ item.data.chinese }}</span>
               <span v-else class="missing-text">等待翻译...</span>
             </div>
             <div class="col-cat">
               <span class="p-badge cat-badge" :class="'cat-' + item.data.category">{{ item.data.category }}</span>
             </div>
             <div class="col-act">
               <button v-if="!item.data.source?.includes('verified')" class="btn-tool" @click="verifyTerm(item.data.english)" title="验证并标记">✅</button>
               <button class="btn-tool" @click="editTerm(item.data)" title="编辑词条">✏️</button>
               <button class="btn-tool del" @click="deleteTerm(item.data.english)" title="彻底删除">🗑️</button>
             </div>
           </div>
         </div>
       </div>
    </div>
  </div>
</template>

<style scoped>
.no-p { padding: 0 !important; overflow: hidden; display: flex; flex-direction: column; }
.stats-badges { display: flex; gap: 8px; }

.toolbar { 
  padding: 16px 20px; 
  display: flex; 
  flex-direction: column;
  gap: 12px; 
  border-bottom: 1px solid #f1f5f9;
  background: #fff;
}

.search-actions, .global-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.search-input { flex: 1; min-width: 200px; }
.category-select { width: 140px; }

.dict-table-header {
  display: grid;
  grid-template-columns: 1.5fr 1fr 140px 100px;
  padding: 12px 20px;
  background: #f8fafc;
  font-size: 0.75rem;
  font-weight: 800;
  color: #64748b;
  border-bottom: 1px solid #e2e8f0;
}

.dict-scroll-area { 
  height: 520px; 
  overflow-y: auto; 
  position: relative;
}

.dict-row { 
  grid-template-columns: 1.5fr 1fr 140px 100px; 
  padding: 0 20px; 
  height: 52px;
  transition: all 0.2s;
}
.dict-row:hover { background: #f8fafc; }
.row-verified { opacity: 0.85; }

.en-text { font-family: 'Inter', system-ui, sans-serif; font-weight: 600; color: #1e293b; }
.zh-text { color: #334155; }
.missing-text { color: #94a3b8; font-style: italic; font-size: 0.85rem; }

.cat-badge { font-size: 0.7rem; border-radius: 6px; padding: 2px 8px; }
.cat-species { background: #ecfdf5; color: #059669; }
.cat-gene { background: #eff6ff; color: #2563eb; }
.cat-other { background: #f1f5f9; color: #475569; }

.col-act { display: flex; gap: 6px; justify-content: flex-end; }

.btn-tool {
  background: white; border: 1px solid #e2e8f0; cursor: pointer; padding: 4px 6px; border-radius: 6px;
  transition: all 0.2s; font-size: 0.9rem;
}
.btn-tool:hover { background: #f8fafc; border-color: #cbd5e1; transform: translateY(-1px); box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.btn-tool.del:hover { color: #ef4444; border-color: #fecaca; }

.btn-active-proof {
  background: #fff7ed !important;
  border-color: #f97316 !important;
  color: #f97316 !important;
  font-weight: 800;
}

.unverified-tag {
  font-size: 0.65rem;
  background: #fff7ed;
  color: #f97316;
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 8px;
  border: 1px solid #ffedd5;
  font-weight: 800;
}

.add-term-box {
  padding: 16px 20px;
  background: #f8fafc;
  border-bottom: 2px solid #e2e8f0;
}
.add-box-header { font-size: 0.75rem; font-weight: 800; color: #64748b; margin-bottom: 8px; text-transform: uppercase; }
.add-box-fields { display: flex; gap: 12px; }

.loading-overlay {
  position: absolute; inset: 0; background: rgba(255,255,255,0.7);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; z-index: 10; color: #64748b; font-size: 0.9rem;
}
.empty-placeholder { padding: 40px; text-align: center; color: #94a3b8; font-style: italic; }

.spinner {
  width: 24px; height: 24px; border: 3px solid #e2e8f0; border-top-color: #3b82f6;
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
