import { describe, expect, it } from 'vitest'
import {
  buildManualLengthError,
  filterSourcesByKeyword,
  filterTaxonomyEntriesByKeyword,
  replacePassageDigit,
} from '../components/strain/sampleCodeHelpers'
import type { CodeLookupEntry, SourceEntry } from '../types/codeSystem'

describe('sampleCodeHelpers', () => {
  it('能大小写无关过滤来源词条与属种词条', () => {
    const sources: SourceEntry[] = [
      { code: 'BJ', name: '北京院区', isBuiltin: true, enabled: true },
      { code: 'SH', name: '上海分库', isBuiltin: true, enabled: true },
    ]
    expect(filterSourcesByKeyword(sources, '')).toHaveLength(2)
    expect(filterSourcesByKeyword(sources, 'bj').map((s) => s.code)).toEqual(['BJ'])
    expect(filterSourcesByKeyword(sources, '上海').map((s) => s.code)).toEqual(['SH'])

    const entries: CodeLookupEntry[] = [
      { code: 'AAA', level: 2, parentPath: '1', fullPath: '1AAA', name: '克雷伯菌属', latinName: 'Klebsiella', isBuiltin: true, enabled: true },
      { code: 'BBB', level: 2, parentPath: '1', fullPath: '1BBB', name: '假单胞菌属', latinName: 'Pseudomonas', isBuiltin: true, enabled: true },
    ]
    expect(filterTaxonomyEntriesByKeyword(entries, 'kleb').map((e) => e.code)).toEqual(['AAA'])
    expect(filterTaxonomyEntriesByKeyword(entries, '假单').map((e) => e.code)).toEqual(['BBB'])
  })

  it('能精准替换14位编码中的第10位传代字符而不破坏流水号与非14位输入', () => {
    expect(replacePassageDigit('011AAABBB00042', 3)).toBe('011AAABBB30042')
    expect(replacePassageDigit('SHORT', 2)).toBe('SHORT')
    expect(buildManualLengthError(0)).toEqual([])
    expect(buildManualLengthError(8)).toEqual(['已输入8位，需14位'])
  })
})
