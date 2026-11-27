/**
 * SampleCodeInput 纯逻辑辅助函数与强类型载荷定义
 */
import type {
  CodeGenerationRequest,
  CodeLookupEntry,
  SourceEntry,
} from '../../types/codeSystem'

export interface SampleCodeUpdatePayload {
  sampleCode: string
  codeSource: string
  codeCategory: string
  codeGenus: string
  codeSpecies: string
  codePassage: number
  codeSerial: number
  generationRequest?: CodeGenerationRequest | null
}

export function filterSourcesByKeyword(sources: SourceEntry[], rawKeyword: string): SourceEntry[] {
  const keyword = rawKeyword.toLowerCase()
  if (!keyword) return sources
  return sources.filter(
    (entry) =>
      entry.code.toLowerCase().includes(keyword) ||
      entry.name.toLowerCase().includes(keyword)
  )
}

export function filterTaxonomyEntriesByKeyword(
  entries: CodeLookupEntry[],
  rawKeyword: string
): CodeLookupEntry[] {
  const keyword = rawKeyword.toLowerCase()
  if (!keyword) return entries
  return entries.filter(
    (entry) =>
      entry.name.toLowerCase().includes(keyword) ||
      (entry.latinName?.toLowerCase().includes(keyword) ?? false)
  )
}

export function replacePassageDigit(baseCode: string, passage: number): string {
  if (baseCode.length !== 14) return baseCode
  return baseCode.substring(0, 9) + String(passage) + baseCode.substring(10)
}

export function buildManualLengthError(codeLength: number): string[] {
  return codeLength > 0 ? [`已输入${codeLength}位，需14位`] : []
}
