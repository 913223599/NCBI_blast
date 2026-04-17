<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getBridge } from '../../bridge'
import { useAppStore } from '../../stores/app'

const appStore = useAppStore()
const lanEnabled = ref(false)
const lanShareInfo = ref<any>(null)

async function loadLanShareInfo() {
  const result = await getBridge().get_lan_share_info()
  if (result) {
    lanEnabled.value = result.enabled
    lanShareInfo.value = result
  }
}

async function saveLanSettings() {
  const result = await getBridge().save_lan_share_settings(lanEnabled.value)
  if (result.success) appStore.showNotification('系统参数已同步保存', 'success')
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    appStore.showNotification('访问链接已复制', 'success')
  })
}

onMounted(() => loadLanShareInfo())
</script>

<template>
  <div class="panel">
    <header class="panel-header">
      <h2>⚙️ 系统参数 & 环境配置</h2>
      <p class="desc">控制应用的运行环境、存储路径以及局域网内的设备协同设置。</p>
    </header>

    <div class="p-card">
      <h3>🌐 局域网服务共享</h3>
      <p class="desc-sm">开启后，同一网络下的其他终端可通过浏览器直接访问并参与当前的分析工作流。</p>
      
      <div class="lan-control-row">
        <label class="p-toggle">
           <span class="label">启用局域网共享服务</span>
           <div class="toggle-container">
             <input type="checkbox" v-model="lanEnabled">
             <span class="p-slider"></span>
           </div>
        </label>
      </div>

      <div v-if="lanEnabled && lanShareInfo" class="lan-details mt-24">
        <div class="detail-item">
          <label>当前专用访问地址</label>
          <div class="url-box">
            <code>http://{{ lanShareInfo.ip }}:{{ lanShareInfo.port }}</code>
            <button class="p-btn p-btn-primary btn-sm" @click="copyToClipboard(`http://${lanShareInfo.ip}:${lanShareInfo.port}`)">复制</button>
          </div>
        </div>
      </div>

      <div class="footer-actions mt-24" style="text-align: right;">
        <button class="p-btn p-btn-primary" @click="saveLanSettings">💾 应用系统更改</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lan-control-row {
  background: #f8fafc;
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}

.p-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
}
.p-toggle .label { font-weight: 700; color: #334155; }

.toggle-container {
  position: relative;
  display: inline-block;
  width: 50px;
  height: 26px;
}
.toggle-container input { opacity: 0; width: 0; height: 0; }
.p-slider {
  position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
  background-color: #cbd5e1; transition: .4s; border-radius: 34px;
}
.p-slider:before {
  position: absolute; content: ""; height: 20px; width: 20px; left: 3px; bottom: 3px;
  background-color: white; transition: .4s; border-radius: 50%;
}
input:checked + .p-slider { background-color: #3b82f6; }
input:checked + .p-slider:before { transform: translateX(24px); }

.detail-item label { font-size: 0.75rem; color: #94a3b8; font-weight: 700; margin-bottom: 8px; display: block; }
.url-box { display: flex; gap: 8px; }
.url-box code { 
  flex: 1; background: #fff; padding: 10px 14px; border: 1px solid #e2e8f0; 
  border-radius: 8px; font-family: monospace; color: #2563eb; font-weight: 700;
}
.btn-sm { height: 38px; }
.mt-24 { margin-top: 24px; }
</style>
