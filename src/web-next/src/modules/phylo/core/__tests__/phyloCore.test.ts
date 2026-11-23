import { describe, expect, it } from 'vitest'
import { PhyloTreeModel } from '../TreeModel'
import { PhyloTreeLayout } from '../TreeLayout'
import type { TreeVisualSettings } from '../../types/phylo'

const DEFAULT_VISUAL: TreeVisualSettings = {
  layout: 'rect',
  useBranchLengths: true,
  showLabels: true,
  showSupport: true,
  supportThreshold: 50,
  fontSize: 13,
  rowSpacing: 24,
  sortMode: 'original',
  searchQuery: '',
  showMetadataStrips: true,
  highlightStrongUfboot: true,
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
})
