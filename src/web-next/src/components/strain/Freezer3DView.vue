<template>
  <div class="view-3d-container">
    <!-- 3D 画布 -->
    <div ref="canvasContainer" class="canvas-container"></div>

    <!-- 3D 控制面板 -->
    <div class="controls-panel">
      <div class="control-group">
        <label>旋转速度</label>
        <input
          v-model.number="rotationSpeed"
          type="range"
          min="0"
          max="100"
          class="slider"
        />
      </div>
      <div class="control-group">
        <label>缩放级别</label>
        <input
          v-model.number="zoomLevel"
          type="range"
          min="50"
          max="200"
          class="slider"
        />
      </div>
      <div class="control-buttons">
        <button class="ctrl-btn" @click="resetView">🔄 重置视图</button>
        <button class="ctrl-btn" @click="toggleAutoRotate">
          {{ autoRotate ? '⏸ 停止旋转' : '▶ 自动旋转' }}
        </button>
      </div>
    </div>

    <!-- 选中位置信息 -->
    <div v-if="selectedPosition" class="position-info">
      <div class="info-header">
        <h4>📍 选中位置</h4>
        <button class="close-info-btn" @click="selectedPosition = null">✕</button>
      </div>
      <div class="info-content">
        <div class="info-row">
          <span class="label">位置：</span>
          <span class="value">{{ selectedPosition.path }}</span>
        </div>
        <div class="info-row">
          <span class="label">状态：</span>
          <span class="value" :class="selectedPosition.occupied ? 'occupied' : 'free'">
            {{ selectedPosition.occupied ? '已占用' : '空闲' }}
          </span>
        </div>
        <div v-if="selectedPosition.occupied && selectedPosition.sample" class="info-row">
          <span class="label">样本：</span>
          <span class="value">{{ selectedPosition.sample.name }}</span>
        </div>
      </div>
      <div class="info-actions">
        <button
          v-if="!selectedPosition.occupied"
          class="action-btn primary"
          @click="handleAddSample"
        >
          ➕ 录入样本
        </button>
        <button
          v-else
          class="action-btn"
          @click="handleViewSample"
        >
          👁️ 查看详情
        </button>
      </div>
    </div>

    <!-- 加载提示 -->
    <div v-if="loading" class="loading-overlay">
      <div class="loading-spinner"></div>
      <p>正在加载 3D 视图...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { StrainRecord } from '../../stores/strain'

const strain = useStrainStore()
const appStore = useAppStore()
const emit = defineEmits(['addSample', 'viewSample'])

const canvasContainer = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const autoRotate = ref(true)
const rotationSpeed = ref(30)
const zoomLevel = ref(100)
const selectedPosition = ref<{
  path: string
  occupied: boolean
  sample?: StrainRecord
  positionData?: any
} | null>(null)

// Three.js 相关变量
let scene: any = null
let camera: any = null
let renderer: any = null
let controls: any = null
let animationId: number | null = null
let raycaster: any = null
let mouse: any = null
let clickableObjects: any[] = []

async function initThreeJS() {
  try {
    // 动态导入 Three.js
    const THREE = await import('three')
    const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')

    loading.value = true

    // 场景
    scene = new THREE.Scene()
    scene.background = new THREE.Color(0xf8fafc)

    // 相机
    camera = new THREE.PerspectiveCamera(
      60,
      canvasContainer.value!.clientWidth / canvasContainer.value!.clientHeight,
      0.1,
      1000
    )
    camera.position.set(10, 8, 10)

    // 渲染器
    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(canvasContainer.value!.clientWidth, canvasContainer.value!.clientHeight)
    renderer.setPixelRatio(window.devicePixelRatio)
    canvasContainer.value!.appendChild(renderer.domElement)

    // 控制器
    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.05
    controls.autoRotate = autoRotate.value
    controls.autoRotateSpeed = rotationSpeed.value / 10

    // 灯光
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6)
    scene.add(ambientLight)

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8)
    directionalLight.position.set(10, 10, 10)
    scene.add(directionalLight)

    // 创建冰箱 3D 模型
    createFreezerModel(THREE)

    // 射线检测（用于点击检测）
    raycaster = new THREE.Raycaster()
    mouse = new THREE.Vector2()

    // 事件监听
    renderer.domElement.addEventListener('click', handleCanvasClick)
    window.addEventListener('resize', handleResize)

    loading.value = false
    animate()
  } catch (error) {
    console.error('Failed to load Three.js:', error)
    appStore.showNotification('3D 视图加载失败，请检查网络连接', 'error')
    loading.value = false
  }
}

