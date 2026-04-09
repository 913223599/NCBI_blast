import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getBridge } from '../bridge/pyqt-bridge'

export interface SequenceRecord {
  id: string
  sampleId: string
  sampleCode: string
  seqType: string  // 16S, WGS, etc.
  title: string
  sequence: string
  seqLen: number
  metadata: Record<string, any>
  addedAt: string
}

export const useSequenceStore = defineStore('sequence', () => {
  const activeSequences = ref<SequenceRecord[]>([])

  async function saveSequence(seq: Omit<SequenceRecord, 'id' | 'addedAt'>) {
    const newSeq: SequenceRecord = {
      ...seq,
      id: `seq_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      addedAt: new Date().toISOString()
    }
    
    try {
      const bridge = getBridge()
      const success = bridge.db_save_sequence(JSON.stringify(newSeq))
      return success
    } catch (e) {
      console.error('Failed to save sequence to DB', e)
      return false
    }
  }

  async function loadSequencesBySample(sampleId: string) {
    try {
      const bridge = getBridge()
      const jsonStr = bridge.db_load_sequences_by_sample(sampleId)
      activeSequences.value = JSON.parse(jsonStr)
      return activeSequences.value
    } catch (e) {
      console.error('Failed to load sequences', e)
      return []
    }
  }

  async function searchSequences(keyword: string) {
    try {
      const bridge = getBridge()
      const jsonStr = bridge.db_search_sequences(keyword)
      return JSON.parse(jsonStr) as SequenceRecord[]
    } catch (e) {
      console.error('Failed to search sequences', e)
      return []
    }
  }

  async function deleteSequence(id: string) {
    try {
      const bridge = getBridge()
      const success = bridge.db_delete_sequence(id)
      return success
    } catch (e) {
      console.error('Failed to delete sequence', e)
      return false
    }
  }

  return {
    activeSequences,
    saveSequence,
    loadSequencesBySample,
    searchSequences,
    deleteSequence
  }
})
