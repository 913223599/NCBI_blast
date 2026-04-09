import type { SampleCategory, StrainRecord } from '../stores/strain'

/**
 * 模拟完整的样本业务数据
 */
export const MOCK_SAMPLES: Partial<StrainRecord>[] = [
  {
    name: 'Escherichia coli K-12 MG1655',
    sampleType: 'Bacteria' as SampleCategory,
    species: 'Escherichia coli',
    accession: 'NC_000913.3',
    sequenceType: 'DNA',
    metadata: {
      storageDate: '2024-03-01',
      storageMedium: '20% Glycerol',
      biosafetyLevel: 'BSL-1',
      concentration: '2.5x10^9 CFU/ml',
      cultureCondition: 'LB, 37°C, 220rpm',
      resistance: ['Amp', 'Kan'],
      genotype: 'F- lambda- ilvG- rfb-50 rph-1',
      description: 'Standard lab strain for molecular biology.'
    }
  },
  {
    name: 'T4 Phage High Titer Stock',
    sampleType: 'Phage' as SampleCategory,
    species: 'Enterobacteria phage T4',
    sequenceType: 'DNA',
    metadata: {
      storageDate: '2024-03-15',
      storageMedium: 'SM Buffer',
      biosafetyLevel: 'BSL-1',
      potency: '1.2x10^12 PFU/ml',
      hostStrain: 'E. coli B',
      lifestyle: 'Virulent',
      latentPeriod: '25 min',
      burstSize: '150 PFU/cell',
      morphology: 'Myoviridae'
    }
  },
  {
    name: 'SARS-CoV-2 Delta Variant',
    sampleType: 'Virus' as SampleCategory,
    species: 'Severe acute respiratory syndrome coronavirus 2',
    sequenceType: 'RNA',
    metadata: {
      storageDate: '2024-02-10',
      storageMedium: 'Viral Transport Medium',
      biosafetyLevel: 'BSL-3',
      potency: '5.0x10^7 TCID50/ml',
      titer: '2.4x10^8 copies/ml',
      serotype: 'B.1.617.2',
      envelope: 'Enveloped',
      inactivationMethod: 'None (Live)'
    }
  },
  {
    name: 'pcDNA3.1-EGFP Expression Plasmid',
    sampleType: 'Plasmid' as SampleCategory,
    sequenceType: 'DNA',
    metadata: {
      storageDate: '2024-04-01',
      storageMedium: 'TE Buffer',
      concentration: '1200 ng/ul',
      hostStrain: 'DH5α',
      backbone: 'pcDNA3.1(+)',
      insertName: 'EGFP',
      plasmidSize: '6.2 kb',
      marker: ['Ampicilin'],
      isExpression: true,
      promoter: 'CMV'
    }
  },
  {
    name: 'Purified Cas9 Protein (High Purity)',
    sampleType: 'Protein' as SampleCategory,
    sequenceType: 'Protein',
    metadata: {
      storageDate: '2024-03-20',
      storageMedium: 'Storage Buffer with 50% Glycerol',
      concentration: '10 mg/ml',
      purity: '>98% (SDS-PAGE)',
      molecularWeight: '160 kDa',
      buffer: '20mM HEPES, 150mM KCl, 1mM DTT',
      tags: ['6xHis']
    }
  },
  {
    name: 'HEK293T Cell Line P15',
    sampleType: 'CellLine' as SampleCategory,
    species: 'Homo sapiens',
    sequenceType: 'DNA',
    metadata: {
      storageDate: '2024-01-05',
      storageMedium: '90% FBS + 10% DMSO',
      concentration: '2.0x10^6 cells/ml',
      cellType: 'Adherent',
      medium: 'DMEM + 10% FBS',
      doublingTime: '24h',
      authentication: 'ATCC-CRL-3216'
    }
  }
]

/**
 * 自动填充脚本 - 适配 v6 编码系统
 */
export function seedMockData(strainStore: any, codeGen: any) {
  // 查找一个可用的空槽位
  const freezer = strainStore.freezers[0]
  if (!freezer) {
    console.warn('请先创建一个冰箱后再填充测试数据')
    return
  }
  
  const shelf = freezer.shelves[0]
  const cabinet = shelf?.cabinets[0]
  const drawer = cabinet?.drawers[0]
  const box = drawer?.boxes[0]
  
  if (!box) return

  // 预设一些分类映射 (与 builtinCodes.ts 中的内置代码对应)
  const taxonMap: Record<string, any> = {
    'Bacteria': { cat: '1', gen: 'AKF', spc: 'BXM' },
    'Phage':    { cat: '3', gen: 'PHG', spc: 'TFA' }, // T04 -> TFA
    'Virus':    { cat: '2', gen: 'COV', spc: 'SAR' }, // S02 -> SAR
    'Plasmid':  { cat: '5', gen: 'VEC', spc: 'PCD' }, // D03 -> PCD
    'Protein':  { cat: '8', gen: 'ENZ', spc: 'CAS' },
    'CellLine': { cat: '6', gen: 'CEL', spc: 'HEK' }, // 293 -> HEK
  }

  const sources = ['ZC', 'AT', 'NC', 'BJ']

  MOCK_SAMPLES.forEach((mock, index) => {
    const positionObj = box.positions[index]
    if (!positionObj) return
    
    const pos = positionObj.label
    const taxon = taxonMap[mock.sampleType as string] || { cat: '9', gen: 'OTH', spc: '001' }
    const source = sources[index % sources.length]

    try {
      const sampleCode = codeGen.generate({
        sourceCode: source,
        categoryCode: taxon.cat,
        genusCode: taxon.gen,
        speciesCode: taxon.spc,
        passage: index % 5
      })

      const taxonomyPath = `${taxon.cat}${taxon.gen}${taxon.spc}`
      const serial = codeGen.counter.getCurrentValue(taxonomyPath)

      const record = strainStore.addRecord({
        ...mock,
        sampleCode,
        codeSource: source,
        codeCategory: taxon.cat,
        codeGenus: taxon.gen,
        codeSpecies: taxon.spc,
        codePassage: index % 5,
        codeSerial: serial,
        accession: sampleCode, 
        freezerId: freezer.id,
        shelfId: shelf.id,
        cabinetId: cabinet.id,
        drawerId: drawer.id,
        boxId: box.id,
        position: pos
      })
      
      strainStore.updatePositionOccupancy(
        freezer.id, shelf.id, cabinet.id, drawer.id, box.id, pos,
        true, record.id
      )
    } catch (e) {
      console.error('填充测试样本失败:', e)
    }
  })
  
  console.log('✅ v6 编码系统填充测试完成。')
}
