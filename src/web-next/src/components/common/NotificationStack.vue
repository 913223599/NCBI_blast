<script setup lang="ts">
/**
 * NotificationStack - 全局通知提示组件
 */
import { useAppStore } from '../../stores/app'

const appStore = useAppStore()
</script>

<template>
  <div class="notification-stack">
    <TransitionGroup name="notif">
      <div
        v-for="notif in appStore.notifications"
        :key="notif.id"
        class="notification"
        :class="notif.type"
      >
        {{ notif.message }}
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.notification-stack {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notification {
  padding: 12px 20px;
  border-radius: 8px;
  color: #fff;
  font-size: 0.875rem;
  font-weight: 500;
  max-width: 360px;
}

.notification.info { background: rgba(59, 130, 246, 0.9); }
.notification.success { background: rgba(16, 185, 129, 0.9); }
.notification.warning { background: rgba(245, 158, 11, 0.9); }
.notification.error { background: rgba(239, 68, 68, 0.9); }

.notif-enter-active { animation: slideIn 0.3s ease-out; }
.notif-leave-active { animation: slideOut 0.3s ease-in; }

@keyframes slideIn {
  from { transform: translateX(100px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

@keyframes slideOut {
  from { transform: translateX(0); opacity: 1; }
  to { transform: translateX(100px); opacity: 0; }
}
</style>