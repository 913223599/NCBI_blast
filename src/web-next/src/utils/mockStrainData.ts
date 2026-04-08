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
 * 自动填充脚本
 */
export function seedMockData(strainStore: any) {
  // 查找一个可用的空槽位 (假设在第一个冰箱的第一格)
  const freezer = strainStore.freezers[0]
  if (!freezer) return
  
  const shelf = freezer.shelves[0]
  if (!shelf) return

  const cabinet = shelf.cabinets[0]
  if (!cabinet) return

  const drawer = cabinet.drawers[0]
  if (!drawer) return

  const box = drawer.boxes[0]
  if (!box) return

  MOCK_SAMPLES.forEach((mock, index) => {
    // 获取盒内的真实位置标签 (如 A1, A2, ...)
    const positionObj = box.positions[index]
    if (!positionObj) return
    
    const pos = positionObj.label
    
    const record = strainStore.addRecord({
      ...mock,
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
  })
  
  console.log('✅ 项目表单填充测试完成，已录入 6 种不同类型的全元数据样本。')
}
