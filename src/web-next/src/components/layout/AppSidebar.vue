<script setup lang="ts">
/**
 * AppSidebar - 应用侧边栏导航
 * 从旧版 index.html 中的 #sidebar 迁移而来
 */
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../../stores/app'

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()

interface NavItem {
  id: string
  label: string
  icon: string
  route: string
  category?: string
}

const navItems: NavItem[] = [
  { id: 'dashboard', label: '仪表盘', icon: 'dashboard', route: '/', category: '主要' },
  { id: 'strain', label: '菌毒种库', icon: 'strain', route: '/strain', category: '分析工具' },
  { id: 'assembly', label: '基因组拼接', icon: 'assembly', route: '/assembly', category: '分析工具' },
  { id: 'analysis', label: '组装分析', icon: 'analysis', route: '/analysis', category: '分析工具' },
  { id: 'blast', label: 'BLAST 分析', icon: 'blast', route: '/blast', category: '分析工具' },
  { id: 'tree', label: '进化树', icon: 'tree', route: '/tree', category: '分析工具' },
  { id: 'settings', label: '设置', icon: 'settings', route: '/settings', category: '系统' },
  { id: 'help', label: '帮助', icon: 'help', route: '/help', category: '系统' }
]

/** 按 category 分组 */
const categories = [...new Set(navItems.map(item => item.category))]

function navigateTo(item: NavItem): void {
  router.push(item.route)
  appStore.setPageTitle(item.label)
}

function isActive(item: NavItem): boolean {
  return route.path === item.route
}
</script>

<template>
  <nav class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
    <!-- Logo -->
    <div class="brand">
      <div class="logo-container">
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
      <span class="brand-text">NCBI <span class="brand-sub">Pro</span></span>
    </div>

    <!-- 导航菜单 -->
    <div class="nav-menu">
      <template v-for="cat in categories" :key="cat">
        <div class="nav-category">{{ cat }}</div>
        <div
          v-for="item in navItems.filter(n => n.category === cat)"
          :key="item.id"
          class="nav-item"
          :class="{ active: isActive(item) }"
          @click="navigateTo(item)"
        >
          <svg class="nav-icon" viewBox="0 0 24 24">
            <!-- Dashboard -->
            <template v-if="item.icon === 'dashboard'">
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
            </template>
            <!-- Strain (Enhanced Microbial Icon) -->
            <template v-else-if="item.icon === 'strain'">
              <circle cx="12" cy="12" r="6" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
              <path d="M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
              <path d="M9 12a3 3 0 0 1 6 0" />
            </template>
            <!-- BLAST -->
            <template v-else-if="item.icon === 'blast'">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </template>
            <!-- Tree -->
            <template v-else-if="item.icon === 'tree'">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </template>
            <!-- Assembly -->
            <template v-else-if="item.icon === 'assembly'">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
              <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
              <line x1="12" y1="22.08" x2="12" y2="12" />
            </template>
            <!-- Analysis -->
            <template v-else-if="item.icon === 'analysis'">
              <path d="M21 12A9 9 0 1 1 12 3v9z" />
              <path d="M12 3a9 9 0 0 1 9 9h-9z" />
              <path d="M12 12V3" />
            </template>
            <!-- Settings -->
            <template v-else-if="item.icon === 'settings'">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </template>
            <!-- Help -->
            <template v-else>
              <circle cx="12" cy="12" r="10" />
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </template>
          </svg>
          <span class="nav-text">{{ item.label }}</span>
        </div>
      </template>
    </div>

    <!-- 折叠按钮 -->
    <div class="sidebar-footer">
      <div class="toggle-btn" @click="appStore.toggleSidebar()">
        <svg class="nav-icon" viewBox="0 0 24 24">
          <polyline points="11 17 6 12 11 7" />
          <polyline points="18 17 13 12 18 7" />
        </svg>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.sidebar {
  width: 260px;
  min-width: 260px;
  height: 100vh;
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
  display: flex;
  flex-direction: column;
  /* transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1),
              min-width 0.3s cubic-bezier(0.4, 0, 0.2, 1); transform-origin: left; */
  overflow: hidden;
  z-index: 100;
}

.sidebar.collapsed {
  width: 60px;
  min-width: 60px;
}

.brand {
  padding: 20px 20px 15px;
  display: flex;
  align-items: center;
  white-space: nowrap;
}

.brand-text {
  color: #f8fafc;
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: -0.5px;
  background: linear-gradient(to right, #f8fafc, #94a3b8);
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.brand-sub {
  font-size: 0.7em;
  font-weight: 400;
  color: #60a5fa;
  -webkit-text-fill-color: #60a5fa;
  margin-left: 2px;
}

.logo-container {
  width: 32px;
  height: 32px;
  margin-right: 12px;
}

.logo-svg {
  width: 100%;
  height: 100%;
}

.collapsed .brand-text { display: none; }
.collapsed .brand { justify-content: center; padding: 20px 0; }

.nav-menu {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.nav-category {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #64748b;
  padding: 16px 12px 6px;
}

.collapsed .nav-category { display: none; }

.nav-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: 8px;
  cursor: pointer;
  color: #94a3b8;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  white-space: nowrap;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}

.nav-item.active {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
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

.collapsed .nav-text { display: none; }
.collapsed .nav-item { justify-content: center; padding: 10px; }

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  color: #64748b;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.toggle-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}

.collapsed .toggle-btn svg {
  transform: rotate(180deg);
}
</style>