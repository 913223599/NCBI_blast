<script setup lang="ts">
/**
 * SangonAccountModal - 生工官网自动登录账号与无头浏览器配置弹窗
 * 职责：
 * 1. 配置生工官网登录账号（手机号/邮箱）与密码（独立密钥文件 .sangon_auth 持久化，界面仅回传掩码）；
 * 2. 配置遇到 KBSeq 费用确认弹窗时是否自动点击「确定」继续下载；
 * 3. 展示无头浏览器（Playwright Chromium）启动检查状态、切换有头/无头及系统兜底并触发一键自修复。
 */
import { computed, ref, watch } from 'vue'
import type { BrowserEnvStatus, SangonAuthMeta } from '../sangonTypes'

const props = defineProps<{
  visible: boolean
  authMeta: SangonAuthMeta
  browserEnv?: BrowserEnvStatus | null
  busy?: boolean
  repairingBrowser?: boolean
  hintText?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: { account: string; password: string | null; auto_confirm_fee: boolean }): void
  (e: 'clearPassword'): void
  (e: 'repairBrowser', payload: {
    enabled: boolean
    headless: boolean
    use_system_browser_fallback: boolean
    auto_install: boolean
    probe_launch: boolean
  }): void
}>()

const accountInput = ref('')
const passwordInput = ref('')
const autoConfirmFee = ref(true)
const browserEnabled = ref(true)
const browserHeadless = ref(true)
const browserFallback = ref(true)

const browserModeText = computed(() => {
  const m = props.browserEnv?.mode || 'unavailable'
  const map: Record<string, string> = {
    playwright_chromium: 'Playwright 内置 Chromium',
    system_browser_fallback: '系统浏览器兜底 (Edge/Chrome)',
    custom_executable: '自定义浏览器路径',
    disabled: '已按配置禁用',
    unavailable: '未就绪'
  }
  return map[m] || m
})

function syncBrowserInputs(): void {
  const cfg = props.browserEnv?.config
  browserEnabled.value = cfg?.enabled ?? props.browserEnv?.enabled ?? true
  browserHeadless.value = cfg?.headless ?? true
  browserFallback.value = cfg?.use_system_browser_fallback ?? true
}

watch(
  () => props.visible,
  (open) => {
    if (open) {
      accountInput.value = props.authMeta?.account || ''
      passwordInput.value = ''
      autoConfirmFee.value = props.authMeta?.auto_confirm_fee ?? true
      syncBrowserInputs()
    }
  }
)

watch(
  () => props.browserEnv,
  () => {
    if (props.visible) syncBrowserInputs()
  },
  { deep: true }
)

function handleSubmit(): void {
  const pwd = passwordInput.value.trim()
  emit('save', {
    account: accountInput.value.trim(),
    password: pwd ? pwd : null,
    auto_confirm_fee: autoConfirmFee.value
  })
}

function handleRepairBrowser(): void {
  emit('repairBrowser', {
    enabled: browserEnabled.value,
    headless: browserHeadless.value,
    use_system_browser_fallback: browserFallback.value,
    auto_install: true,
    probe_launch: true
  })
}
</script>

<template>
  <div v-if="visible" class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-card">
      <div class="modal-header">
        <h3>生工官网账号与无头浏览器配置</h3>
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

        <div class="browser-env-box">
          <div class="browser-env-head">
            <div class="browser-env-title">
              <strong>无头浏览器运行环境（Playwright Chromium）</strong>
              <span class="browser-env-sub">
                {{ browserModeText }}
                <template v-if="browserEnv?.expected_version || browserEnv?.playwright_version">
                  · {{ browserEnv?.expected_version || browserEnv?.playwright_version }}
                </template>
              </span>
            </div>
            <span
              :class="[
                'env-badge',
                !browserEnv
                  ? 'muted'
                  : !browserEnv.enabled
                    ? 'muted'
                    : browserEnv.ready
                      ? 'ok'
                      : 'warn'
              ]"
            >
              {{ !browserEnv ? '未检测' : !browserEnv.enabled ? '已禁用' : browserEnv.ready ? '已就绪' : '需修复' }}
            </span>
          </div>

          <div v-if="browserEnv?.effective_browsers_path" class="file-hint">
            内核目录：{{ browserEnv.effective_browsers_path }}
          </div>

          <div class="browser-checks">
            <label class="mini-check">
              <input v-model="browserEnabled" type="checkbox" :disabled="repairingBrowser" />
              <span>启用无头浏览器自动下载与启动检查</span>
            </label>
            <label class="mini-check">
              <input v-model="browserHeadless" type="checkbox" :disabled="repairingBrowser || !browserEnabled" />
              <span>静默无头运行（取消勾选可在下载时展示浏览器窗口便于调试）</span>
            </label>
            <label class="mini-check">
              <input v-model="browserFallback" type="checkbox" :disabled="repairingBrowser || !browserEnabled" />
              <span>缺失内置内核时允许本机 Edge / Chrome 兜底</span>
            </label>
          </div>

          <ul v-if="browserEnv?.issues?.length" class="env-msg-list warn">
            <li v-for="(item, idx) in browserEnv.issues" :key="idx">{{ item.message }}</li>
          </ul>
          <ul v-if="browserEnv?.actions?.length" class="env-msg-list ok">
            <li v-for="(act, idx) in browserEnv.actions" :key="idx">{{ act }}</li>
          </ul>
          <ul v-if="browserEnv?.warnings?.length" class="env-msg-list warn">
            <li v-for="(w, idx) in browserEnv.warnings" :key="idx">{{ w }}</li>
          </ul>

          <div class="browser-env-foot">
            <button
              class="btn-mini primary"
              :disabled="busy || repairingBrowser"
              @click="handleRepairBrowser"
            >
              {{ repairingBrowser ? '检查与自修复中...' : '应用浏览器配置并检查自修复' }}
            </button>
          </div>
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
  width: 560px;
  max-width: 92vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
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
  overflow-y: auto;
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
  overflow-wrap: anywhere;
  word-break: break-word;
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
.btn-mini.primary {
  background: #eff6ff;
  color: #2563eb;
  border-color: #93c5fd;
  font-weight: 600;
}
.btn-mini:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.browser-env-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.browser-env-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.browser-env-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #1e293b;
}

.browser-env-sub {
  font-size: 11px;
  color: #64748b;
}

.env-badge {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.env-badge.ok { background: #ecfdf5; color: #047857; border: 1px solid #6ee7b7; }
.env-badge.warn { background: #fffbeb; color: #b45309; border: 1px solid #fcd34d; }
.env-badge.muted { background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; }

.browser-checks {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.mini-check {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: #334155;
  cursor: pointer;
}

.env-msg-list {
  margin: 0;
  padding: 6px 10px 6px 24px;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.45;
}
.env-msg-list.warn {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
}
.env-msg-list.ok {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
}

.browser-env-foot {
  display: flex;
  justify-content: flex-end;
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

