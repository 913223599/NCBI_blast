<script setup lang="ts">
/**
 * UniversalUpload - 通用文件上传/拖拽组件
 * 核心逻辑：屏蔽 Electron 和 Web 环境差异，统一输出后端可访问的文件路径
 */
import { ref } from 'vue'
import { getBridge } from '../../bridge'
import { useAppStore } from '../../stores/app'

interface Props {
  accept?: string // 例如 ".fasta,.fas"
  multiple?: boolean
  label?: string
  icon?: string
  type: 'fasta' | 'tree' | 'all' // 用于 Electron 过滤器的标识
}

const props = withDefaults(defineProps<Props>(), {
  accept: '*',
  multiple: true,
  label: '点击或拖拽文件至此处',
  icon: '📤',
  type: 'all'
})

const emit = defineEmits<{
  (e: 'success', paths: string[]): void
  (e: 'error', msg: string): void
}>()

const appStore = useAppStore()
const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)

/**
 * 核心处理逻辑：将 File 对象数组转化为后端路径数组
 */
async function processFiles(files: File[]) {
  const bridge = getBridge()
  const processedPaths: string[] = []
  
  appStore.showNotification(`正在处理 ${files.length} 个文件...`, 'info')

  for (const f of files) {
    // 1. 尝试获取本地物理路径 (Electron)
    const localPath = bridge.get_path_for_file(f)
    if (localPath) {
      processedPaths.push(localPath)
    } else {
      // 2. 网页端：执行流式上传
      try {
        const res = await bridge.upload_file(f)
        if (res.success && res.path) {
          processedPaths.push(res.path)
        } else {
          appStore.showNotification(`上传失败: ${f.name} - ${res.error || '未知错误'}`, 'error')
        }
      } catch (err) {
        emit('error', `文件 ${f.name} 处理异常`)
      }
    }
  }

  if (processedPaths.length > 0) {
    emit('success', processedPaths)
  }
}

/**
 * 点击触发：区分 Electron 和 Web
 */
function handleClick() {
  const bridge = getBridge()
  const isElectron = !!(window as any).electronAPI
  
  if (isElectron) {
    // Electron 环境使用原生对话框
    bridge.request_file_load(props.type)
    // 注意：request_file_load 通常是在 bridge 内部通过 handleFileLoaded 回调全局的
    // 为了让通用组件能拿到结果，我们需要在这里手动拦截或通过全局事件发送
  } else {
    // 网页环境触发隐藏的 Input
    fileInputRef.value?.click()
  }
}

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    processFiles(Array.from(target.files))
    target.value = '' // 清空以便下次触发
  }
}

function handleDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files.length) {
    processFiles(Array.from(e.dataTransfer.files))
  }
}
</script>

<template>
  <div 
    class="universal-upload-zone"
    :class="{ 'is-dragging': isDragging }"
    @click="handleClick"
    @dragover.prevent="isDragging = true"
    @dragleave.prevent="isDragging = false"
    @drop.prevent="handleDrop"
  >
    <input 
      type="file" 
      ref="fileInputRef" 
      style="display: none" 
      :multiple="multiple" 
      :accept="accept"
      @change="onFileChange"
    />
    
    <div class="upload-inner">
      <span class="upload-icon">{{ icon }}</span>
      <span class="upload-text">{{ label }}</span>
      <slot name="extra"></slot>
    </div>
  </div>
</template>

<style scoped>
.universal-upload-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 32px 20px;
  text-align: center;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  background: #f8fafc;
  cursor: pointer;
  position: relative;
  overflow: hidden;
}

.universal-upload-zone:hover {
  border-color: #2563eb;
  background: #f0f7ff;
}

.universal-upload-zone.is-dragging {
  border-color: #2563eb;
  background: #eff6ff;
  transform: scale(1.02);
  box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.1);
}

.upload-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}

.upload-icon {
  font-size: 2rem;
  transition: transform 0.2s;
}

.universal-upload-zone:hover .upload-icon {
  transform: translateY(-4px);
}

.upload-text {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 600;
}
</style>
