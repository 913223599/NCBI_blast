import { beforeEach } from 'vitest'
import { config } from '@vue/test-utils'
import { createPinia, getActivePinia, setActivePinia } from 'pinia'
import type { App } from 'vue'

// 动态代理当前活跃 Pinia 实例：兼容单测内手动调用 setActivePinia(createPinia())，
// 并彻底消除所有组件挂载时的 "[Vue warn]: injection Symbol(pinia) not found" 告警。
const activePiniaPlugin = {
  install(app: App) {
    let pinia = getActivePinia()
    if (!pinia) {
      pinia = createPinia()
      setActivePinia(pinia)
    }
    pinia.install(app)
  },
}

beforeEach(() => {
  const pinia = createPinia()
  setActivePinia(pinia)
  config.global.plugins = [activePiniaPlugin]
})
