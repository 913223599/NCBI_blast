<template>
  <div class="translate-splicer" :class="{ 'has-trans': translated && !showOriginal }">
    <template v-if="translated && !showOriginal">
      <span class="translated-text">{{ translated }}</span>
    </template>
    <template v-else>
      <span class="original-text-only">{{ original }}</span>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 翻译拼接组件
 * 职责：实现原文/译文的平滑切换（替换显示）。
 */
defineProps<{
  original: string
  translated?: string | null
  showOriginal?: boolean
}>()
</script>

<style scoped>
.translate-splicer {
  display: inline-block;
  cursor: pointer;
  transition: opacity 0.2s;
}

.translate-splicer:hover {
  opacity: 0.8;
}

.translated-text {
  font-weight: 700;
  color: #2563eb; /* 使用蓝色强调翻译内容 */
}

.original-text-only {
  color: #1e293b;
  font-weight: 400;
}
</style>
