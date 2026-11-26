<script setup lang="ts">
import type { DiversitySampleItem } from './useDiversityModal'

defineProps<{
  detailSearchQuery: string
  detailViewMode: 'cards' | 'table'
  isGroupView: boolean
  abundanceMode: 'norm' | 'raw'
  activeSampleCount: number
  filteredActiveSamples: DiversitySampleItem[]
  isSampleCollapsed: (sampleName: string) => boolean
  getDominantTaxon: (s: DiversitySampleItem) => { taxon: string; pct: number } | null
  getTaxonColor: (taxon: string) => string
  getTaxonZh: (taxon: string) => string
  isNoiseTaxon: (taxon: string) => boolean
  formatPct: (val: number | string | null | undefined) => string
}>()

const emit = defineEmits<{
  (e: 'update:detailSearchQuery', value: string): void
  (e: 'update:detailViewMode', value: 'cards' | 'table'): void
  (e: 'toggleSampleCollapse', sampleName: string): void
  (e: 'expandAllSamples'): void
  (e: 'collapseAllSamples'): void
}>()
</script>

<template>
  <div class="tab-content-neo scroll-y">
    <div class="matrix-toolbar-card">
      <div class="matrix-toolbar-left">
        <div class="matrix-search-box">
          <svg class="search-svg" viewBox="0 0 20 20" fill="currentColor">
            <path
              fill-rule="evenodd"
              d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z"
              clip-rule="evenodd"
            />
          </svg>
          <input
            type="text"
            :value="detailSearchQuery"
            class="matrix-search-input"
            placeholder="快速定位点位 (如 -1)、分组名或特定菌种 (如 Vibrio)..."
            @input="emit('update:detailSearchQuery', ($event.target as HTMLInputElement).value)"
          />
          <button
            v-if="detailSearchQuery"
            type="button"
            class="clear-search-btn"
            @click="emit('update:detailSearchQuery', '')"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div class="matrix-stat-hint">
          <span>
            展示 <strong>{{ filteredActiveSamples.length }}</strong> / {{ activeSampleCount }} 个{{ isGroupView ? '样本组' : '采样点位' }}
          </span>
          <span class="hint-sep">·</span>
          <span class="hint-desc">
            {{ abundanceMode === 'norm' ? '当前指标: rrnDB 拷贝数校正后细胞相对丰度' : '当前指标: 原始测序 Reads 物理占比' }}
          </span>
        </div>
      </div>

      <div class="matrix-toolbar-right">
        <div v-if="detailViewMode === 'cards'" class="card-expand-actions">
          <button type="button" class="btn-ghost-action" @click="emit('expandAllSamples')" title="展开所有样本卡片">
            全部展开
          </button>
          <button type="button" class="btn-ghost-action" @click="emit('collapseAllSamples')" title="折叠所有样本卡片">
            全部折叠
          </button>
        </div>

        <div class="detail-mode-segmented">
          <button
            type="button"
            class="segment-btn"
            :class="{ active: detailViewMode === 'cards' }"
            @click="emit('update:detailViewMode', 'cards')"
            title="卡片分组视图：每个点位独立卡片容器，彻底防止串行看混（推荐）"
          >
            <svg class="segment-svg" viewBox="0 0 20 20" fill="currentColor">
              <path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" />
            </svg>
            <span>分组卡片 (推荐防混)</span>
          </button>
          <button
            type="button"
            class="segment-btn"
            :class="{ active: detailViewMode === 'table' }"
            @click="emit('update:detailViewMode', 'table')"
            title="连续大表视图：保留紧凑跨点位通览对比"
          >
            <svg class="segment-svg" viewBox="0 0 20 20" fill="currentColor">
              <path
                fill-rule="evenodd"
                d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"
                clip-rule="evenodd"
              />
            </svg>
            <span>紧凑大表</span>
          </button>
        </div>
      </div>
    </div>

    <div v-if="detailViewMode === 'cards'" class="sample-cards-list">
      <div
        v-for="s in filteredActiveSamples"
        :key="s.sample_name"
        class="sample-card-item"
        :class="{ 'is-collapsed': isSampleCollapsed(s.sample_name) }"
      >
        <div class="sample-card-header" @click="emit('toggleSampleCollapse', s.sample_name)">
          <div class="header-sample-identity">
            <div class="sample-badge-primary" :class="{ 'is-group': s.is_group }">
              <span class="badge-role">{{ s.is_group ? '合并组' : '采样点位' }}</span>
              <span class="badge-name mono">{{ s.sample_name }}</span>
            </div>
            <div v-if="s.is_group && s.member_samples" class="group-members-pill">
              <span class="pill-title">聚合点位 ({{ s.member_samples.length }}个):</span>
              <span v-for="m in s.member_samples.slice(0, 6)" :key="m" class="pill-chip">{{ m }}</span>
              <span v-if="s.member_samples.length > 6" class="pill-chip-more">...等 {{ s.member_samples.length }} 点</span>
            </div>
          </div>

          <div class="header-meta-chips">
            <div class="meta-chip chip-reads">
              <span class="chip-k">有效 Reads:</span>
              <span class="chip-v mono">{{ (s.total_reads || 0).toLocaleString() }}</span>
            </div>
            <div class="meta-chip chip-taxa">
              <span class="chip-k">检出物种:</span>
              <span class="chip-v">{{ s.norm_result?.details?.length || 0 }} 种</span>
            </div>
            <div class="meta-chip chip-dominant" v-if="getDominantTaxon(s)">
              <span class="chip-k">主导优势菌:</span>
              <span class="dominant-dot" :style="{ background: getTaxonColor(getDominantTaxon(s)!.taxon) }"></span>
              <span class="chip-v italic">{{ getDominantTaxon(s)!.taxon }}</span>
              <span v-if="getTaxonZh(getDominantTaxon(s)!.taxon)" class="chip-zh-sub font-bold">
                ({{ getTaxonZh(getDominantTaxon(s)!.taxon) }})
              </span>
              <span class="chip-pct">({{ formatPct(getDominantTaxon(s)!.pct) }}%)</span>
            </div>
          </div>

          <div class="collapse-toggle-btn">
            <span class="toggle-txt">{{ isSampleCollapsed(s.sample_name) ? '展开明细' : '收起' }}</span>
            <svg
              class="chevron-svg"
              :class="{ rotated: isSampleCollapsed(s.sample_name) }"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fill-rule="evenodd"
                d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                clip-rule="evenodd"
              />
            </svg>
          </div>
        </div>

        <div v-show="!isSampleCollapsed(s.sample_name)" class="sample-card-body">
          <table class="card-detail-table">
            <thead>
              <tr>
                <th style="width: 34%">检出物种名称</th>
                <th style="width: 13%">Reads 计数</th>
                <th style="width: 13%">原始占比 (%)</th>
                <th style="width: 15%">16S 拷贝数 (GCN)</th>
                <th style="width: 25%">rrnDB 校正后占比 (%)</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(d, idx) in s.norm_result?.details || []"
                :key="d.taxon"
                :class="{
                  'row-noise': isNoiseTaxon(d.taxon),
                  'row-dominant': idx === 0 && !isNoiseTaxon(d.taxon) && d.norm_pct >= 30,
                }"
              >
                <td>
                  <div class="taxa-cell-flex">
                    <span
                      class="taxa-color-dot"
                      :style="{ background: isNoiseTaxon(d.taxon) ? '#cbd5e1' : getTaxonColor(d.taxon) }"
                    ></span>
                    <span
                      class="taxa-name-txt"
                      :class="{ 'taxa-latin': !isNoiseTaxon(d.taxon), 'taxa-noise-txt': isNoiseTaxon(d.taxon) }"
                    >
                      {{ d.taxon }}
                    </span>
                    <span v-if="getTaxonZh(d.taxon)" class="taxa-zh-badge">{{ getTaxonZh(d.taxon) }}</span>
                    <span
                      v-if="idx === 0 && !isNoiseTaxon(d.taxon) && d.norm_pct >= 30"
                      class="tag-dominant-star"
                      title="该样本中丰度第一的主要优势菌群"
                    >
                      主要优势
                    </span>
                    <span
                      v-else-if="isNoiseTaxon(d.taxon)"
                      class="tag-noise-badge"
                      title="丰度低于 1% 的极低频 Reads 过滤合并，排除测序假阳性"
                    >
                      噪声过滤合集
                    </span>
                  </div>
                </td>
                <td class="mono font-semibold">{{ (d.raw_count || 0).toLocaleString() }}</td>
                <td class="mono text-muted">{{ formatPct(d.raw_pct) }}%</td>
                <td>
                  <div class="gcn-cell-wrap">
                    <span class="gcn-num mono"><strong>{{ d.gcn_mean }}</strong></span>
                    <span class="badge-match-mini" :class="d.gcn_matched ? 'match-ok' : 'match-fallback'">
                      {{ d.gcn_rank === 'species' ? '种级匹配' : d.gcn_rank === 'genus' ? '属级回退' : '默认基准' }}
                    </span>
                  </div>
                </td>
                <td>
                  <div class="norm-bar-cell">
                    <div class="mini-bar-track">
                      <div
                        class="mini-bar-fill"
                        :style="{
                          width: `${Math.min(100, Math.max(Number(d.norm_pct || 0), 1.5))}%`,
                          background: isNoiseTaxon(d.taxon) ? '#94a3b8' : getTaxonColor(d.taxon),
                        }"
                      ></div>
                    </div>
                    <span class="norm-pct-val mono">{{ formatPct(d.norm_pct) }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="filteredActiveSamples.length === 0" class="empty-search-card">
        <p>未找到匹配 "{{ detailSearchQuery }}" 的采样点位或物种</p>
        <button type="button" class="btn-clear-filter" @click="emit('update:detailSearchQuery', '')">
          清除搜索条件
        </button>
      </div>
    </div>

    <div v-else class="matrix-card">
      <table class="neo-data-table enhanced-matrix-table">
        <thead>
          <tr>
            <th style="width: 220px">样本 / 合并组</th>
            <th>检出物种名称</th>
            <th>Reads 计数</th>
            <th>原始占比 (%)</th>
            <th>16S 拷贝数 (GCN)</th>
            <th>匹配级别</th>
            <th>rrnDB 校正后占比 (%)</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="s in filteredActiveSamples" :key="s.sample_name">
            <tr
              v-for="(d, idx) in s.norm_result?.details || []"
              :key="d.taxon"
              :class="{
                'sample-start-row': idx === 0,
                'row-noise': isNoiseTaxon(d.taxon),
                'row-dominant-subtle': idx === 0 && !isNoiseTaxon(d.taxon) && d.norm_pct >= 30,
              }"
            >
              <td v-if="idx === 0" :rowspan="s.norm_result?.details?.length || 1" class="align-top sample-grouped-col">
                <div class="sample-info-block-neo">
                  <div class="sample-title-badge" :class="{ 'is-group': s.is_group }">
                    <span class="title-text mono">{{ s.sample_name }}</span>
                    <span v-if="s.is_group" class="group-flag">合并组</span>
                  </div>
                  <div v-if="s.is_group && s.member_samples" class="member-samples-preview">
                    <span class="preview-label">包含点位 ({{ s.member_samples.length }}个):</span>
                    <div class="member-chips-inline">
                      <span v-for="m in s.member_samples.slice(0, 6)" :key="m" class="sub-chip">{{ m }}</span>
                      <span v-if="s.member_samples.length > 6" class="sub-chip-more">+{{ s.member_samples.length - 6 }}</span>
                    </div>
                  </div>
                  <div class="sample-meta-stat">
                    <span class="stat-reads">总 Reads: <strong>{{ (s.total_reads || 0).toLocaleString() }}</strong></span>
                    <span class="stat-taxa">检出物种: {{ s.norm_result?.details?.length || 0 }} 种</span>
                  </div>
                </div>
              </td>

              <td>
                <div class="taxa-cell-flex">
                  <span
                    class="taxa-color-dot"
                    :style="{ background: isNoiseTaxon(d.taxon) ? '#cbd5e1' : getTaxonColor(d.taxon) }"
                  ></span>
                  <span
                    class="taxa-name-txt"
                    :class="{ 'taxa-latin': !isNoiseTaxon(d.taxon), 'taxa-noise-txt': isNoiseTaxon(d.taxon) }"
                  >
                    {{ d.taxon }}
                  </span>
                  <span v-if="getTaxonZh(d.taxon)" class="taxa-zh-badge">{{ getTaxonZh(d.taxon) }}</span>
                  <span v-if="idx === 0 && !isNoiseTaxon(d.taxon) && d.norm_pct >= 30" class="tag-dominant-star">
                    优势
                  </span>
                  <span v-else-if="isNoiseTaxon(d.taxon)" class="tag-noise-badge">噪声</span>
                </div>
              </td>
              <td class="mono font-semibold">{{ (d.raw_count || 0).toLocaleString() }}</td>
              <td class="mono text-muted">{{ formatPct(d.raw_pct) }}%</td>
              <td><strong>{{ d.gcn_mean }}</strong></td>
              <td>
                <span class="badge-match" :class="d.gcn_matched ? 'match-ok' : 'match-fallback'">
                  {{ d.gcn_rank === 'species' ? '种级' : d.gcn_rank === 'genus' ? '属级' : '基准' }}
                </span>
              </td>
              <td>
                <div class="norm-bar-cell">
                  <div class="mini-bar-track">
                    <div
                      class="mini-bar-fill"
                      :style="{
                        width: `${Math.min(100, Math.max(Number(d.norm_pct || 0), 1.5))}%`,
                        background: isNoiseTaxon(d.taxon) ? '#94a3b8' : getTaxonColor(d.taxon),
                      }"
                    ></div>
                  </div>
                  <span class="norm-pct-val mono font-bold">{{ formatPct(d.norm_pct) }}%</span>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped src="./styles/matrix.css"></style>
