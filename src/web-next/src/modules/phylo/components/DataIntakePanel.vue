<script setup lang="ts">
import { ref } from 'vue'
import UniversalUpload from '../../../components/common/UniversalUpload.vue'
import { usePhyloStore } from '../stores/usePhyloStore'

const store = usePhyloStore()
const showPasteBox = ref(false)
const pasteName = ref('pasted_sequences.fasta')
const pasteContent = ref('')

async function onUploadPaths(paths: string[]) {
  await store.importFiles(paths)
}

async function submitPaste() {
  if (!pasteContent.value.trim()) return
  await store.pasteSequences(pasteContent.value, pasteName.value)
  pasteContent.value = ''
  showPasteBox.value = false
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}
</script>

<template>
  <div class="phylo-panel">
    <div class="panel-header">
      <h3 class="panel-title">数据采集与序列画像</h3>
      <button type="button" class="btn-link" @click="showPasteBox = !showPasteBox">
        {{ showPasteBox ? '关闭文本导入' : '粘贴 FASTA' }}
      </button>
    </div>

    <UniversalUpload
      type="tree"
      accept=".fasta,.fas,.fa,.fna,.seq,.txt,.zip,.gz,.ab1,.abi,.nwk"
      label="拖拽或点击导入 FASTA / ZIP / NWK"
      @success="onUploadPaths"
    />

    <div v-if="showPasteBox" class="paste-box">
      <input v-model="pasteName" class="neo-input" placeholder="文件名 (如 sample.fasta)" />
      <textarea
        v-model="pasteContent"
        class="neo-textarea"
        rows="5"
        placeholder=">Seq1&#10;ATGCGTACGT..."
      ></textarea>
      <div class="paste-actions">
        <button type="button" class="btn-primary-sm" :disabled="store.isImporting" @click="submitPaste">保存至工作区</button>
      </div>
    </div>

    <div class="sub-header">
      <span>工作区文件 ({{ store.workspaceFiles.length }})</span>
      <div class="sub-actions">
        <button type="button" class="btn-link" @click="store.refreshWorkspace()">刷新</button>
        <button
          type="button"
          v-if="store.workspaceFiles.length > 0"
          class="btn-link danger"
          @click="store.clearWorkspace()"
        >清空</button>
      </div>
    </div>

    <div class="file-list">
      <div v-if="store.workspaceFiles.length === 0" class="empty-hint">
        暂无序列文件，请先导入序列
      </div>
      <div v-for="file in store.workspaceFiles" :key="file.name" class="file-item">
        <span class="file-ext">{{ file.ext.replace('.', '').toUpperCase() }}</span>
        <span class="file-name" :title="file.name">{{ file.name }}</span>
        <span class="file-size">{{ formatSize(file.size) }}</span>
        <button type="button" class="btn-icon-del" title="移除" @click="store.removeWorkspaceFile(file.name)">x</button>
      </div>
    </div>

    <!-- 序列多维画像卡片 -->
    <div v-if="store.profile && store.profile.sequence_count > 0" class="profile-card">
      <div class="profile-head">
        <span class="profile-badge" :class="store.profile.recommended_track">
          推荐: {{ store.profile.recommended_track === 'genome' ? '全基因组无对齐 (Mash)' : '经典比对构树' }}
        </span>
        <span class="mol-tag">{{ store.profile.mol_type.toUpperCase() }}</span>
      </div>

      <div class="profile-grid">
        <div class="metric">
          <div class="m-label">序列条数</div>
          <div class="m-val">{{ store.profile.sequence_count }}</div>
        </div>
        <div class="metric">
          <div class="m-label">长度范围</div>
          <div class="m-val">{{ store.profile.min_length.toLocaleString() }} - {{ store.profile.max_length.toLocaleString() }}</div>
        </div>
        <div class="metric">
          <div class="m-label">总碱基/残基</div>
          <div class="m-val">{{ store.profile.total_bases.toLocaleString() }}</div>
        </div>
        <div class="metric">
          <div class="m-label">对齐状态</div>
          <div class="m-val">{{ store.profile.is_aligned ? '已等长对齐' : '未对齐' }}</div>
        </div>
      </div>

      <div v-if="store.profile.warnings.length > 0" class="warn-list">
        <div v-for="(w, idx) in store.profile.warnings" :key="idx" class="warn-item">{{ w }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.phylo-panel { display: flex; flex-direction: column; gap: 12px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0; }
.sub-header { display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 600; color: #475569; margin-top: 4px; }
.sub-actions { display: flex; gap: 10px; }
.btn-link { background: none; border: none; color: #2563eb; font-size: 12px; cursor: pointer; padding: 0; font-weight: 600; }
.btn-link.danger { color: #dc2626; }
.paste-box { display: flex; flex-direction: column; gap: 8px; background: #f8fafc; padding: 10px; border-radius: 8px; border: 1px solid #e2e8f0; }
.neo-input, .neo-textarea { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 12px; font-family: monospace; box-sizing: border-box; }
.paste-actions { display: flex; justify-content: flex-end; }
.btn-primary-sm { background: #2563eb; color: #fff; border: none; border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; }
.file-list { max-height: 150px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.empty-hint { font-size: 12px; color: #94a3b8; text-align: center; padding: 16px 0; background: #f8fafc; border-radius: 8px; }
.file-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; }
.file-ext { font-size: 10px; font-weight: 700; color: #1d4ed8; background: #dbeafe; padding: 2px 5px; border-radius: 4px; }
.file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #1e293b; }
.file-size { color: #64748b; font-size: 11px; }
.btn-icon-del { background: none; border: none; color: #94a3b8; cursor: pointer; font-weight: 700; padding: 0 4px; }
.btn-icon-del:hover { color: #dc2626; }
.profile-card { background: #f8fafc; border: 1px solid #dbeafe; border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 10px; }
.profile-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.profile-badge { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 999px; }
.profile-badge.genome { background: #dcfce7; color: #166534; }
.profile-badge.gene { background: #dbeafe; color: #1e40af; }
.mol-tag { font-size: 11px; font-weight: 700; color: #475569; background: #e2e8f0; padding: 2px 7px; border-radius: 4px; }
.profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.metric { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px 8px; }
.m-label { font-size: 10px; color: #64748b; }
.m-val { font-size: 12px; font-weight: 700; color: #0f172a; margin-top: 2px; }
.warn-list { display: flex; flex-direction: column; gap: 4px; }
.warn-item { font-size: 11px; color: #92400e; background: #fef3c7; border: 1px solid #fde68a; border-radius: 6px; padding: 6px 8px; line-height: 1.4; }
</style>
