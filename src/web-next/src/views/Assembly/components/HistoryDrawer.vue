
<script setup lang="ts">
const props = defineProps<{
  show: boolean;
  history: any[];
}>();

const emit = defineEmits(['close', 'select', 'delete', 'resume', 'restart']);

const formatDate = (dateStr: string) => {
  if (!dateStr) return '--';
  return new Date(dateStr).toLocaleString();
};

const getStatusLabel = (status: string) => {
  const map: Record<string, string> = {
    'completed': '已完成',
    'failed': '失败',
    'running': '执行中',
    'error': '异常',
    'aborted': '已中止'
  };
  return map[status] || status;
};

const handleDelete = (id: string) => {
  if (confirm('确定要删除该历史任务吗？相关物理文件将保留在服务器。')) {
    emit('delete', id);
  }
};

const handleOpenFolder = async (task: any) => {
  if (!task.id) return;
  
  // 🔗 获取项目根路径并拼接绝对路径
  try {
    const root = await (window as any).electronAPI?.getProjectRoot();
    if (root) {
      // 路径规则: {root}/results/assembly/{id}
      // 注意: Windows 下使用反斜杠或让 Electron 处理
      const fullPath = `${root}/results/assembly/${task.id}`;
      await (window as any).electronAPI?.openPath(fullPath);
    } else {
      // 兜底策略: 如果不在 Electron 环境，尝试提示相对路径
      const relPath = `results/assembly/${task.id}`;
      alert(`任务目录: ${relPath}\n(非桌面客户端环境，请手动前往查看)`);
    }
  } catch (e) {
    console.error('无法打开文件夹:', e);
    alert('无法自动打开文件夹，请手动检查 results 目录');
  }
};
</script>

<template>
  <div class="drawer-overlay" v-if="show" @click="emit('close')">
    <div class="drawer-content" @click.stop>
      <div class="drawer-header">
        <div class="header-title">
          <h3>任务历史</h3>
          <span class="history-count">{{ history.length }} 个任务</span>
        </div>
        <button class="close-btn" @click="emit('close')">×</button>
      </div>

      <div class="history-list">
        <div v-if="history.length === 0" class="empty-tip">暂无拼接历史记录</div>
        
        <div 
          v-for="task in history" 
          :key="task.id" 
          class="history-item"
          @click="emit('select', task)"
        >
          <div class="item-header">
            <span class="task-name">{{ task.name || '未命名任务' }}</span>
            <div class="header-actions">
              <span class="task-status" :class="task.status">{{ getStatusLabel(task.status) }}</span>
              <button class="delete-btn" @click.stop="handleDelete(task.id)" title="删除记录">🗑️</button>
            </div>
          </div>
          
          <div class="item-meta">
            <span class="meta-tag">{{ task.sampleType }}</span>
            <span class="meta-tag">{{ task.tech }}</span>
          </div>

          <!-- 🔗 快捷操作区 -->
          <div class="item-ops" v-if="['failed', 'error', 'completed', 'aborted'].includes(task.status)">
            <button 
              v-if="['failed', 'error', 'aborted'].includes(task.status)" 
              class="op-btn resume-btn" 
              @click.stop="emit('resume', task)"
            >
              ▶️ 断点继续
            </button>
            <button 
              v-if="task.status === 'completed'"
              class="op-btn open-btn"
              @click.stop="handleOpenFolder(task)"
            >
              📁 查看结果
            </button>
            <button class="op-btn restart-btn" @click.stop="emit('restart', task)">
              🔄 重新开始
            </button>
          </div>

          <div class="item-footer">
            <span class="task-id">ID: {{ task.id.substring(3, 11) }}</span>
            <span class="time">{{ formatDate(task.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.drawer-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex; justify-content: flex-end;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.drawer-content {
  width: 380px; height: 100%;
  background: white; box-shadow: -5px 0 25px rgba(0,0,0,0.1);
  display: flex; flex-direction: column;
  animation: slideRight 0.3s ease-out;
}

.drawer-header {
  padding: 24px; border-bottom: 1px solid #f1f5f9;
  display: flex; justify-content: space-between; align-items: center;
}

.drawer-header h3 { margin: 0; font-size: 18px; color: #1e293b; }
.close-btn { background: none; border: none; font-size: 24px; cursor: pointer; color: #94a3b8; }

.history-list { flex: 1; overflow-y: auto; padding: 16px; }
.history-item {
  padding: 16px; border: 1px solid #f1f5f9; border-radius: 10px; margin-bottom: 12px;
  cursor: pointer; transition: all 0.2s;
}
.history-item:hover { border-color: #3b82f6; background: #f8fafc; }

.item-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.task-name { font-weight: 600; color: #334155; }
.task-status { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
.delete-btn { 
  background: none; border: none; font-size: 14px; cursor: pointer; opacity: 0.3; 
  transition: all 0.2s; padding: 2px;
}
.delete-btn:hover { opacity: 1; transform: scale(1.2); }
.task-status.completed { background: #ecfdf5; color: #059669; }
.task-status.failed, .task-status.error { background: #fef2f2; color: #dc2626; }
.task-status.running { background: #eff6ff; color: #2563eb; }
.task-status.aborted { background: #f1f5f9; color: #64748b; }

.item-meta { font-size: 12px; color: #64748b; display: flex; gap: 10px; margin-bottom: 12px; }

.item-ops {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  padding-top: 12px;
  border-top: 1px dashed #e2e8f0;
}

.op-btn {
  flex: 1;
  padding: 6px 0;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.resume-btn {
  background: #f0f9ff;
  color: #0369a1;
}
.resume-btn:hover {
  background: #e0f2fe;
}

.open-btn {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #dbeafe;
}
.open-btn:hover {
  background: #dbeafe;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1);
}

.restart-btn {
  background: #f8fafc;
  color: #475569;
  border: 1px solid #e2e8f0;
}
.restart-btn:hover {
  background: #f1f5f9;
}

.item-footer { font-size: 11px; color: #94a3b8; display: flex; justify-content: space-between; align-items: center; }
.task-id { font-family: monospace; }

.empty-tip { text-align: center; color: #94a3b8; margin-top: 40px; font-size: 14px; }

@keyframes slideRight { from { transform: translateX(100%); } to { transform: translateX(0); } }
</style>
