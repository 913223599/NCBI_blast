import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getBridge } from '../bridge'

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
    
    return new Promise<boolean>((resolve) => {
      try {
        const bridge = getBridge()
        if (bridge && bridge.db_save_sequence) {
          bridge.db_save_sequence(JSON.stringify(newSeq), (success: boolean) => {
            resolve(success)
          })
        } else {
          resolve(false)
        }
      } catch (e) {
        console.error('Failed to save sequence to DB', e)
        resolve(false)
      }
    })
  }

  async function loadSequencesBySample(sampleId: string) {
    return new Promise<SequenceRecord[]>((resolve) => {
      try {
        const bridge = getBridge()
        if (bridge && bridge.db_load_sequences_by_sample) {
          bridge.db_load_sequences_by_sample(sampleId, (jsonStr: string) => {
            try {
              const data = JSON.parse(jsonStr)
              activeSequences.value = data
              resolve(data)
            } catch (err) {
              resolve([])
            }
          })
        } else {
          resolve([])
        }
      } catch (e) {
        console.error('Failed to load sequences', e)
        resolve([])
      }
    })
  }

  async function searchSequences(keyword: string) {
    return new Promise<SequenceRecord[]>((resolve) => {
      try {
        const bridge = getBridge()
        if (bridge && bridge.db_search_sequences) {
          bridge.db_search_sequences(keyword, (jsonStr: string) => {
            try {
              resolve(JSON.parse(jsonStr) as SequenceRecord[])
            } catch (err) {
              resolve([])
            }
          })
        } else {
          resolve([])
        }
      } catch (e) {
        console.error('Failed to search sequences', e)
        resolve([])
      }
    })
  }

  async function deleteSequence(id: string) {
    return new Promise<boolean>((resolve) => {
      try {
        const bridge = getBridge()
        if (bridge && bridge.db_delete_sequence) {
          bridge.db_delete_sequence(id, (success: boolean) => {
            resolve(success)
          })
        } else {
          resolve(false)
        }
      } catch (e) {
        console.error('Failed to delete sequence', e)
        resolve(false)
      }
    })
  }

  return {
    activeSequences,
    saveSequence,
    loadSequencesBySample,
    searchSequences,
    deleteSequence
  }
})
