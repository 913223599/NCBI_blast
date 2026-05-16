
import { ref, reactive } from 'vue'
import { SequencingTech, AssemblyStage, SampleType } from '../../../modules/AssemblyCoordinator/index'
import { getBridge } from '../../../bridge'

/**
 * 组装业务逻辑 Hook
 */
export function useAssembly() {
  const isRunning = ref(false)
  const currentStep = ref(0)
  const history = ref<any[]>([])
  const selectedFiles = ref<string[]>([])
  const showResults = ref(false)

  // 🔗 队列状态追踪
  const queueStatus = ref<any[]>([])
  const queuePaused = ref(false)

  const taskState = reactive({
    id: '',
    name: 'New_Assembly_Task',
    tech: SequencingTech.ILLUMINA as SequencingTech,
    sampleType: SampleType.BACTERIA as SampleType,
    selectedDatabase: 'silva',
    selectedHostDb: 'search_ncbi',
    ncbiSearchTerm: '',
    customHostPath: '',
    estimatedGenomeSize: 100000,
    targetCoverage: 300,
    highResolutionKmer: false,
    stopAfterAssembly: false,
    mergeReads: false,
    useGPU: true,
    isLysogenic: false,
    isStrictParentStrain: true,
    doPolishing: false,
    enableDeepAudit: false,
    progress: 0,
    stage: AssemblyStage.PREPROCESSING as AssemblyStage
  })

  // 1. 获取任务历史
  const fetchHistory = async () => {
    try {
      const bridge = getBridge();
      const response = await bridge.get_assembly_history();
      const rawList = response?.data || response || [];
      
      if (!Array.isArray(rawList)) {
        history.value = [];
        return;
      }

      history.value = rawList.map((item: any) => {
        let configData: any = {};
        try { 
          if(item.config) {
            configData = typeof item.config === 'string' ? JSON.parse(item.config) : item.config;
          }
        } catch(e) {}
        
        return {
          ...item,
          sampleType: item.sample_type || configData.sample_type || 'BACTERIA',
          tech: item.tech || configData.tech || 'ILLUMINA',
          name: item.name || configData.name || '未命名任务',
          created_at: item.created_at ? (item.created_at * 1000) : Date.now()
        }
      });
    } catch (err) {
      console.error('Fetch history failed:', err);
      history.value = [];
    }
  }

  const pickCustomHost = async () => {
    try {
      const paths = await getBridge().request_file_load(['fasta', 'fa', 'fna'], false);
      if (paths && paths.length > 0) {
        taskState.customHostPath = paths[0];
      }
    } catch (err) {
      console.error('Pick custom host failed:', err);
    }
  }

  // 2. 启动任务
  const startTask = async (options: { taskId?: string, reset?: boolean, forceSampleType?: string } = {}) => {
    // 允许在运行时追加队列，移除 if (isRunning.value) return;
    
    // 如果是全新任务，必须选择文件
    if (!options.taskId && selectedFiles.value.length === 0) {
      alert('请先选择或上传 Fastq 测序文件');
      return;
    }
    
    // 如果当前空闲，则重置进度面板
    if (!isRunning.value) {
      currentStep.value = 0;
      taskState.progress = 0;
      taskState.stage = AssemblyStage.PREPROCESSING;
    }
    
    isRunning.value = true;
    
    try {
      let hostDb = taskState.selectedHostDb;
      if (hostDb === 'search_ncbi') {
        hostDb = `ncbi:${taskState.ncbiSearchTerm}`;
      } else if (hostDb === 'custom') {
        hostDb = taskState.customHostPath;
      }

      const taskId = options.taskId || `AS_${Date.now()}`;
      taskState.id = taskId;
      const finalSampleType = options.forceSampleType || taskState.sampleType;

      const sortedFiles = [...selectedFiles.value].sort((a, b) => {
        const isA1 = /[_.]R?1[_.]/.test(a);
        const isB1 = /[_.]R?1[_.]/.test(b);
        if (isA1 && !isB1) return -1;
        if (!isA1 && isB1) return 1;
        return 0;
      });

      const payload = {
        task_id: taskId,
        name: taskState.name,
        sample_id: sortedFiles[0] ? sortedFiles[0].split(/[\\/]/).pop()?.split('.')[0] : 'Sample',
        sample_type: finalSampleType,
        tech: taskState.tech,
        use_gpu: taskState.useGPU,
        algorithm: 'AUTO',
        config: {
          reset: options.reset || false,
          params: {
            database: taskState.selectedDatabase,
            host_filter_db: hostDb,
            input_files: sortedFiles,
            estimated_genome_size: taskState.estimatedGenomeSize || 100000,
            target_coverage: taskState.targetCoverage || 300,
            high_res_kmer: taskState.highResolutionKmer,
            stop_after_assembly: taskState.stopAfterAssembly,
            merge_reads: taskState.mergeReads,
            host_genome: hostDb, // 支持从 host_filter_db 共享为 host_genome
            is_lysogenic: taskState.isLysogenic,
            is_strict_parent_strain: taskState.isStrictParentStrain,
            do_polishing: taskState.doPolishing,
            enable_deep_audit: taskState.enableDeepAudit
          }
        }
      };
      await getBridge().start_assembly_pipeline(payload);
      
      // 🔗 提交成功后清空文件列表，方便添加下一个任务到队列
      selectedFiles.value = [];
      
      // 自动递增任务名称，防止重名
      if (taskState.name) {
          const match = taskState.name.match(/(.*)_(\d+)$/);
          if (match && match[1] !== undefined && match[2] !== undefined) {
              const base = match[1];
              const num = parseInt(match[2]);
              taskState.name = `${base}_${num + 1}`;
          } else {
              taskState.name = `${taskState.name}_1`;
          }
      }

      // 🔗 启动后立即刷新历史列表，确保 UI 状态一致
      await fetchHistory();
    } catch (err) {
      isRunning.value = false;
      console.error('Start failed:', err);
    }
  }

  const restoreTaskToState = (task: any) => {
    let configObj: any = {};
    try {
      configObj = typeof task.config === 'string' ? JSON.parse(task.config) : task.config || {};
    } catch(e) {}
    const params = configObj.params || {};

    if (params.input_files) selectedFiles.value = params.input_files;
    
    taskState.name = task.name;
    const rawType = task.sampleType || task.sample_type || configObj.sample_type || 'BACTERIA';
    taskState.sampleType = rawType;
    taskState.tech = task.tech || configObj.tech || 'ILLUMINA';
    
    if (params.host_filter_db) {
      const db = String(params.host_filter_db);
      if (db.startsWith('ncbi:')) {
        taskState.selectedHostDb = 'search_ncbi';
        taskState.ncbiSearchTerm = db.replace('ncbi:', '');
      } else if (db && db !== 'default_ecoli') {
        taskState.selectedHostDb = 'custom';
        taskState.customHostPath = db;
      }
    }
    
    if (params.estimated_genome_size) {
      taskState.estimatedGenomeSize = params.estimated_genome_size;
    }
    if (params.target_coverage) {
      taskState.targetCoverage = params.target_coverage;
    }
    if (params.high_res_kmer !== undefined) {
      taskState.highResolutionKmer = !!params.high_res_kmer;
    }
    if (params.stop_after_assembly !== undefined) {
      taskState.stopAfterAssembly = !!params.stop_after_assembly;
    }
    if (params.merge_reads !== undefined) {
      taskState.mergeReads = !!params.merge_reads;
    }
    if (params.is_lysogenic !== undefined) {
      taskState.isLysogenic = !!params.is_lysogenic;
    }
    if (params.is_strict_parent_strain !== undefined) {
      taskState.isStrictParentStrain = !!params.is_strict_parent_strain;
    }
    if (params.do_polishing !== undefined) {
      taskState.doPolishing = !!params.do_polishing;
    }
    if (params.enable_deep_audit !== undefined) {
      taskState.enableDeepAudit = !!params.enable_deep_audit;
    }
    return rawType;
  }

  const resumeTask = (task: any) => {
    const rawType = restoreTaskToState(task);
    startTask({ taskId: task.id, reset: false, forceSampleType: rawType });
  };

  const restartTask = (task: any) => {
    if (!confirm('确定要清除所有进度并从头开始运行吗？')) return;
    const rawType = restoreTaskToState(task);
    startTask({ taskId: task.id, reset: true, forceSampleType: rawType });
  };

  const stopTask = async (taskId: string) => {
    try {
      await getBridge().stop_assembly_task(taskId);
    } catch (err) {
      console.error('Stop failed:', err);
    }
  }

  const deleteTask = async (taskId: string) => {
    try {
      await getBridge().delete_assembly_task(taskId);
      await fetchHistory();
    } catch (err) {
      console.error('Delete failed:', err);
    }
  }

  // 🔗 队列状态更新 (由 WebSocket 事件驱动)
  const updateQueueStatus = (data: any) => {
    if (data.queue) queueStatus.value = data.queue
    if (data.paused !== undefined) queuePaused.value = data.paused
  }

  // 🔗 将等待队列重排序请求发送到后端
  const reorderQueue = async (taskIds: string[]) => {
    try {
      await getBridge().reorder_assembly_queue(taskIds)
      // 请求重新获取一下队列状态（虽然广播也会推过来）
    } catch (err) {
      console.error('Reorder queue failed:', err)
    }
  }

  // 🔗 批量提交：将多组 [R1, R2] 文件一次性提交到队列
  const submitBatch = async (fileGroups: string[][], options: any = {}) => {
    if (fileGroups.length === 0) return
    try {
      const payload = {
        file_groups: fileGroups,
        sample_type: options.sampleType || taskState.sampleType,
        tech: options.tech || taskState.tech,
        name_prefix: options.namePrefix || taskState.name,
        config: {
          params: {
            database: taskState.selectedDatabase,
            host_filter_db: taskState.selectedHostDb === 'search_ncbi'
              ? `ncbi:${taskState.ncbiSearchTerm}`
              : taskState.selectedHostDb === 'custom'
                ? taskState.customHostPath
                : taskState.selectedHostDb,
            estimated_genome_size: taskState.estimatedGenomeSize,
            target_coverage: taskState.targetCoverage,
            high_res_kmer: taskState.highResolutionKmer,
            stop_after_assembly: taskState.stopAfterAssembly,
            host_genome: taskState.selectedHostDb === 'search_ncbi'
              ? `ncbi:${taskState.ncbiSearchTerm}`
              : taskState.selectedHostDb === 'custom'
                ? taskState.customHostPath
                : taskState.selectedHostDb,
            is_lysogenic: taskState.isLysogenic,
            is_strict_parent_strain: taskState.isStrictParentStrain,
            do_polishing: taskState.doPolishing,
            enable_deep_audit: taskState.enableDeepAudit
          }
        }
      }
      await getBridge().submit_assembly_batch(payload)
      await fetchHistory()
    } catch (err) {
      console.error('Batch submit failed:', err)
    }
  }

  return {
    taskState, isRunning, currentStep, history, selectedFiles, showResults,
    queueStatus, queuePaused,
    fetchHistory: fetchHistory as () => Promise<void>,
    pickCustomHost: pickCustomHost as () => Promise<void>,
    startTask: startTask as (opt?: any) => Promise<void>,
    resumeTask: resumeTask as (task: any) => void,
    restartTask: restartTask as (task: any) => void,
    stopTask: stopTask as (id: string) => Promise<void>,
    deleteTask: deleteTask as (id: string) => Promise<void>,
    updateQueueStatus,
    reorderQueue,
    submitBatch
  }
}
