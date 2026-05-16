export interface TrackLayer {
  id: string;            // e.g., 'main-cds', 'main-orf-+1'
  groupId: string;       // e.g., 'main'
  type: 'feature' | 'graph' | 'line';
  direction: 'inner' | 'outer';
  rowHeight: number;     // Physical height per row
  rowCount: number;      // Multiplier for overlapping features
  gap: number;           // Additional padding after this layer
  order: number;         // Chronological order for stacking
}

export interface TrackGroup {
  id: string;
  order: number;
}

export interface LayerBounds {
  innerR: number;
  outerR: number;
  linearY: number; // For linear maps
}

export class TrackLayoutEngine {
  private groups = new Map<string, TrackGroup>();
  private layers = new Map<string, TrackLayer>();
  private baseMargin = 10; // Base margin from backbone

  // Add a group
  public addGroup(id: string, order: number) {
    this.groups.set(id, { id, order });
  }

  // Register or update a layer
  public setLayer(layer: TrackLayer) {
    this.layers.set(layer.id, layer);
  }

  public removeLayer(id: string) {
    this.layers.delete(id);
  }

  public hasLayer(id: string) {
    return this.layers.has(id);
  }

  // Resolve the entire layout relative to a starting baseRadius
  public resolveLayout(initialBaseRadius: number) {
    const layoutMap = new Map<string, { bounds: LayerBounds, rows: LayerBounds[] }>();
    
    // Sort groups by order
    const sortedGroups = Array.from(this.groups.values()).sort((a, b) => a.order - b.order);
    
    let currentGroupBaseRadius = initialBaseRadius;
    let maxOuterR = initialBaseRadius; // Track the absolute outermost radius for subsequent groups

    for (const group of sortedGroups) {
      // In a multi-sequence view, the next group starts beyond the maxOuterR of the previous group
      if (group.order > 0) {
        currentGroupBaseRadius = maxOuterR + 50; // 50px inter-sequence gap
      }

      const groupLayers = Array.from(this.layers.values()).filter(l => l.groupId === group.id);
      
      // Separate inner and outer
      const innerLayers = groupLayers.filter(l => l.direction === 'inner').sort((a, b) => a.order - b.order);
      const outerLayers = groupLayers.filter(l => l.direction === 'outer').sort((a, b) => a.order - b.order);

      // Process Inner Layers (they grow towards the center)
      let innerOffset = this.baseMargin;
      for (const layer of innerLayers) {
        const totalHeight = layer.rowHeight * layer.rowCount;
        const outerR = currentGroupBaseRadius - innerOffset;
        const innerR = outerR - totalHeight;
        
        const linearY = -innerOffset;
        
        // Calculate sub-rows
        const rows: LayerBounds[] = [];
        for (let i = 0; i < layer.rowCount; i++) {
          const rowOuter = outerR - (i * layer.rowHeight);
          const rowInner = rowOuter - layer.rowHeight;
          const rowLinearY = linearY - (i * layer.rowHeight);
          rows.push({ innerR: rowInner, outerR: rowOuter, linearY: rowLinearY });
        }

        layoutMap.set(layer.id, { bounds: { innerR, outerR, linearY }, rows });
        innerOffset += totalHeight + layer.gap;
      }

      // Process Outer Layers (they grow away from center)
      let outerOffset = this.baseMargin;
      for (const layer of outerLayers) {
        const totalHeight = layer.rowHeight * layer.rowCount;
        const innerR = currentGroupBaseRadius + outerOffset;
        const outerR = innerR + totalHeight;
        
        const linearY = outerOffset;

        // Calculate sub-rows
        const rows: LayerBounds[] = [];
        for (let i = 0; i < layer.rowCount; i++) {
          const rowInner = innerR + (i * layer.rowHeight);
          const rowOuter = rowInner + layer.rowHeight;
          const rowLinearY = linearY + (i * layer.rowHeight);
          rows.push({ innerR: rowInner, outerR: rowOuter, linearY: rowLinearY });
        }

        layoutMap.set(layer.id, { bounds: { innerR, outerR, linearY }, rows });
        outerOffset += totalHeight + layer.gap;
      }

      if (currentGroupBaseRadius + outerOffset > maxOuterR) {
        maxOuterR = currentGroupBaseRadius + outerOffset;
      }
    }

    return {
      getLayer: (id: string) => layoutMap.get(id),
      getOuterBoundary: () => maxOuterR,
      getBaseRadius: (groupId: string) => {
         // Could calculate specific baseRadius if needed
         return initialBaseRadius;
      }
    };
  }
}
