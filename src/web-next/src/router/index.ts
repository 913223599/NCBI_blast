/**
 * Vue Router 配置
 * 采用懒加载实现按需加载各视图
 */
import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
    {
        path: '/',
        name: 'dashboard',
        component: () => import('../views/DashboardView.vue'),
        meta: { title: '仪表盘', icon: 'dashboard' }
    },
    {
        path: '/blast',
        name: 'blast',
        component: () => import('../views/BlastView.vue'),
        meta: { title: 'BLAST 分析', icon: 'blast' }
    },
    {
        path: '/tree',
        name: 'tree',
        component: () => import('../views/TreeView.vue'),
        meta: { title: '进化树', icon: 'tree' }
    },
    {
        path: '/strain',
        name: 'strain',
        component: () => import('../views/StrainView.vue'),
        meta: { title: '菌毒种库', icon: 'strain' }
    },
    {
        path: '/settings',
        name: 'settings',
        component: () => import('../views/SettingsView.vue'),
        meta: { title: '设置', icon: 'settings' }
    },
    {
        path: '/help',
        name: 'help',
        component: () => import('../views/HelpView.vue'),
        meta: { title: '帮助', icon: 'help' }
    }
]

const router = createRouter({
    history: createWebHashHistory(),
    routes
})

export default router
