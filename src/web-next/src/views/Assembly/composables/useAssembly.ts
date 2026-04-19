
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

  const taskState = reactive({
    id: '',
    name: 'New_Assembly_Task',
    tech: SequencingTech.ILLUMINA as SequencingTech,
    sampleType: SampleType.BACTERIA as SampleType,
    selectedDatabase: 'silva',
    selectedHostDb: 'search_ncbi',
    ncbiSearchTerm: '',
    customHostPath: '',
    useGPU: true,
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
    if (isRunning.value) return;
    
    // 如果是全新任务，必须选择文件
    if (!options.taskId && selectedFiles.value.length === 0) {
      alert('请先选择或上传 Fastq 测序文件');
      return;
    }
    
    isRunning.value = true;
    currentStep.value = 0;
    
    // 💡 彻底重置瞬时进度状态，防止 UI 残留历史数据
    taskState.progress = 0;
    taskState.stage = AssemblyStage.PREPROCESSING;
    
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
            input_files: sortedFiles
          }
        }
      };
      await getBridge().start_assembly_pipeline(payload);
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

  return {
    taskState, isRunning, currentStep, history, selectedFiles, showResults,
    fetchHistory: fetchHistory as () => Promise<void>,
    pickCustomHost: pickCustomHost as () => Promise<void>,
    startTask: startTask as (opt?: any) => Promise<void>,
    resumeTask: resumeTask as (task: any) => void,
    restartTask: restartTask as (task: any) => void,
    stopTask: stopTask as (id: string) => Promise<void>,
    deleteTask: deleteTask as (id: string) => Promise<void>
  }
}
