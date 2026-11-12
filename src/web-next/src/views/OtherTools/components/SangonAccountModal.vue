<script setup lang="ts">
/**
 * SangonAccountModal - 生工官网自动登录账号配置弹窗
 * 职责：
 * 1. 配置生工官网登录账号（手机号/邮箱）与密码（加密/独立密钥文件 .sangon_auth 持久化，界面仅回传掩码）；
 * 2. 配置遇到 KBSeq 费用确认弹窗时是否自动点击「确定」继续下载。
 */
import { ref, watch } from 'vue'
import type { SangonAuthMeta } from '../sangonTypes'

const props = defineProps<{
  visible: boolean
  authMeta: SangonAuthMeta
  busy?: boolean
  hintText?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: { account: string; password: string | null; auto_confirm_fee: boolean }): void
  (e: 'clearPassword'): void
}>()

const accountInput = ref('')
const passwordInput = ref('')
const autoConfirmFee = ref(true)

watch(
  () => props.visible,
  (open) => {
    if (open) {
      accountInput.value = props.authMeta?.account || ''
      passwordInput.value = ''
      autoConfirmFee.value = props.authMeta?.auto_confirm_fee ?? true
    }
  }
)

function handleSubmit(): void {
  const pwd = passwordInput.value.trim()
  emit('save', {
    account: accountInput.value.trim(),
    password: pwd ? pwd : null,
    auto_confirm_fee: autoConfirmFee.value
  })
}
</script>

<template>
  <div v-if="visible" class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-card">
      <div class="modal-header">
        <h3>生工官网账号配置</h3>
        <button class="close-btn" @click="emit('close')">&times;</button>
      </div>

      <div class="modal-body">
        <div v-if="hintText" class="hint-banner">{{ hintText }}</div>

        <div class="status-row">
          <span>
            密码状态：{{ authMeta.password_ready ? `已配置 (${authMeta.password_masked})` : '未配置' }}
          </span>
          <button
            v-if="authMeta.password_ready"
            class="btn-mini danger"
            :disabled="busy"
            @click="emit('clearPassword')"
          >
            清除已存密码
          </button>
        </div>

        <label class="field-label">
          <span>生工登录账号（手机号或邮箱）</span>
          <input
            v-model="accountInput"
            type="text"
            placeholder="例如：150xxxxxxxx"
            class="field-input"
          />
        </label>

        <label class="field-label">
          <span>生工登录密码</span>
          <input
            v-model="passwordInput"
            type="password"
            autocomplete="new-password"
            :placeholder="authMeta.password_ready ? `已保存 (${authMeta.password_masked})，留空保留原密码` : '请输入生工官网登录密码'"
            class="field-input"
          />
        </label>

        <label class="check-row">
          <input v-model="autoConfirmFee" type="checkbox" />
          <div class="check-desc">
            <strong>自动确认 KBSeq 费用明细弹窗并下载</strong>
            <span>首次下载部分三代/KBSeq 测序订单会弹出费用确认框（用于确认已知订单账单，不会新下单扣款）；取消勾选则在遇到费用弹窗时暂停等待手动下载。</span>
          </div>
        </label>

        <div v-if="authMeta.password_file" class="file-hint">
          密码独立存储文件：{{ authMeta.password_file }}
        </div>
        <div class="safe-hint">
          安全机制：正常密码登录无验证码阻断；若后续意外触发人机安全验证弹窗，自动下载将立即安全中止并提示改用「打开生工下载页」手动下载。
        </div>
      </div>

      <div class="modal-footer">
        <button class="btn-outline" @click="emit('close')">取消</button>
        <button
          class="btn-primary"
          :disabled="busy || !accountInput.trim() || (!authMeta.password_ready && !passwordInput.trim())"
          @click="handleSubmit"
        >
          保存配置
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  background: white;
  border-radius: 12px;
  width: 500px;
  max-width: 92vw;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
}
.modal-header h3 { margin: 0; font-size: 15px; color: #0f172a; }
.close-btn { background: none; border: none; font-size: 20px; cursor: pointer; color: #64748b; }

.modal-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hint-banner {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.field-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #475569;
}

.field-input {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  color: #0f172a;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
}

.check-row input {
  margin-top: 2px;
}

.check-desc {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  color: #334155;
}

.check-desc span {
  font-size: 11px;
  color: #64748b;
  line-height: 1.45;
}

.file-hint {
  font-size: 11px;
  color: #94a3b8;
  font-family: Consolas, monospace;
  word-break: break-all;
}

.safe-hint {
  font-size: 11px;
  color: #64748b;
  line-height: 1.45;
}

.btn-mini {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 3px 9px;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
}
.btn-mini.danger {
  color: #b91c1c;
  border-color: #fecaca;
}
.btn-mini.danger:hover:not(:disabled) {
  background: #fef2f2;
}

.btn-primary {
  background: #2563eb;
  color: white;
  border: none;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary:disabled { opacity: 0.55; cursor: not-allowed; }

.btn-outline {
  background: #f8fafc;
  color: #334155;
  border: 1px solid #cbd5e1;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>

