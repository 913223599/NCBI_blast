<script setup lang="ts">
import type { DiversityTaxonOverviewItem } from './useDiversityModal'

defineProps<{
  taxaSearchQuery: string
  confirmedSpeciesCount: number
  filteredTaxaOverview: DiversityTaxonOverviewItem[]
  isNoiseTaxon: (taxon: string) => boolean
  getRealTaxonRank: (taxon: string) => number | string | null
  getTaxonColor: (taxon: string) => string
  getTaxonZh: (taxon: string) => string
}>()

const emit = defineEmits<{
  (e: 'update:taxaSearchQuery', value: string): void
  (e: 'exportExcel'): void
}>()
</script>

<template>
  <div class="tab-content-neo scroll-y">
    <div class="taxa-overview-card">
      <div class="taxa-toolbar">
        <div class="taxa-search-box">
          <svg class="search-svg" viewBox="0 0 20 20" fill="currentColor">
            <path
              fill-rule="evenodd"
              d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z"
              clip-rule="evenodd"
            />
          </svg>
          <input
            type="text"
            :value="taxaSearchQuery"
            placeholder="搜索检出菌种或属名 (如 Pseudomonas、Bacillus...)"
            class="taxa-search-input"
            @input="emit('update:taxaSearchQuery', ($event.target as HTMLInputElement).value)"
          />
          <button
            v-if="taxaSearchQuery"
            type="button"
            class="clear-search-btn"
            @click="emit('update:taxaSearchQuery', '')"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div class="taxa-toolbar-right">
          <span class="taxa-count-tag">
            共计确证 <strong>{{ confirmedSpeciesCount }}</strong> 种有效微生物
            <span v-if="taxaSearchQuery"> (检索匹配 {{ filteredTaxaOverview.length }} 项)</span>
          </span>
          <button type="button" class="btn-export-excel" @click="emit('exportExcel')">
            <svg viewBox="0 0 20 20" fill="currentColor">
              <path
                fill-rule="evenodd"
                d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"
                clip-rule="evenodd"
              />
            </svg>
            <span>导出 Excel 报表</span>
          </button>
        </div>
      </div>

      <table class="neo-data-table taxa-table">
        <thead>
          <tr>
            <th style="width: 60px">排名</th>
            <th>物种拉丁学名 (Taxon)</th>
            <th style="width: 130px">16S 拷贝数 (GCN)</th>
            <th style="width: 120px">总检出 Reads</th>
            <th style="width: 240px">总体校正相对丰度</th>
            <th style="width: 120px">原始占比</th>
            <th style="width: 150px">点位检出覆盖率</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in filteredTaxaOverview"
            :key="item.taxon"
            class="taxa-row"
            :class="{ 'taxa-row-noise': isNoiseTaxon(item.taxon) }"
          >
            <td class="text-center font-bold">
              <span
                v-if="!isNoiseTaxon(item.taxon)"
                class="rank-badge"
                :class="Number(getRealTaxonRank(item.taxon)) <= 3 ? `rank-${getRealTaxonRank(item.taxon)}` : 'rank-normal'"
              >
                {{ getRealTaxonRank(item.taxon) }}
              </span>
              <span
                v-else
                class="rank-badge rank-noise"
                title="低频测序噪声与孤儿读段本底合集，不占用有效物种排名"
              >
                -
              </span>
            </td>
            <td>
              <div class="taxon-name-wrap">
                <span class="taxon-latin-name">{{ item.taxon }}</span>
                <span v-if="getTaxonZh(item.taxon)" class="taxon-zh-badge">{{ getTaxonZh(item.taxon) }}</span>
                <template v-if="!isNoiseTaxon(item.taxon)">
                  <span class="top-tag" v-if="getRealTaxonRank(item.taxon) === 1">绝对优势种</span>
                  <span class="top-sub-tag" v-else-if="Number(getRealTaxonRank(item.taxon)) <= 3">主要优势种</span>
                </template>
                <template v-else>
                  <span class="noise-tag">低频测序噪声</span>
                </template>
              </div>
            </td>
            <td>
              <div class="gcn-cell">
                <span class="gcn-val">{{ item.gcn_mean || 1.0 }}</span>
                <span class="badge-match" :class="item.gcn_matched !== false ? 'match-ok' : 'match-fallback'">
                  {{ item.gcn_rank || 'species' }}
                </span>
              </div>
            </td>
            <td class="mono font-bold">{{ (item.raw_count ?? item.total_raw_count ?? 0).toLocaleString() }}</td>
            <td>
              <div class="abundance-progress-wrap">
                <div class="progress-bar-bg">
                  <div
                    class="progress-bar-fill"
                    :style="{
                      width: `${Math.min(100, Math.max(item.norm_pct ?? item.overall_norm_pct ?? 0, 2))}%`,
                      background: getTaxonColor(item.taxon),
                    }"
                  ></div>
                </div>
                <span class="progress-val-txt">{{ item.norm_pct ?? item.overall_norm_pct ?? 0 }}%</span>
              </div>
            </td>
            <td class="mono text-muted">{{ item.raw_pct ?? item.overall_raw_pct ?? 0 }}%</td>
            <td>
              <div class="sample-coverage-tag">
                <span class="cov-num">
                  {{ item.sample_frequency ? `${item.sample_frequency} 点位` : `${item.sample_count || 0} 点位` }}
                </span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped src="./styles/taxa.css"></style>
