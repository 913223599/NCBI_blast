import { ref } from 'vue'
import { useStrainStore } from '../stores/strain'
import { useAppStore } from '../stores/app'
import { getBridge } from '../bridge'

/**
 * 专门负责处理样本录入过程中的物种名称识别、编号库匹配以及后端分类同步
 */
export function useTaxonomySync() {
  const strain = useStrainStore()
  const appStore = useAppStore()

  /**
   * 尝试根据学名自动匹配编号库中的属/种编码
   */
  function attemptTaxonomicMatch(fullIdentification: string) {
    if (!fullIdentification) return null
    
    const consensusMatch = fullIdentification.trim().match(/^[\*\s]*([A-Za-z]+)\s+([A-Za-z\.\-_0-9]+)/)
    if (!consensusMatch) return null
    
    const genusPart = consensusMatch[1]
    const speciesPart = consensusMatch[2]
    
    if (!genusPart || !speciesPart) return null
    
    const selections: any = {
      category: '1', 
      source: '01',   
      passage: 0
    }

    const cleanSpecies = speciesPart.replace(/[,\(\)].*$/, '')

    try {
      const lowerGenus = genusPart.toLowerCase()
      const genusEntries = strain.codeLookupEntries.filter(
        e => e.level === 2 && 
        (e.latinName?.toLowerCase() === lowerGenus || e.name === genusPart)
      )
      
      if (genusEntries.length > 0) {
        const matchedGenus = genusEntries[0]
        selections.genus = matchedGenus.code
        selections.category = matchedGenus.parentPath 
        
        if (cleanSpecies) {
          const lowerSpecies = cleanSpecies.toLowerCase()
          const parentPath = matchedGenus.fullPath
          const speciesEntries = strain.codeLookupEntries.filter(
            e => e.level === 3 && 
            e.parentPath === parentPath &&
            (e.latinName?.toLowerCase() === lowerSpecies || e.name === cleanSpecies)
          )
          if (speciesEntries.length > 0) {
            const matchedSpecies = speciesEntries[0]
            selections.species = matchedSpecies.code
          }
        }
      }
      
      return {
        selections: selections.genus ? selections : null,
        consensus: `${genusPart} ${cleanSpecies}`.trim()
      }
    } catch (e) {
      console.warn('[TaxonomySync] Match failed:', e)
      return null
    }
  }

  /**
   * 执行后端分类数据库同步
   */
  async function syncTaxonomyToBackend(queryName: string) {
    return new Promise((resolve) => {
      getBridge().sync_taxonomy?.(queryName, (res: any) => {
        if (res && res.success) {
          strain.initFromDatabase()
          resolve(res)
        } else {
          resolve(null)
        }
      })
    })
  }

  return {
    attemptTaxonomicMatch,
    syncTaxonomyToBackend
  }
}