function createFreezerModel(THREE: any) {
  if (!strain.activeFreezer) return

  const freezer = strain.activeFreezer
  let yOffset = 0

  // 遍历层创建模型
  freezer.shelves.forEach((shelf: any, shelfIndex: number) => {
    shelf.cabinets.forEach((cabinet: any, cabinetIndex: number) => {
      cabinet.drawers.forEach((drawer: any, drawerIndex: number) => {
        drawer.boxes.forEach((box: any, boxIndex: number) => {
          // 创建冻存盒
          const boxGeometry = new THREE.BoxGeometry(1.5, 0.3, 1.5)
          const boxMaterial = new THREE.MeshPhongMaterial({
            color: 0x94a3b8,
            transparent: true,
            opacity: 0.8
          })
          const boxMesh = new THREE.Mesh(boxGeometry, boxMaterial)

          // 位置计算
          const xOffset = cabinetIndex * 2 + boxIndex * 0.5
          const zOffset = drawerIndex * 0.5
          boxMesh.position.set(xOffset, yOffset + shelfIndex * 2.5, zOffset)

          // 存储位置信息
          boxMesh.userData = {
            type: 'box',
            freezerId: freezer.id,
            shelfId: shelf.id,
            cabinetId: cabinet.id,
            drawerId: drawer.id,
            boxId: box.id,
            path: `${freezer.name} > ${shelf.name} > ${cabinet.name} > ${drawer.name} > ${box.name}`
          }

          scene.add(boxMesh)
          clickableObjects.push(boxMesh)

          // 创建存储位网格
          box.positions.forEach((pos: any, posIndex: number) => {
            const posSize = 0.12
            const cols = box.cols
            const row = Math.floor(posIndex / cols)
            const col = posIndex % cols

            const posGeometry = new THREE.BoxGeometry(posSize, 0.05, posSize)
            const posMaterial = new THREE.MeshPhongMaterial({
              color: pos.occupied ? 0xef4444 : 0x10b981,
              emissive: pos.occupied ? 0x7f1d1d : 0x065f46,
              emissiveIntensity: 0.2
            })
            const posMesh = new THREE.Mesh(posGeometry, posMaterial)

            const posX = xOffset + (col - box.cols / 2) * 0.15
            const posZ = zOffset + (row - box.rows / 2) * 0.15
            posMesh.position.set(posX, yOffset + shelfIndex * 2.5 + 0.2, posZ)

            // 存储位置信息
            posMesh.userData = {
              type: 'position',
              freezerId: freezer.id,
              shelfId: shelf.id,
              cabinetId: cabinet.id,
              drawerId: drawer.id,
              boxId: box.id,
              position: pos.label,
              occupied: pos.occupied,
              sampleId: pos.sampleId,
              path: `${freezer.name} > ${shelf.name} > ${cabinet.name} > ${drawer.name} > ${box.name} > ${pos.label}`
            }

            scene.add(posMesh)
            clickableObjects.push(posMesh)
          })
        })
      })
    })
  })
}

function handleCanvasClick(event: MouseEvent) {
  if (!canvasContainer.value) return

  const rect = canvasContainer.value.getBoundingClientRect()
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1

  raycaster.setFromCamera(mouse, camera)
  const intersects = raycaster.intersectObjects(clickableObjects)

  if (intersects.length > 0) {
    const object = intersects[0].object
    const data = object.userData

    if (data.type === 'position') {
      const sample = data.sampleId
        ? strain.records.find(r => r.id === data.sampleId)
        : null

      selectedPosition.value = {
        path: data.path,
        occupied: data.occupied,
        sample: sample || undefined
      }

      // 高亮选中的位置
      clickableObjects.forEach(obj => {
        if (obj.userData.type === 'position') {
          obj.material.emissiveIntensity = 0.2
        }
      })
      object.material.emissiveIntensity = 0.8
    }
  }
}

