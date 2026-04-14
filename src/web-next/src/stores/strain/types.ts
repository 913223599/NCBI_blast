/**
 * Strain Store 类型定义
 */

/** 样本分类枚举 */
export type SampleCategory = 
  | 'Bacteria' | 'Phage' | 'Virus' | 'Fungi' | 'Archaea' 
  | 'Plasmid' | 'GenomicDNA' | 'RNA' | 'Oligo' | 'Library'
  | 'Protein' | 'Enzyme' | 'Antibody' | 'Peptide' | 'Antigen'
  | 'CompetentCell' | 'CellLine' | 'Tissue' | 'Fluid' | 'Environmental'
  | 'Exosome' | 'Vesicle' | 'Organelle' | 'Other'

/** 通用基础元数据 */
export interface BaseMetadata {
  description?: string
  storageMedium?: string
  passageNumber?: string
  biosafetyLevel?: 'BSL-1' | 'BSL-2' | 'BSL-3' | 'BSL-4'
  containerType?: string
  batchNumber?: string
  concentration?: string
  titer?: string
  potency?: string
  storageDate?: string
}

export interface FreezerBox {
  id: string
  name: string
  rows: number
  cols: number
  positions: Array<{
    row: number
    col: number
    label: string
    occupied: boolean
    sampleId?: string
  }>
}

export interface FreezerDrawer {
  id: string
  name: string
  boxes: FreezerBox[]
}

export interface FreezerCabinet {
  id: string
  name: string
  drawers: FreezerDrawer[]
}

export interface FreezerShelf {
  id: string
  name: string
  cabinets: FreezerCabinet[]
}

export interface Freezer {
  id: string
  name: string
  model: string
  location: string
  shelves: FreezerShelf[]
  createdAt: string
  updatedAt: string
}

export interface StrainRecord {
  id: string
  name: string
  accession: string
  species: string
  strain: string
  sampleType: SampleCategory
  sequenceType: 'DNA' | 'RNA' | 'Protein'
  sequence?: string
  source: string
  host: string
  country: string
  collectionDate: string
  metadata: Record<string, any>
  freezerId?: string
  shelfId?: string
  cabinetId?: string
  drawerId?: string
  boxId?: string
  position?: string
  sampleCode?: string
  codeSource?: string
  codeCategory?: string
  codeGenus?: string
  codeSpecies?: string
  codePassage?: number
  codeSerial?: number
  addedAt: string
}

export interface SearchFilters {
  keyword: string
  species: string
  sequenceType: string
  country: string
  dateFrom: string
  dateTo: string
  minLength?: number | null
  maxLength?: number | null
  integrityOnly?: boolean
  sortKey?: string
  sortOrder?: 'asc' | 'desc' | null
}

export interface ImportTask {
  taskId: string
  fileName: string
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled'
  progress: number
  recordCount: number
  startTime: string
}
