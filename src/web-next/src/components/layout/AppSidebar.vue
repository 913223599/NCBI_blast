<script setup lang="ts">
/**
 * AppSidebar - 应用侧边栏语义导航（无障碍键盘可达 + 折叠 Tooltip）
 */
import { computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../../stores/app'
import { useI18n } from '../../locales'

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()
const { t } = useI18n()

interface NavItem {
  id: string
  label: string
  icon: string
  route: string
  categoryKey: string
  category: string
}

const navItems = computed<NavItem[]>(() => [
  { id: 'dashboard', label: t('nav.dashboard'), icon: 'dashboard', route: '/', categoryKey: 'main', category: t('nav.cat.main') },
  { id: 'strain', label: t('nav.strain'), icon: 'strain', route: '/strain', categoryKey: 'tools', category: t('nav.cat.tools') },
  { id: 'assembly', label: t('nav.assembly'), icon: 'assembly', route: '/assembly', categoryKey: 'tools', category: t('nav.cat.tools') },
  { id: 'analysis', label: t('nav.analysis'), icon: 'analysis', route: '/analysis', categoryKey: 'tools', category: t('nav.cat.tools') },
  { id: 'blast', label: t('nav.blast'), icon: 'blast', route: '/blast', categoryKey: 'tools', category: t('nav.cat.tools') },
  { id: 'tree', label: t('nav.tree'), icon: 'tree', route: '/tree', categoryKey: 'tools', category: t('nav.cat.tools') },
  { id: 'other_tools', label: t('nav.other_tools'), icon: 'other_tools', route: '/other-tools', categoryKey: 'tools', category: t('nav.cat.tools') },
  { id: 'settings', label: t('nav.settings'), icon: 'settings', route: '/settings', categoryKey: 'system', category: t('nav.cat.system') },
  { id: 'help', label: t('nav.help'), icon: 'help', route: '/help', categoryKey: 'system', category: t('nav.cat.system') },
])

const categories = computed(() => {
  const seen = new Set<string>()
  const list: Array<{ key: string; label: string }> = []
  for (const item of navItems.value) {
    if (!seen.has(item.categoryKey)) {
      seen.add(item.categoryKey)
      list.push({ key: item.categoryKey, label: item.category })
    }
  }
  return list
})

function navigateTo(item: NavItem): void {
  router.push(item.route)
  appStore.setPageTitle(item.label)
}

function isActive(item: NavItem): boolean {
  return route.path === item.route
}

// 路由直达、浏览器后退或切换界面语言时同步顶栏页面标题
watch(
  [() => route.path, () => appStore.locale],
  ([path]) => {
    const matched = navItems.value.find((item) => item.route === path)
    if (matched) {
      appStore.setPageTitle(matched.label)
    } else if (typeof route.meta?.title === 'string') {
      appStore.setPageTitle(route.meta.title)
    }
  },
  { immediate: true }
)
</script>

<template>
  <nav
    class="sidebar"
    :class="{ collapsed: appStore.sidebarCollapsed }"
    :aria-label="t('nav.aria_main')"
  >
    <div class="brand" title="NCBI Bio-Station">
      <div class="logo-container" aria-hidden="true">
        <svg class="logo-svg" viewBox="0 0 100 100">
          <defs>
            <linearGradient id="logo-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" style="stop-color:#60a5fa" />
              <stop offset="100%" style="stop-color:#34d399" />
            </linearGradient>
          </defs>
          <path d="M50 5 L90 27.5 L90 72.5 L50 95 L10 72.5 L10 27.5 Z" fill="none" stroke="url(#logo-gradient)" stroke-width="8" />
          <path d="M35 30 C35 30, 65 30, 50 50 C35 70, 65 70, 65 70" fill="none" stroke="white" stroke-width="6" stroke-linecap="round" />
          <circle cx="35" cy="30" r="4" fill="white" />
          <circle cx="65" cy="70" r="4" fill="white" />
        </svg>
      </div>
      <span class="brand-text">Bio-Station <span class="brand-sub">NCBI</span></span>
    </div>

    <div class="nav-menu">
      <template v-for="cat in categories" :key="cat.key">
        <div class="nav-category">{{ cat.label }}</div>
        <button
          v-for="item in navItems.filter((n) => n.categoryKey === cat.key)"
          :key="item.id"
          type="button"
          class="nav-item"
          :class="{ active: isActive(item) }"
          :title="appStore.sidebarCollapsed ? item.label : undefined"
          :aria-label="item.label"
          :aria-current="isActive(item) ? 'page' : undefined"
          @click="navigateTo(item)"
        >
          <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
            <template v-if="item.icon === 'dashboard'">
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
            </template>
            <template v-else-if="item.icon === 'strain'">
              <circle cx="12" cy="12" r="6" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
              <path d="M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
              <path d="M9 12a3 3 0 0 1 6 0" />
            </template>
            <template v-else-if="item.icon === 'blast'">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </template>
            <template v-else-if="item.icon === 'tree'">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </template>
            <template v-else-if="item.icon === 'assembly'">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
              <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
              <line x1="12" y1="22.08" x2="12" y2="12" />
            </template>
            <template v-else-if="item.icon === 'analysis'">
              <path d="M21 12A9 9 0 1 1 12 3v9z" />
              <path d="M12 3a9 9 0 0 1 9 9h-9z" />
              <path d="M12 12V3" />
            </template>
            <template v-else-if="item.icon === 'other_tools'">
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
              <path d="M16 19h6" />
              <path d="m19 16 3 3-3 3" />
            </template>
            <template v-else-if="item.icon === 'settings'">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </template>
            <template v-else>
              <circle cx="12" cy="12" r="10" />
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </template>
          </svg>
          <span class="nav-text">{{ item.label }}</span>
        </button>
      </template>
    </div>

    <div class="sidebar-footer">
      <button
        type="button"
        class="toggle-btn"
        :title="appStore.sidebarCollapsed ? t('nav.expand_sidebar') : t('nav.collapse_sidebar')"
        :aria-label="appStore.sidebarCollapsed ? t('nav.expand_sidebar') : t('nav.collapse_sidebar')"
        :aria-expanded="!appStore.sidebarCollapsed"
        @click="appStore.toggleSidebar()"
      >
        <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
          <polyline points="11 17 6 12 11 7" />
          <polyline points="18 17 13 12 18 7" />
        </svg>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.sidebar {
  width: 248px;
  min-width: 248px;
  height: 100vh;
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 100;
}

.sidebar.collapsed {
  width: 60px;
  min-width: 60px;
}

.brand {
  padding: 18px 18px 14px;
  display: flex;
  align-items: center;
  white-space: nowrap;
}

.brand-text {
  color: #f8fafc;
  font-size: 1.12rem;
  font-weight: 800;
  letter-spacing: -0.4px;
}

.brand-sub {
  font-size: 0.72em;
  font-weight: 500;
  color: #60a5fa;
  margin-left: 4px;
}

.logo-container {
  width: 30px;
  height: 30px;
  margin-right: 11px;
  flex-shrink: 0;
}

.logo-svg {
  width: 100%;
  height: 100%;
}

.collapsed .brand-text {
  display: none;
}

.collapsed .brand {
  justify-content: center;
  padding: 18px 0;
}

.collapsed .logo-container {
  margin-right: 0;
}

.nav-menu {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.nav-category {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: #94a3b8;
  padding: 14px 12px 6px;
}

.collapsed .nav-category {
  display: none;
}

.nav-item {
  width: 100%;
  background: transparent;
  text-align: left;
  display: flex;
  align-items: center;
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: 8px;
  cursor: pointer;
  color: #cbd5e1;
  transition: background-color 0.16s, color 0.16s;
  white-space: nowrap;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
}

.nav-item.active {
  background: rgba(59, 130, 246, 0.22);
  color: #93c5fd;
}

.nav-item:focus-visible,
.toggle-btn:focus-visible {
  outline: 2px solid #60a5fa;
  outline-offset: -2px;
}

.nav-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.nav-text {
  margin-left: 12px;
  font-size: 0.875rem;
  font-weight: 500;
}

.collapsed .nav-text {
  display: none;
}

.collapsed .nav-item {
  justify-content: center;
  padding: 10px;
}

.sidebar-footer {
  padding: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.toggle-btn {
  width: 100%;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  color: #94a3b8;
  transition: background-color 0.16s, color 0.16s;
}

.toggle-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
}

.collapsed .toggle-btn svg {
  transform: rotate(180deg);
}

@media (max-width: 1024px) {
  .sidebar:not(.collapsed) {
    width: 210px;
    min-width: 210px;
  }
}
</style>
