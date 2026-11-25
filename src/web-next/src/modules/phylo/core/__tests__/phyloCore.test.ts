import { describe, expect, it } from 'vitest'
import { formatNodeDisplayLabel, PhyloTreeModel } from '../TreeModel'
import { PhyloTreeLayout } from '../TreeLayout'
import {
  buildStarPolygonPoints,
  buildTopGenusColorMap,
  computeNiceScaleValue,
  detectMonophyleticClades,
  isFormalTaxonName,
  JOURNAL_THEMES,
  mapHostToPhylum,
  splitTaxonomicLabelSegments,
} from '../JournalTheme'
import type { TreeVisualSettings } from '../../types/phylo'

const DEFAULT_VISUAL: TreeVisualSettings = {
  layout: 'rect',
  useBranchLengths: true,
  showLabels: true,
  labelFormat: 'name_acc',
  showSupport: true,
  supportThreshold: 50,
  fontSize: 13,
  rowSpacing: 24,
  sortMode: 'original',
  searchQuery: '',
  showMetadataStrips: true,
  highlightStrongUfboot: true,
  journalTheme: 'nature',
  alignTipLabels: true,
  showCladeShading: true,
  italicizeTaxa: true,
  smartLabelCull: true,
}

describe('PhyloCore TreeModel & Layout', () => {
  it('parses quoted labels, scientific lengths, and bootstrap supports', () => {
    const model = new PhyloTreeModel()
    const root = model.parse("(('Taxon A':1.5e-3,Taxon_B:0.02)92:0.05,(Taxon_C:0.08,Taxon_D:0.04)78:0.03);")
    expect(root).not.toBeNull()
    expect(model.leaves.map((l) => l.name)).toEqual(['Taxon A', 'Taxon_B', 'Taxon_C', 'Taxon_D'])
    const firstInternal = root!.children[0]!
    expect(firstInternal.support).toBe(92)
    expect(model.toNewick()).toContain("'Taxon A'")
  })

  it('parses and preserves dual SH-aLRT/UFBoot supports and applies metadata strips', () => {
    const model = new PhyloTreeModel()
    const root = model.parse('((Query_Phage:0.02,Ref_A:0.03)98.5/100:0.05,Outgroup_X:0.2);')
    expect(root).not.toBeNull()
    const inner = root!.children[0]!
    expect(inner.alrt).toBe(98.5)
    expect(inner.ufboot).toBe(100)
    expect(inner.supportLabel).toBe('98.5/100')
    expect(model.toNewick()).toContain('98.5/100')

    const baseBounds = PhyloTreeLayout.compute(model, DEFAULT_VISUAL)
    model.applyNodeMetadata({
      Query_Phage: { role: 'query', genome_length: 42500 },
      Ref_A: { role: 'ictv_rep', genus: 'Warsawvirus', genome_length: 40200 },
      Outgroup_X: { role: 'outgroup', genus: 'Teseptimavirus', genome_length: 39800 },
    })
    expect(model.hasNodeMetadata).toBe(true)
    expect(model.maxGenomeLength).toBe(42500)

    const metaBounds = PhyloTreeLayout.compute(model, DEFAULT_VISUAL)
    expect(metaBounds.maxX).toBeGreaterThan(baseBounds.maxX)
  })

  it('supports midpoint and outgroup rerooting without dropping leaf names', () => {
    const model = new PhyloTreeModel()
    model.parse('((A:0.1,B:0.1)95:0.2,C:0.6,D:0.3);')
    model.rerootMidpoint()
    expect(model.root!.children.length).toBe(2)
    expect(model.leaves.map((l) => l.name).sort()).toEqual(['A', 'B', 'C', 'D'])

    const targetD = model.leaves.find((l) => l.name === 'D')!
    model.rerootOutgroup(targetD.id)
    expect(model.leaves.map((l) => l.name).sort()).toEqual(['A', 'B', 'C', 'D'])
  })

  it('supports ladderize sorting and clade collapsing', () => {
    const model = new PhyloTreeModel()
    model.parse('(((A:0.1,B:0.1):0.1,C:0.2):0.1,D:0.3);')
    model.applySorting('ladder-right')
    expect(model.leaves[0]!.name).toBe('D')

    const clade = model.root!.children[1]!
    model.toggleCollapse(clade.id)
    expect(model.leaves.length).toBe(2)
  })

  it('computes rectangular, circular, and unrooted layouts cleanly', () => {
    const model = new PhyloTreeModel()
    model.parse('((A:0.1,B:0.2)90:0.1,(C:0.15,D:0.25)85:0.1);')

    for (const layout of ['rect', 'circular', 'unrooted'] as const) {
      const bounds = PhyloTreeLayout.compute(model, { ...DEFAULT_VISUAL, layout })
      expect(bounds.maxX).toBeGreaterThan(bounds.minX)
      expect(bounds.maxY).toBeGreaterThan(bounds.minY)
      for (const leaf of model.leaves) {
        expect(Number.isFinite(leaf.x)).toBe(true)
        expect(Number.isFinite(leaf.y)).toBe(true)
      }
    }
  })

  it('expands rectangular maxX dynamically for long taxon names', () => {
    const shortModel = new PhyloTreeModel()
    shortModel.parse('(A:0.1,B:0.2,C:0.3);')
    const shortBounds = PhyloTreeLayout.compute(shortModel, DEFAULT_VISUAL)

    const longModel = new PhyloTreeModel()
    longModel.parse('(Very_Long_Phage_Genome_Assembly_Scaffold_Identifier_001:0.1,B:0.2,C:0.3);')
    const longBounds = PhyloTreeLayout.compute(longModel, DEFAULT_VISUAL)

    expect(longBounds.maxX).toBeGreaterThan(shortBounds.maxX)
  })

  it('formats phage display labels across name_acc, name, and accession modes', () => {
    const refNode = {
      name: 'AY587007',
      meta: { role: 'ictv_rep' as const, description: 'Escherichia phage T5, complete genome' },
    }
    expect(formatNodeDisplayLabel(refNode, 'name_acc')).toBe('Escherichia phage T5 (AY587007)')
    expect(formatNodeDisplayLabel(refNode, 'name')).toBe('Escherichia phage T5')
    expect(formatNodeDisplayLabel(refNode, 'accession')).toBe('AY587007')

    const queryNode = {
      name: 'T5-E1_asm',
      meta: { role: 'query' as const, description: 'Should be ignored for queries' },
    }
    expect(formatNodeDisplayLabel(queryNode, 'name_acc')).toBe('T5-E1_asm')
  })

  it('preserves leaf metadata descriptions and dual support values across reroot and sorting', () => {
    const model = new PhyloTreeModel()
    model.parse('((Query_Phage:0.02,AY587007:0.03)98.5/100:0.05,(Ref_B:0.1,NC_055913:0.25)91/96:0.1);')
    model.applyNodeMetadata({
      Query_Phage: { role: 'query', genome_length: 104500 },
      AY587007: {
        role: 'ictv_rep',
        genus: 'Tequintavirus',
        description: 'Escherichia phage T5',
        genome_length: 121750,
      },
      Ref_B: {
        role: 'neighbor',
        genus: 'Vequintavirus',
        description: 'Escherichia phage FFH2',
        genome_length: 139000,
      },
      NC_055913: {
        role: 'outgroup',
        genus: 'Thalassavirus',
        description: 'Vibrio phage Gary',
        genome_length: 128300,
      },
    })

    model.rerootMidpoint()
    model.applySorting('ladder-right')
    const og = model.leaves.find((l) => l.name === 'NC_055913')!
    model.rerootOutgroup(og.id)

    const ayLeaf = model.leaves.find((l) => l.name === 'AY587007')!
    expect(ayLeaf.meta?.description).toBe('Escherichia phage T5')
    expect(formatNodeDisplayLabel(ayLeaf, 'name_acc')).toBe('Escherichia phage T5 (AY587007)')
    expect(model.hasNodeMetadata).toBe(true)
    const dualSupportNodes = Array.from(model.nodesById.values()).filter((n) => !n.isLeaf && n.supportLabel)
    expect(dualSupportNodes.some((n) => n.supportLabel === '98.5/100' && n.ufboot === 100)).toBe(true)
  })

  it('provides publication journal palettes, italic taxon splitting, nice scales, and clade detection', () => {
    expect(Object.keys(JOURNAL_THEMES)).toEqual(['nature', 'lancet', 'okabe_ito', 'monochrome'])
    expect(computeNiceScaleValue(0.0024)).toBe(0.002)
    expect(computeNiceScaleValue(0.14)).toBe(0.1)
    expect(computeNiceScaleValue(0.16)).toBe(0.2)
    expect(mapHostToPhylum('Escherichia coli K12')).toBe('Pseudomonadota')
    expect(mapHostToPhylum('Mycobacterium smegmatis')).toBe('Actinomycetota')
    expect(isFormalTaxonName('Tequintavirus')).toBe(true)
    expect(isFormalTaxonName('Unclassified')).toBe(false)

    expect(splitTaxonomicLabelSegments('Escherichia phage T5 (AY587007)')).toEqual([
      { text: 'Escherichia', italic: true },
      { text: ' phage T5 (AY587007)', italic: false },
    ])
    expect(splitTaxonomicLabelSegments('测试中文噬菌体01')).toEqual([
      { text: '测试中文噬菌体01', italic: false },
    ])

    const starPts = buildStarPolygonPoints(10, 10, 6, 2.5)
    expect(starPts.split(' ').length).toBe(10)

    const model = new PhyloTreeModel()
    model.parse('((Q1:0.01,(R1:0.02,R2:0.02)99:0.01)96:0.03,OG:0.2);')
    model.applyNodeMetadata({
      Q1: { role: 'query', host: 'Escherichia' },
      R1: { role: 'ictv_rep', genus: 'Tequintavirus', host: 'Escherichia' },
      R2: { role: 'neighbor', genus: 'Tequintavirus', host: 'Salmonella' },
      OG: { role: 'outgroup', genus: 'Thalassavirus', host: 'Vibrio' },
    })
    const clades = detectMonophyleticClades(model.root!, model.leaves, model.genusColors)
    expect(clades.length).toBe(1)
    expect(clades[0]!.taxonName).toBe('Tequintavirus')
    expect(clades[0]!.leafStartIdx).toBe(0)
    expect(clades[0]!.leafEndIdx).toBe(2)

    const manyLeaves = Array.from({ length: 16 }, (_, idx) => ({
      name: `L${idx}`,
      meta: { role: idx === 0 ? ('query' as const) : ('neighbor' as const), genus: `Genus${idx}` },
    }))
    const topMap = buildTopGenusColorMap(manyLeaves as any, 'nature', 6)
    expect(topMap.genusColors.size).toBe(6)
    expect(new Set(topMap.genusColors.values()).size).toBe(6)
    expect(topMap.otherGenera.size).toBe(10)

    // 仅在 genusColors 映射表中的属才生成单系背景阴影，未配色属不涂灰
    const filteredClades = detectMonophyleticClades(
      model.root!,
      model.leaves,
      new Map<string, string>()
    )
    expect(filteredClades.length).toBe(0)
  })
})
