<script setup lang="ts">
/**
 * NodeLibrary - 节点库侧面板
 * 显示可用节点类型列表，支持拖拽添加到画布
 * 动态从 Python 后端加载工具定义
 */
import { ref, computed, onMounted } from 'vue'
import { getBridge } from '../../bridge/pyqt-bridge'
import type { NodeData, NodePin, NodeParam } from '../../stores/studio'

const emit = defineEmits<{
  addNode: [type: string, label: string, posX: number, posY: number, config?: Partial<NodeData>]
}>()

interface NodeTemplate {
  type: string
  label: string
  description: string
  category: string
  color: string
  pins: NodePin[]
  params: NodeParam[]
}

// 默认基础节点
const DEFAULT_TEMPLATES: NodeTemplate[] = [
  {
    type: 'fasta_input', label: 'FASTA 输入', description: '加载 FASTA 序列文件',
    category: '输入/输出', color: '#10b981',
    pins: [{ pinId: 'out_fasta', label: 'FASTA', direction: 'output', dataType: 'fasta' }],
    params: [{ key: 'file_path', label: '文件路径', type: 'file', value: '', placeholder: '选择文件...' }]
  },
  {
    type: 'tree_view', label: '进化树可视化', description: '渲染 Newick 进化树',
    category: '可视化', color: '#ec4899',
    pins: [{ pinId: 'in_tree', label: 'Newick', direction: 'input', dataType: 'newick' }],
    params: []
  },
  {
    type: 'csv_export', label: 'CSV 导出', description: '导出结果为 CSV',
    category: '输入/输出', color: '#10b981',
    pins: [{ pinId: 'in_data', label: '数据', direction: 'input', dataType: 'any' }],
    params: [{ key: 'delimiter', label: '分隔符', type: 'select', value: ',', options: [
      { value: ',', label: '逗号' }, { value: '\t', label: 'Tab' }, { value: ';', label: '分号' }
    ]}]
  }
]

const nodeTemplates = ref<NodeTemplate[]>([...DEFAULT_TEMPLATES])

const categories = computed(() => [...new Set(nodeTemplates.value.map(t => t.category))])

// 颜色映射
const CATEGORY_COLORS: Record<string, string> = {
  'io': '#10b981',
  'process': '#3b82f6',
  'convert': '#06b6d4',
  'phylogeny': '#10b981',
  'data': '#f59e0b',
  'hmm': '#a855f7',
  'blast_util': '#ef4444'
}

const CATEGORY_NAMES: Record<string, string> = {
  'io': '输入/输出',
  'process': '分析',
  'convert': '转换',
  'phylogeny': '系统发育',
  'data': '数据',
  'hmm': 'HMM 模型',
  'blast_util': 'BLAST 工具'
}

function onAddNode(template: NodeTemplate): void {
  const posX = 200 + Math.random() * 200
  const posY = 100 + Math.random() * 200
  emit('addNode', template.type, template.label, posX, posY, {
    color: template.color,
    pins: template.pins.map(pin => ({ ...pin })),
    params: template.params.map(param => ({ ...param }))
  })
}

onMounted(() => {
  try {
    const bridge = getBridge()
    if (bridge && bridge.get_tools_metadata) {
      bridge.get_tools_metadata((jsonStr) => {
        try {
          const metadata = JSON.parse(jsonStr)
          if (metadata && Array.isArray(metadata.tools)) {
            // 映射工具
            const loadedTools: NodeTemplate[] = metadata.tools.map((tool: any) => {
              const catKey = tool.cat || 'process'
              const catName = CATEGORY_NAMES[catKey] || '其他'
              const color = CATEGORY_COLORS[catKey] || '#64748b'
              
              // Map Pins
              const pins: NodePin[] = []
              if (tool.in) tool.in.forEach((type: string, idx: number) => {
                 pins.push({ pinId: `in_${idx}`, label: type, direction: 'input', dataType: type })
              })
              if (tool.out) tool.out.forEach((type: string, idx: number) => {
                 pins.push({ pinId: `out_${idx}`, label: type, direction: 'output', dataType: type })
              })
              
              // Map Params
              const params: NodeParam[] = []
              if (tool.params) {
                tool.params.forEach((p: any) => {
                   // Simple heuristic
                   const isBool = p.default === null
                   params.push({
                     key: p.name.replace(/^-+/, ''),
                     label: p.name.replace(/^-+/, ''),
                     type: isBool ? 'checkbox' : 'text', // Fallback to text
                     value: p.default !== null ? p.default : false
                   })
                })
              }

              return {
                type: tool.id,
                label: tool.name,
                description: tool.desc || tool.name,
                category: catName,
                color: color,
                pins,
                params
              }
            })
            
            // Merge: filter out defaults that are present in loaded
            const loadedIds = new Set(loadedTools.map(t => t.type))
            const keepDefaults = DEFAULT_TEMPLATES.filter(t => !loadedIds.has(t.type))
            
            nodeTemplates.value = [...keepDefaults, ...loadedTools]
          }
        } catch (e) {
          console.error('[NodeLibrary] Failed to parse tools metadata', e)
        }
      })
    }
  } catch (e) {
    // Bridge not ready or mock
    console.warn('[NodeLibrary] Bridge not available', e)
  }
})
</script>

<template>
  <aside class="node-library">
    <div class="lib-header">
      <h3>📦 节点库</h3>
    </div>
    <div class="lib-list">
      <template v-for="cat in categories" :key="cat">
        <div class="lib-category">{{ cat }}</div>
        <div
          v-for="tpl in nodeTemplates.filter(nodeTemplate => nodeTemplate.category === cat)"
          :key="tpl.type"
          class="lib-item"
          @click="onAddNode(tpl)"
        >
          <div class="lib-dot" :style="{ background: tpl.color }" />
          <div class="lib-info">
            <div class="lib-name">{{ tpl.label }}</div>
            <div class="lib-desc">{{ tpl.description }}</div>
          </div>
        </div>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.node-library {
  width: 240px;
  min-width: 240px;
  background: #1e293b;
  border-right: 1px solid #334155;
  display: flex;
  flex-direction: column;
  z-index: 40;
}

.lib-header {
  padding: 14px 16px;
  border-bottom: 1px solid #334155;
}
.lib-header h3 { margin: 0; font-size: 0.85rem; color: #e2e8f0; }

.lib-list { flex: 1; overflow-y: auto; padding: 8px; }

.lib-category {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #64748b;
  padding: 12px 8px 4px;
  font-weight: 600;
}

.lib-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.lib-item:hover { background: rgba(255, 255, 255, 0.05); }

.lib-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.lib-name { font-size: 0.8rem; color: #e2e8f0; font-weight: 500; }
.lib-desc { font-size: 0.68rem; color: #64748b; margin-top: 1px; }
</style>
