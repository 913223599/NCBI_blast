<script setup lang="ts">
import type { SampleGroupDef } from './diversityHelpers'

defineProps<{
  visible: boolean
  groupChunkSize: number
  allSampleNames: string[]
  sampleGroups: SampleGroupDef[]
  unassignedSamples: string[]
  parseSamplePattern: (pattern: string, samples: string[]) => string[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply'): void
  (e: 'update:groupChunkSize', value: number): void
  (e: 'generateConsecutiveGroups', size: number): void
  (e: 'setChunkSizeAndGenerate', size: number): void
  (e: 'addGroup'): void
  (e: 'removeGroup', id: string): void
  (e: 'clearAllGroups'): void
}>()
</script>

<template>
  <transition name="drawer-fade">
    <div v-if="visible" class="group-modal-backdrop" @click.self="emit('close')">
      <div class="group-modal-card">
        <div class="group-modal-header">
          <div class="header-title-wrap">
            <svg class="header-icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" />
            </svg>
            <div>
              <h3 class="modal-h3">样本点位合并与分组规则</h3>
              <p class="modal-sub">
                将多个随机采样点位合并为一个样本组进行分析，Reads 自动累加并重新执行 rrnDB 归一化校正
              </p>
            </div>
          </div>
          <button type="button" class="btn-modal-close" @click="emit('close')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div class="group-modal-body scroll-y">
          <div class="group-config-control-panel">
            <div class="chunk-generator-section">
              <div class="generator-header">
                <span class="section-title">连续分组模式 (连续 X 个一组)</span>
                <span class="section-desc">根据采样编号顺序，按设定跨度自动将所有点位切分为连续的分组</span>
              </div>
              <div class="generator-toolbar">
                <div class="chunk-input-wrap">
                  <span class="chunk-label">每连续</span>
                  <input
                    type="number"
                    :value="groupChunkSize"
                    min="1"
                    :max="Math.max(1, allSampleNames.length)"
                    class="chunk-num-input"
                    @input="emit('update:groupChunkSize', Number(($event.target as HTMLInputElement).value))"
                  />
                  <span class="chunk-unit">个点位为一组</span>
                </div>
                <button
                  type="button"
                  class="btn-gen-chunk"
                  @click="emit('generateConsecutiveGroups', groupChunkSize)"
                >
                  自动生成分组
                </button>
                <div class="quick-preset-chips">
                  <button
                    v-for="s in [2, 3, 4, 5, 8]"
                    :key="s"
                    type="button"
                    class="btn-preset-chip"
                    :class="{ active: groupChunkSize === s }"
                    @click="emit('setChunkSizeAndGenerate', s)"
                  >
                    {{ s }}个一组
                  </button>
                </div>
              </div>
            </div>

            <div class="manual-group-section">
              <div class="manual-header">
                <span class="section-title">手动分组模式</span>
                <span class="section-desc">自由添加/删除分组，支持自定义输入任意点位范围（如 1-5、6-9、1,3,5）</span>
              </div>
              <div class="manual-toolbar">
                <button type="button" class="btn-sub-action primary" @click="emit('addGroup')">
                  + 新增自定义合并组
                </button>
                <button
                  v-if="sampleGroups.length > 0"
                  type="button"
                  class="btn-sub-action"
                  @click="emit('clearAllGroups')"
                >
                  清空所有规则
                </button>
              </div>
            </div>
          </div>

          <div class="group-rules-list">
            <div v-if="sampleGroups.length === 0" class="empty-rules-hint">
              当前暂无合并分组规则。您可以选择上方的连续分组模式一键生成，或点击“+ 新增自定义合并组”手动创建。
            </div>
            <div v-for="grp in sampleGroups" :key="grp.id" class="group-rule-card">
              <div class="rule-inputs-row">
                <div class="input-field-group">
                  <label class="field-label">组名称</label>
                  <input type="text" v-model="grp.name" placeholder="例如：对照组 (Control)" class="rule-input" />
                </div>
                <div class="input-field-group flex-2">
                  <label class="field-label">点位范围 / 匹配规则</label>
                  <input type="text" v-model="grp.pattern" placeholder="例如：1-5 或 1,2,3,4,5" class="rule-input" />
                </div>
                <button type="button" class="btn-del-group" @click="emit('removeGroup', grp.id)" title="删除此分组">
                  <svg viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fill-rule="evenodd"
                      d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </button>
              </div>

              <div class="match-preview-box">
                <span class="preview-title">
                  匹配结果:
                  <strong>{{ parseSamplePattern(grp.pattern, allSampleNames).length }}</strong> 个点位
                </span>
                <div class="match-chips-wrap">
                  <span
                    v-for="sName in parseSamplePattern(grp.pattern, allSampleNames)"
                    :key="sName"
                    class="preview-sample-chip"
                  >
                    {{ sName }}
                  </span>
                  <span
                    v-if="parseSamplePattern(grp.pattern, allSampleNames).length === 0"
                    class="empty-match-hint"
                  >
                    暂无匹配到的点位 (请检查输入规则)
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div class="unassigned-status-banner">
            <span class="label">未分组的独立点位 (共 {{ unassignedSamples.length }} 个):</span>
            <div class="unassigned-chips">
              <span v-for="s in unassignedSamples.slice(0, 15)" :key="s" class="unassigned-chip">{{ s }}</span>
              <span v-if="unassignedSamples.length > 15" class="unassigned-chip-more">
                ...等 {{ unassignedSamples.length }} 个
              </span>
            </div>
          </div>
        </div>

        <div class="group-modal-footer">
          <button type="button" class="btn-cancel" @click="emit('close')">关闭</button>
          <button type="button" class="btn-apply-group" @click="emit('apply')">
            应用规则并开启合并视图
          </button>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped src="./styles/group-modal.css"></style>