function handleResize() {
  if (!canvasContainer.value || !camera || !renderer) return

  camera.aspect = canvasContainer.value.clientWidth / canvasContainer.value.clientHeight
  camera.updateProjectionMatrix()
  renderer.setSize(canvasContainer.value.clientWidth, canvasContainer.value.clientHeight)
}

function animate() {
  animationId = requestAnimationFrame(animate)

  if (controls) {
    controls.autoRotate = autoRotate.value
    controls.autoRotateSpeed = rotationSpeed.value / 10
    controls.update()
  }

  if (renderer && scene && camera) {
    renderer.render(scene, camera)
  }
}

function resetView() {
  if (camera && controls) {
    camera.position.set(10, 8, 10)
    controls.target.set(0, 0, 0)
    controls.update()
  }
}

function toggleAutoRotate() {
  autoRotate.value = !autoRotate.value
}

function handleAddSample() {
  if (!selectedPosition.value) return
  emit('addSample', selectedPosition.value)
}

function handleViewSample() {
  if (!selectedPosition.value?.sample) return
  emit('viewSample', selectedPosition.value.sample)
}

watch(zoomLevel, (newVal) => {
  if (camera) {
    const distance = 20 - (newVal / 200) * 10
    camera.position.set(distance, distance * 0.8, distance)
  }
})

onMounted(() => {
  initThreeJS()
})

onUnmounted(() => {
  if (animationId) {
    cancelAnimationFrame(animationId)
  }
  if (renderer) {
    renderer.dispose()
  }
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.view-3d-container {
  position: relative;
  width: 100%;
  height: 100%;
  background: #f8fafc;
}

.canvas-container {
  width: 100%;
  height: 100%;
}

/* 控制面板 */
.controls-panel {
  position: absolute;
  top: 20px;
  right: 20px;
  background: #ffffff;
  border-radius: 12px;
  padding: 16px;
  min-width: 200px;
}

.control-group {
  margin-bottom: 12px;
}

.control-group label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 6px;
}

.slider {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #e2e8f0;
  outline: none;
  -webkit-appearance: none;
}

.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
}

.control-buttons {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ctrl-btn {
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.ctrl-btn:hover {
  background: #e2e8f0;
}

/* 位置信息面板 */
.position-info {
  position: absolute;
  bottom: 20px;
  left: 20px;
  background: #ffffff;
  border-radius: 12px;
  padding: 16px;
  min-width: 250px;
  max-width: 300px;
}

.info-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.info-header h4 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
}

.close-info-btn {
  background: none;
  border: none;
  font-size: 1.2rem;
  color: #94a3b8;
  cursor: pointer;
}

.info-content {
  margin-bottom: 12px;
}

.info-row {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 0.8rem;
}

.info-row .label {
  color: #64748b;
  font-weight: 600;
  flex-shrink: 0;
}

.info-row .value {
  color: #1e293b;
  word-break: break-word;
}

.info-row .value.occupied {
  color: #ef4444;
  font-weight: 700;
}

.info-row .value.free {
  color: #10b981;
  font-weight: 700;
}

.info-actions {
  display: flex;
  gap: 8px;
}

.action-btn {
  flex: 1;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.action-btn.primary {
  background: #2563eb;
  color: white;
  border: none;
}

.action-btn.primary:hover {
  background: #1d4ed8;
}

.action-btn:not(.primary) {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #475569;
}

.action-btn:not(.primary):hover {
  background: #e2e8f0;
}

/* 加载提示 */
.loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(248, 250, 252, 0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e2e8f0;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-overlay p {
  font-size: 0.9rem;
  color: #64748b;
}
</style>