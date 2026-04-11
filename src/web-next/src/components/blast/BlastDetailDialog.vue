<script setup lang="ts">

const props = defineProps<{
  show: boolean
  title: string
  data: any[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

</script>

<template>
  <Transition name="dialog-fade">
    <div v-if="show" class="dialog-overlay" @click.self="emit('close')">
      <div class="dialog-container">
        <div class="dialog-header">
          <h3>📋 {{ title }} - 全部比对结果 ({{ data.length }} 条)</h3>
          <button class="close-btn" @click="emit('close')">✕</button>
        </div>
        <div class="dialog-body scroll-v">
          <table v-if="data.length > 0" class="detail-table">
            <thead>
              <tr>
                <th>#</th>
                <th>物种名称</th>
                <th>相似度</th>
                <th>E值</th>
                <th>Accession</th>
                <th>标题</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(hit, index) in data" :key="index" v-memo="[hit.acc, hit.similarity]">
                <td>{{ index + 1 }}</td>
                <td>{{ hit.species || '-' }}</td>
                <td>
                  <span :class="parseFloat(hit.similarity) >= 98 ? 'high-id' : 'low-id'">
                    {{ hit.similarity }}
                  </span>
                </td>
                <td class="mono">{{ hit.evalue }}</td>
                <td class="mono">{{ hit.acc || '-' }}</td>
                <td class="title-cell">{{ hit.title || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="loading-skeleton-container">
            <div v-for="i in 10" :key="i" class="skeleton-row"></div>
            <p class="loading-text">正在精准解析...</p>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-primary" @click="emit('close')">确认</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 2000; }
.dialog-container { background: white; border-radius: 12px; width: 900px; max-width: 95vw; max-height: 85vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1); }
.dialog-header { padding: 16px 24px; border-bottom: 1px solid #e2e8f0; display: flex; align-items: center; justify-content: space-between; }
.dialog-header h3 { font-size: 1rem; font-weight: 700; color: #1e293b; }
.dialog-body { flex: 1; padding: 0; overflow: auto; }
.dialog-footer { padding: 12px 24px; border-top: 1px solid #e2e8f0; display: flex; justify-content: flex-end; }

.detail-table { width: 100%; border-collapse: collapse; }
th { background: #f8fafc; padding: 12px 16px; font-size: 0.75rem; color: #64748b; text-align: left; position: sticky; top: 0; z-index: 5; }
td { padding: 12px 16px; border-bottom: 1px solid #f1f5f9; font-size: 0.82rem; }
.title-cell { color: #64748b; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.btn-primary { background: #2563eb; color: white; border: none; padding: 8px 24px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.close-btn { background: none; border: none; font-size: 1.2rem; cursor: pointer; color: #94a3b8; }

.mono { font-family: 'JetBrains Mono', monospace; }
.high-id { color: #059669; font-weight: 700; }
.low-id { color: #ea580c; }

.loading-skeleton-container { padding: 20px; }
.skeleton-row { height: 12px; background: #f1f5f9; margin-bottom: 12px; border-radius: 4px; }
.loading-text { text-align: center; color: #94a3b8; font-size: 0.8rem; margin-top: 20px; }

.dialog-fade-enter-active, .dialog-fade-leave-active { transition: opacity 0.3s ease; }
.dialog-fade-enter-from, .dialog-fade-leave-to { opacity: 0; }
</style>
