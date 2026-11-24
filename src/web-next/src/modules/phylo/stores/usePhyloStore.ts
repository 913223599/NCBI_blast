import { computed, markRaw, reactive, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { useAppStore } from '../../../stores/app'
import { phyloApi } from '../api/phyloApi'
import { PhyloTreeModel } from '../core/TreeModel'
import type {
  AniScreenResult,
  CapabilitiesResponse,
  DeliveryScopeConfig,
  NodeMetadata,
  PhyloJobConfig,
  PhyloJobRecord,
  ReferenceCandidate,
  SequenceProfile,
  StageState,
  TreeVisualSettings,
  WorkbenchMode,
  WorkspaceFileItem,
} from '../types/phylo'

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export const usePhyloStore = defineStore('phylo', () => {
  const appStore = useAppStore()

  // 工作台模式：噬菌体 8 步分类科研流 vs 通用系统发育树
  const workbenchMode = ref<WorkbenchMode>('phage_taxonomy')

  // 系统能力与工具状态
  const capabilities = ref<CapabilitiesResponse | null>(null)
  const isProbingCaps = ref(false)

  // 工作区与序列画像
  const workspaceFiles = ref<WorkspaceFileItem[]>([])
  const profile = ref<SequenceProfile | null>(null)
  const isImporting = ref(false)

  // 第 0-2 步：噬菌体交付边界、ANI 预判与参考集策展
  const phageScope = reactive<DeliveryScopeConfig>({
    target_rank: 'genus',
    ani_species_threshold: 95.0,
    ani_genus_threshold: 70.0,
    ref_max_count: 80,
    derep_ani: 0.9,
    derep_min_len: 20000,
    treemmer_target: 80,
    treemmer_min_cluster: 25,
    checkv_min_completeness: 95.0,
    enable_checkv: false,
    local_ref_dir: null,
    outgroup_ids: [],
    mash_top_k: 40,
  })
  const aniResult = ref<AniScreenResult | null>(null)
  const referenceCandidates = ref<ReferenceCandidate[]>([])
  const isScreeningAni = ref(false)
  const isCuratingRefs = ref(false)

  // 分析配置
  const config = reactive<PhyloJobConfig>({
    title: '',
    track: 'auto',
    msa: 'mafft',
    msa_strategy: 'linsi',
    trim_mode: 'kpic',
    trim_gap_threshold: null,
    engine: 'iqtree',
    model: 'MFP',
    bootstrap: 1000,
    iqtree_bnni: true,
    iqtree_alrt: 1000,
    iqtree_seed: 42,
    outgroup_ids: [],
    threads: 0,
    use_gpu: true,
    mash_kmer: 21,
    mash_sketch: 1000,
    mrbayes_ngen: 10000,
    midpoint_root: true,
    use_cache: true,
    phage_scope: null,
    marker_mode: 'terl',
    ani_engine: 'viridic_blastn',
    selected_references: [],
  })

  // 活跃任务与实时日志
  const activeJob = ref<PhyloJobRecord | null>(null)
  const liveLogs = ref<string[]>([])
  const isCancelling = ref(false)
  const isSubmitting = ref(false)

  // 历史记录与当前展示树
  const historyJobs = ref<PhyloJobRecord[]>([])
  const currentJob = ref<PhyloJobRecord | null>(null)
  const rawNewick = ref<string>('')
  const originalNewick = ref<string>('')
  const treeModel = shallowRef<PhyloTreeModel>(markRaw(new PhyloTreeModel()))
  const treeRevision = ref(0)

  const visual = reactive<TreeVisualSettings>({
    layout: 'rect',
    useBranchLengths: true,
    showLabels: true,
    labelFormat: 'name_acc',
    showSupport: true,
    supportThreshold: 50,
    fontSize: 13,
    rowSpacing: 26,
    sortMode: 'original',
    searchQuery: '',
    showMetadataStrips: true,
    highlightStrongUfboot: true,
  })

  let unsubscribeEvents: (() => void) | null = null
  const terminatedJobIds = new Set<string>()

  const effectiveTrack = computed<'genome' | 'gene' | 'phage_taxonomy'>(() => {
    if (workbenchMode.value === 'phage_taxonomy') return 'phage_taxonomy'
    if (config.track === 'genome' || config.track === 'gene') return config.track
    return profile.value?.recommended_track || 'gene'
  })

  const isRunning = computed(() => {
    return (
      activeJob.value !== null &&
      (activeJob.value.status === 'running' || activeJob.value.status === 'pending')
    )
  })

  const hasTree = computed(() => Boolean(rawNewick.value && treeModel.value.root))

  function applyRecommendedDefaults(prof: SequenceProfile | null): void {
    if (!prof || prof.sequence_count === 0) return
    if (workbenchMode.value === 'phage_taxonomy') {
      config.msa = 'mafft'
      config.msa_strategy = 'linsi'
      config.trim_mode = 'kpic'
      config.engine = capabilities.value?.engines.iqtree?.available ? 'iqtree' : 'fasttree'
      config.model = 'MFP'
      config.bootstrap = 1000
      config.iqtree_bnni = true
      config.iqtree_alrt = 1000
      return
    }
    if (prof.recommended_track === 'genome') {
      config.track = 'auto'
      config.msa = 'none'
      config.engine = 'bionj'
      config.model = 'jc69'
    } else {
      config.track = 'auto'
      config.msa = prof.recommended_msa
      const eng = prof.recommended_engine
      if (capabilities.value?.engines[eng]?.available) {
        config.engine = eng
      } else {
        config.engine = 'bionj'
      }
      if (prof.mol_type === 'protein') {
        config.model =
          config.engine === 'iqtree' ? 'JTT+G' : config.engine === 'fasttree' ? 'jtt' : 'poisson'
      } else {
        config.model =
          config.engine === 'iqtree' ? 'MFP' : config.engine === 'fasttree' ? 'gtr' : 'jc69'
      }
    }
  }

  function mergeNodeMetadata(
    prevMap?: Record<string, NodeMetadata>,
    nextMap?: Record<string, NodeMetadata>
  ): Record<string, NodeMetadata> | undefined {
    if (!prevMap && !nextMap) return undefined
    const merged: Record<string, NodeMetadata> = {}
    for (const [k, v] of Object.entries(prevMap || {})) {
      merged[k] = { ...v }
    }
    for (const [k, v] of Object.entries(nextMap || {})) {
      const cur = merged[k] || {}
      merged[k] = {
        ...cur,
        ...v,
        description: v.description || cur.description,
        genus: v.genus || cur.genus,
        family: v.family || cur.family,
        host: v.host || cur.host,
      }
    }
    return merged
  }

  function loadNewickIntoViewer(
    newick: string,
    job: PhyloJobRecord | null = null,
    preserveOriginal = false
  ): void {
    const model = new PhyloTreeModel()
    const root = model.parse(newick)
    if (!root) {
      appStore.showNotification('Newick 格式解析失败', 'error')
      return
    }
    const prevSameJobMeta =
      job && currentJob.value?.job_id === job.job_id ? currentJob.value.node_metadata : undefined
    const effectiveMeta = mergeNodeMetadata(prevSameJobMeta, job?.node_metadata)
    if (job && effectiveMeta) {
      job.node_metadata = effectiveMeta
    }
    if (effectiveMeta) {
      model.applyNodeMetadata(effectiveMeta)
    }
    if (visual.sortMode !== 'original') {
      model.applySorting(visual.sortMode)
    }
    treeModel.value = markRaw(model)
    rawNewick.value = newick
    if (!preserveOriginal || !originalNewick.value) {
      originalNewick.value = newick
    }
    if (job) {
      currentJob.value = job
      if (job.ani_result) {
        aniResult.value = job.ani_result
      }
    }
    treeRevision.value++
  }

  function applyLocalSort(): void {
    if (!treeModel.value.root) return
    treeModel.value.applySorting(visual.sortMode)
    treeRevision.value++
  }

  function toggleNodeCollapse(nodeId: string): void {
    treeModel.value.toggleCollapse(nodeId)
    treeRevision.value++
  }

  function colorClade(nodeId: string, color: string | null): void {
    treeModel.value.setCladeColor(nodeId, color)
    treeRevision.value++
  }

  async function rerootMidpoint(): Promise<void> {
    if (!treeModel.value.root) return
    if (currentJob.value) {
      try {
        const updated = await phyloApi.rerootJob(currentJob.value.job_id, 'midpoint')
        if (updated.newick) {
          loadNewickIntoViewer(updated.newick, updated, true)
          await refreshHistory()
          appStore.showNotification('已完成中点定根', 'success')
          return
        }
      } catch (e: unknown) {
        appStore.showNotification(`后端重定根失败，已切换前端本地计算: ${errMsg(e)}`, 'warning')
      }
    }
    treeModel.value.rerootMidpoint()
    rawNewick.value = treeModel.value.toNewick()
    treeRevision.value++
  }

  async function rerootOutgroup(nodeName: string): Promise<void> {
    if (!treeModel.value.root || !nodeName) return
    if (currentJob.value) {
      try {
        const updated = await phyloApi.rerootJob(currentJob.value.job_id, 'outgroup', nodeName)
        if (updated.newick) {
          loadNewickIntoViewer(updated.newick, updated, true)
          await refreshHistory()
          appStore.showNotification(`已将 [${nodeName}] 设为外群重定根`, 'success')
          return
        }
      } catch (e: unknown) {
        appStore.showNotification(`外群定根失败: ${errMsg(e)}`, 'error')
        return
      }
    }
    const target = Array.from(treeModel.value.nodesById.values()).find(
      (n) => n.isLeaf && n.name === nodeName
    )
    if (target) {
      treeModel.value.rerootOutgroup(target.id)
      rawNewick.value = treeModel.value.toNewick()
      treeRevision.value++
    }
  }

  function resetTopology(): void {
    if (originalNewick.value) {
      loadNewickIntoViewer(originalNewick.value, currentJob.value)
    }
  }

  async function refreshCapabilities(refresh = false): Promise<void> {
    isProbingCaps.value = true
    try {
      capabilities.value = await phyloApi.getCapabilities(refresh)
    } catch (e: unknown) {
      appStore.showNotification(`获取工具能力失败: ${errMsg(e)}`, 'error')
    } finally {
      isProbingCaps.value = false
    }
  }

  async function refreshWorkspace(): Promise<void> {
    try {
      const ws = await phyloApi.getWorkspace()
      workspaceFiles.value = ws.files || []
      profile.value = ws.profile || null
    } catch (e: unknown) {
      appStore.showNotification(`刷新工作区失败: ${errMsg(e)}`, 'error')
    }
  }

  async function importFiles(paths: string[]): Promise<void> {
    if (!paths.length) return
    if (paths.length === 1 && /\.(nwk|newick|tree)$/i.test(paths[0]!)) {
      const content = await window.electronAPI?.readFile(paths[0]!)
      if (content) {
        loadNewickIntoViewer(content, null)
        appStore.showNotification('已直接载入 Newick 树文件', 'success')
        return
      }
    }
    isImporting.value = true
    try {
      const ws = await phyloApi.addWorkspaceFiles(paths)
      workspaceFiles.value = ws.files || []
      profile.value = ws.profile || null
      applyRecommendedDefaults(profile.value)
      aniResult.value = null
      referenceCandidates.value = []
      appStore.showNotification('序列已导入工作区并完成特征画像', 'success')
    } catch (e: unknown) {
      appStore.showNotification(`导入失败: ${errMsg(e)}`, 'error')
    } finally {
      isImporting.value = false
    }
  }

  async function pasteSequences(content: string, filename?: string): Promise<void> {
    isImporting.value = true
    try {
      const ws = await phyloApi.pasteSequences(content, filename)
      workspaceFiles.value = ws.files || []
      profile.value = ws.profile || null
      applyRecommendedDefaults(profile.value)
      aniResult.value = null
      referenceCandidates.value = []
      appStore.showNotification('粘贴序列已保存至工作区', 'success')
    } catch (e: unknown) {
      appStore.showNotification(`保存序列失败: ${errMsg(e)}`, 'error')
    } finally {
      isImporting.value = false
    }
  }

  async function removeWorkspaceFile(filename: string): Promise<void> {
    try {
      const ws = await phyloApi.removeWorkspaceFile(filename)
      workspaceFiles.value = ws.files || []
      profile.value = ws.profile || null
    } catch (e: unknown) {
      appStore.showNotification(`移除文件失败: ${errMsg(e)}`, 'error')
    }
  }

  async function clearWorkspace(): Promise<void> {
    try {
      const ws = await phyloApi.clearWorkspace()
      workspaceFiles.value = ws.files || []
      profile.value = ws.profile || null
      aniResult.value = null
      referenceCandidates.value = []
      appStore.showNotification('工作区已清空', 'info')
    } catch (e: unknown) {
      appStore.showNotification(`清空失败: ${errMsg(e)}`, 'error')
    }
  }

  // ─── 第 1 & 2 步交互操作 ─────────────────────────────────────
  async function runPhageAniScreen(): Promise<void> {
    if (!profile.value || profile.value.sequence_count < 1) {
      appStore.showNotification('请先导入至少 1 条噬菌体基因组 FASTA', 'error')
      return
    }
    isScreeningAni.value = true
    try {
      const res = await phyloApi.phageAniScreen({
        scope: { ...phageScope },
        ani_engine: config.ani_engine,
        threads: config.threads,
      })
      aniResult.value = res
      // 同步推荐外群
      phageScope.outgroup_ids = [...(res.recommended_outgroup_accessions || [])]
      appStore.showNotification('ANI 全库初筛与 wgANI 矩阵精算完成', 'success')
      await curatePhageReferences()
    } catch (e: unknown) {
      appStore.showNotification(`ANI 预判失败: ${errMsg(e)}`, 'error')
    } finally {
      isScreeningAni.value = false
    }
  }

  async function curatePhageReferences(): Promise<void> {
    if (!profile.value || profile.value.sequence_count < 1) {
      appStore.showNotification('工作区为空，请先导入噬菌体序列', 'error')
      return
    }
    isCuratingRefs.value = true
    try {
      const list = await phyloApi.phageCurateRefs({
        ani_result: aniResult.value,
        scope: { ...phageScope },
      })
      referenceCandidates.value = list
      config.selected_references = list
    } catch (e: unknown) {
      appStore.showNotification(`参考集策展失败: ${errMsg(e)}`, 'error')
    } finally {
      isCuratingRefs.value = false
    }
  }

  function toggleReferenceSelected(accession: string): void {
    const item = referenceCandidates.value.find((r) => r.accession === accession)
    if (!item || item.role === 'query') return
    item.selected = !item.selected
  }

  function setReferenceRole(accession: string, role: ReferenceCandidate['role']): void {
    const item = referenceCandidates.value.find((r) => r.accession === accession)
    if (!item || item.role === 'query') return
    item.role = role
    if (role === 'outgroup') {
      item.selected = true
      if (!phageScope.outgroup_ids.includes(accession)) {
        phageScope.outgroup_ids.push(accession)
      }
    } else {
      phageScope.outgroup_ids = phageScope.outgroup_ids.filter((id) => id !== accession)
    }
  }

  async function refreshHistory(): Promise<void> {
    try {
      historyJobs.value = await phyloApi.listJobs(50)
    } catch {
      // 忽略首次连接抖动
    }
  }

  async function restoreActiveJob(): Promise<void> {
    try {
      const activeList = await phyloApi.listActiveJobs()
      if (activeList.length > 0) {
        const running = activeList[0]!
        activeJob.value = running
        liveLogs.value = await phyloApi.getJobLogs(running.job_id, 200)
      }
    } catch {
      // ignore
    }
  }

  async function startAnalysis(): Promise<void> {
    if (workbenchMode.value === 'phage_taxonomy') {
      await startPhageTaxonomyPipeline()
      return
    }
    if (!profile.value || profile.value.sequence_count < 3) {
      appStore.showNotification('请先导入至少 3 条有效序列', 'error')
      return
    }
    isSubmitting.value = true
    liveLogs.value = []
    try {
      const payload: PhyloJobConfig = { ...config, phage_scope: null, selected_references: [] }
      const job = await phyloApi.submitJob(payload)
      if (!terminatedJobIds.has(job.job_id)) {
        activeJob.value = job
        isCancelling.value = false
      } else {
        const latest = await phyloApi.getJob(job.job_id).catch(() => null)
        if (latest && (latest.status === 'running' || latest.status === 'pending')) {
          activeJob.value = latest
        }
      }
      appStore.showNotification(
        `分析任务已启动 (${job.resolved_track === 'genome' ? '全基因组模式' : '基因比对模式'})`,
        'info'
      )
    } catch (e: unknown) {
      appStore.showNotification(`启动失败: ${errMsg(e)}`, 'error')
    } finally {
      isSubmitting.value = false
    }
  }

  async function startPhageTaxonomyPipeline(): Promise<void> {
    if (!profile.value || profile.value.sequence_count < 1) {
      appStore.showNotification('请先导入至少 1 条待鉴定噬菌体序列', 'error')
      return
    }
    isSubmitting.value = true
    liveLogs.value = []
    try {
      const outgroups = referenceCandidates.value
        .filter((r) => r.selected && r.role === 'outgroup')
        .map((r) => r.accession)
      const payload: PhyloJobConfig = {
        ...config,
        track: 'phage_taxonomy',
        outgroup_ids: outgroups.length ? outgroups : [...phageScope.outgroup_ids],
        phage_scope: { ...phageScope, outgroup_ids: outgroups },
        selected_references: referenceCandidates.value.length
          ? referenceCandidates.value.map((r) => ({ ...r }))
          : [],
        precomputed_ani_result: aniResult.value || null,
      }
      const job = await phyloApi.submitJob(payload)
      if (!terminatedJobIds.has(job.job_id)) {
        activeJob.value = job
        isCancelling.value = false
      } else {
        const latest = await phyloApi.getJob(job.job_id).catch(() => null)
        if (latest && (latest.status === 'running' || latest.status === 'pending')) {
          activeJob.value = latest
        }
      }
      appStore.showNotification('已启动噬菌体分类鉴定 8 步科研流水线', 'info')
    } catch (e: unknown) {
      appStore.showNotification(`启动失败: ${errMsg(e)}`, 'error')
    } finally {
      isSubmitting.value = false
    }
  }

  async function cancelActiveJob(): Promise<void> {
    if (!activeJob.value) return
    isCancelling.value = true
    try {
      await phyloApi.cancelJob(activeJob.value.job_id)
      appStore.showNotification('已发送强制终止指令，正在清理计算进程...', 'warning')
    } catch (e: unknown) {
      appStore.showNotification(`取消失败: ${errMsg(e)}`, 'error')
      isCancelling.value = false
    }
  }

  async function deleteHistoryJob(jobId: string): Promise<void> {
    try {
      await phyloApi.deleteJob(jobId)
      historyJobs.value = historyJobs.value.filter((j) => j.job_id !== jobId)
      if (currentJob.value?.job_id === jobId) {
        currentJob.value = null
        rawNewick.value = ''
        treeModel.value = markRaw(new PhyloTreeModel())
        treeRevision.value++
      }
      appStore.showNotification('已删除任务记录与归档文件', 'info')
    } catch (e: unknown) {
      appStore.showNotification(`删除失败: ${errMsg(e)}`, 'error')
    }
  }

  function applyConfigFromJob(job: PhyloJobRecord): void {
    Object.assign(config, job.config)
    if (job.resolved_track === 'phage_taxonomy') {
      workbenchMode.value = 'phage_taxonomy'
      if (job.config.phage_scope) Object.assign(phageScope, job.config.phage_scope)
      if (job.ani_result) aniResult.value = job.ani_result
      if (job.config.selected_references?.length) {
        referenceCandidates.value = job.config.selected_references.map((r) => ({ ...r }))
      }
    } else {
      workbenchMode.value = 'general'
    }
    appStore.showNotification(`已载入历史任务参数: ${job.title}`, 'info')
  }

  function handlePhyloEvent(eventType: string, data: Record<string, unknown>): void {
    if (!data) return
    const jid = typeof data.job_id === 'string' ? data.job_id : ''
    if (eventType === 'phylo_log') {
      if (activeJob.value && activeJob.value.job_id === jid && data.line) {
        liveLogs.value.push(String(data.line))
        if (liveLogs.value.length > 500) liveLogs.value.shift()
      }
      return
    }
    if (eventType === 'phylo_stage') {
      if (activeJob.value && activeJob.value.job_id === jid) {
        activeJob.value = {
          ...activeJob.value,
          status: 'running',
          current_stage: String(data.stage || activeJob.value.current_stage),
          progress: Number(data.progress ?? activeJob.value.progress),
          message: String(data.message || ''),
          elapsed_sec: Number(data.elapsed_sec ?? activeJob.value.elapsed_sec),
          stages: (data.stages as StageState[]) || activeJob.value.stages,
        }
      }
      return
    }
    if (eventType === 'phylo_finished') {
      if (jid) terminatedJobIds.add(jid)
      const rec = data.record as PhyloJobRecord
      activeJob.value = null
      isCancelling.value = false
      if (rec?.newick) {
        loadNewickIntoViewer(rec.newick, rec)
      }
      refreshHistory()
      appStore.showNotification(
        `进化树构建完成 (${rec?.metrics?.leaf_count || 0} 叶节点, 耗时 ${rec?.elapsed_sec || 0}s)`,
        'success'
      )
      return
    }
    if (eventType === 'phylo_cancelled') {
      if (jid) terminatedJobIds.add(jid)
      activeJob.value = null
      isCancelling.value = false
      refreshHistory()
      appStore.showNotification('进化树分析任务已终止，相关进程已清理', 'warning')
      return
    }
    if (eventType === 'phylo_error') {
      if (jid) terminatedJobIds.add(jid)
      activeJob.value = null
      isCancelling.value = false
      refreshHistory()
      appStore.showNotification(`分析失败: ${String(data.error || '未知错误')}`, 'error')
    }
  }

  async function init(): Promise<void> {
    if (!unsubscribeEvents) {
      unsubscribeEvents = phyloApi.subscribeEvents(handlePhyloEvent)
    }
    await Promise.all([
      refreshCapabilities(false),
      refreshWorkspace(),
      refreshHistory(),
      restoreActiveJob(),
    ])
    if (!activeJob.value && profile.value && profile.value.sequence_count > 0) {
      applyRecommendedDefaults(profile.value)
    }
    if (!hasTree.value) {
      const latestCompleted = historyJobs.value.find(
        (j) => j.status === 'completed' && j.newick
      )
      if (latestCompleted && latestCompleted.newick) {
        loadNewickIntoViewer(latestCompleted.newick, latestCompleted)
      }
    }
  }

  function dispose(): void {
    if (unsubscribeEvents) {
      unsubscribeEvents()
      unsubscribeEvents = null
    }
  }

  return {
    workbenchMode,
    capabilities,
    isProbingCaps,
    workspaceFiles,
    profile,
    isImporting,
    phageScope,
    aniResult,
    referenceCandidates,
    isScreeningAni,
    isCuratingRefs,
    config,
    effectiveTrack,
    activeJob,
    liveLogs,
    isRunning,
    isCancelling,
    isSubmitting,
    historyJobs,
    currentJob,
    rawNewick,
    treeModel,
    treeRevision,
    hasTree,
    visual,
    init,
    dispose,
    refreshCapabilities,
    refreshWorkspace,
    importFiles,
    pasteSequences,
    removeWorkspaceFile,
    clearWorkspace,
    runPhageAniScreen,
    curatePhageReferences,
    toggleReferenceSelected,
    setReferenceRole,
    startAnalysis,
    startPhageTaxonomyPipeline,
    cancelActiveJob,
    refreshHistory,
    deleteHistoryJob,
    applyRecommendedDefaults,
    applyConfigFromJob,
    loadNewickIntoViewer,
    applyLocalSort,
    toggleNodeCollapse,
    colorClade,
    rerootMidpoint,
    rerootOutgroup,
    resetTopology,
  }
})
