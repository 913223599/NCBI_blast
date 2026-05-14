<script setup lang="ts">
import { computed } from 'vue';

interface QueuedTask {
  id: string;
  name: string;
  status: 'running' | 'pending' | 'queued';
  position: number;
  tech: string;
}

const props = defineProps<{
  queue: QueuedTask[];
  activeTaskId?: string;
}>();

const emit = defineEmits(['focus']);

const sortedQueue = computed(() => {
  return [...props.queue].sort((a, b) => {
    if (a.status === 'running') return -1;
    if (b.status === 'running') return 1;
    return a.position - b.position;
  });
});

const getStatusLabel = (task: QueuedTask) => {
  if (task.status === 'running') return '正在运行';
  return `排队中 #${task.position}`;
};

const getStatusClass = (task: QueuedTask) => {
  return {
    'status-running': task.status === 'running',
    'status-queued': task.status !== 'running',
    'is-active': task.id === props.activeTaskId
  };
};
</script>

<template>
  <div class="queue-monitor-container">
    <div class="monitor-header">
      <div class="title-group">
        <span class="pulse-dot" :class="{ 'inactive': queue.length === 0 }"></span>
        <h3>任务队列监控</h3>
        <span class="count-badge">{{ queue.length }}</span>
      </div>
    </div>
    
    <div v-if="queue.length > 0" class="queue-list">
      <div 
        v-for="task in sortedQueue" 
        :key="task.id"
        class="task-card"
        :class="getStatusClass(task)"
        @click="emit('focus', task.id)"
      >
        <div class="card-left">
          <div class="tech-icon" :title="task.tech">
            {{ task.tech ? task.tech.charAt(0) : 'A' }}
          </div>
        </div>
        <div class="card-info">
          <div class="task-name">{{ task.name || '未命名任务' }}</div>
          <div class="task-meta">
            <span class="status-tag">{{ getStatusLabel(task) }}</span>
            <span class="id-tag">ID: {{ task.id.split('_').pop() }}</span>
          </div>
        </div>
        <div v-if="task.status === 'running'" class="running-indicator">
          <div class="bar-container">
            <div class="bar-fill"></div>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="empty-queue-hint">
       当前计算引擎空闲，可以直接提交任务
    </div>
  </div>
</template>

<style scoped>
.queue-monitor-container {
  background: white;
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.05);
  margin-bottom: 8px;
  border: 1px solid rgba(0,0,0,0.03);
}

.monitor-header {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
}

.title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  background: #10b981;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

.pulse-dot.inactive {
  background: #cbd5e1;
  animation: none;
}

@keyframes pulse {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

.empty-queue-hint {
  padding: 20px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
  background: #f8fafc;
  border: 1px dashed #e2e8f0;
  border-radius: 12px;
}

h3 {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.count-badge {
  background: #f1f5f9;
  color: #64748b;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
}

.queue-list {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
  scrollbar-width: thin;
}

.queue-list::-webkit-scrollbar { height: 4px; }
.queue-list::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 10px; }

.task-card {
  flex: 0 0 240px;
  background: #f8fafc;
  border-radius: 12px;
  padding: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
  position: relative;
  overflow: hidden;
}

.task-card:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.task-card.is-active {
  background: white;
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
}

.tech-icon {
  width: 32px;
  height: 32px;
  background: #3b82f6;
  color: white;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 14px;
}

.status-running .tech-icon {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
}

.card-info {
  flex: 1;
  min-width: 0;
}

.task-name {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.status-tag {
  font-size: 10px;
  font-weight: 500;
  color: #3b82f6;
}

.status-running .status-tag {
  color: #10b981;
}

.id-tag {
  font-size: 10px;
  color: #94a3b8;
}

.running-indicator {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
}

.bar-container {
  width: 100%;
  height: 100%;
  background: #d1fae5;
}

.bar-fill {
  height: 100%;
  background: #10b981;
  width: 30%;
  animation: loading 1.5s infinite ease-in-out;
}

@keyframes loading {
  0% { transform: translateX(-100%); width: 30%; }
  50% { width: 60%; }
  100% { transform: translateX(400%); width: 30%; }
}
</style>
