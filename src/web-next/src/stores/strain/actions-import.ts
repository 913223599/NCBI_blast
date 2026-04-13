import type { ImportTask } from './types'

export function useImportActions(state: any) {
  const { files, importTasks, activeTaskId, inputMode, importText } = state

  function addFile(file: string) {
    if (!files.value.includes(file)) {
      files.value.push(file)
    }
  }

  function addFiles(newFiles: string[]) {
    newFiles.forEach(f => addFile(f))
  }

  function removeFile(file: string) {
    files.value = files.value.filter((f: string) => f !== file)
  }

  function clearFiles() {
    files.value = []
  }

  function addTask(task: ImportTask) {
    importTasks.value = [task, ...importTasks.value]
    activeTaskId.value = task.taskId
  }

  function updateTaskStatus(taskId: string, updates: Partial<ImportTask>) {
    importTasks.value = importTasks.value.map((t: ImportTask) => 
      t.taskId === taskId ? { ...t, ...updates } : t
    )
  }

  function removeTask(taskId: string) {
    importTasks.value = importTasks.value.filter((t: ImportTask) => t.taskId !== taskId)
    if (activeTaskId.value === taskId) {
      activeTaskId.value = importTasks.value[0]?.taskId || null
    }
  }

  function switchInputMode(mode: 'file' | 'text' | 'ncbi') {
    inputMode.value = mode
  }

  function clearImportInput() {
    importText.value = ''
  }

  return {
    addFile,
    addFiles,
    removeFile,
    clearFiles,
    addTask,
    updateTaskStatus,
    removeTask,
    clearTasks() {
      importTasks.value = []
    },
    switchInputMode,
    clearImportInput
  }
}
