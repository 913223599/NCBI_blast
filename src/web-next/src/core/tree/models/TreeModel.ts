export interface TreeNode {
    id: string
    name?: string
    children: TreeNode[]
    parent: TreeNode | null
    branch_length: number
    original_length?: number 
    depth: number
    heightFromRoot: number
    isLeaf: boolean
    leafCount?: number
    minTaxon?: string
    maxDistToLeaf?: number
    parseIndex: number

    x?: number
    y?: number
    cartX?: number
    cartY?: number
    angle?: number
    radius?: number
}

/**
 * 分类学排序哨兵值：用于未命名节点在分类学排序中的占位
 * 设定为 'zzz' 使未命名节点排到末尾
 */
const TAXONOMY_SORT_SENTINEL = 'zzz'

/**
 * 进化树核心数据模型 (Station 2.0)
 */
export class TreeModel {
    root: TreeNode | null = null
    leaves: TreeNode[] = []
    nodesById: Record<string, TreeNode> = {}
    maxDepth: number = 0
    maxHeight: number = 0
    version: number = 0 // 版本标识，用于触发渲染强制同步

    constructor() { }

    incrementVersion() {
        this.version++
    }

    parse(s: string | undefined): TreeNode | null {
        if (!s || !s.trim()) return null
        let input = s.trim()
        if (input.endsWith(';')) input = input.substring(0, input.length - 1)

        let i = 0
        const parseNode = (parent: TreeNode | null): TreeNode => {
            const node: TreeNode = { 
                id: '', // 稍后在 _processTree 中分配
                children: [], 
                parent, 
                branch_length: 0, 
                name: "",
                depth: 0,
                heightFromRoot: 0,
                isLeaf: false,
                parseIndex: 0
            }
            if (input[i] === '(') {
                i++ 
                let childIndex = 0
                while (true) {
                    const child = parseNode(node)
                    child.parseIndex = childIndex++
                    node.children.push(child)
                    if (input[i] === ',') i++ 
                    else if (input[i] === ')') { i++; break }
                    else break
                }
            }
            let labelStart = i
            while (i < input.length && !['(', ')', ',', ':', ';'].includes(input[i] as string)) i++
            if (i > labelStart) node.name = input.substring(labelStart, i).trim()
            if (i < input.length && input[i] === ':') {
                i++;
                let lenStart = i
                while (i < input.length && !['(', ')', ',', ';'].includes(input[i] as string)) i++
                const rawLen = parseFloat(input.substring(lenStart, i).trim()) || 0
                // 核心修复：强制分枝长度非负，消除 NJ 算法中由于浮点误差或高度相似序列产生的逆向绘图
                node.branch_length = Math.max(0, rawLen)
            }
            return node
        }

        try {
            this.root = parseNode(null)
            this._processTree()
            return this.root
        } catch (e) {
            console.error("Newick Parse Failed:", e)
            return null
        }
    }

    _processTree() {
        this.incrementVersion() // 核心维护：每次拓扑重构必须强制升级版本，通知渲染器刷 Labels
        this.leaves = []
        this.nodesById = {}
        this.maxDepth = 0
        this.maxHeight = 0
        if (!this.root) return

        // Issue #5: 使用确定性递增计数器替代 Math.random()，
        // 保证相同拓扑下生成相同 ID 序列，避免渲染器缓存失效
        let idCounter = 0
        const stack: { node: TreeNode, depth: number, height: number, parent: TreeNode | null }[] = [
            { node: this.root, depth: 0, height: 0, parent: null }
        ]

        while (stack.length > 0) {
            const item = stack.pop()
            if (!item) continue
            const { node, depth, height, parent } = item
            node.id = `tree_n_v${this.version}_${idCounter++}`
            node.depth = depth
            node.heightFromRoot = height
            node.parent = parent
            this.nodesById[node.id] = node

            if (!node.children || node.children.length === 0) {
                node.isLeaf = true
                node.children = []
                this.leaves.push(node)
                if (depth > this.maxDepth) this.maxDepth = depth
                if (height > this.maxHeight) this.maxHeight = height
            } else {
                node.isLeaf = false
                for (const child of node.children) {
                    stack.push({
                        node: child,
                        depth: depth + 1,
                        height: height + (child.branch_length || 0),
                        parent: node
                    })
                }
            }
        }
    }

    /**
     * 第一步：中点定根 (Midpoint Rooting)
     * 核心逻辑：寻找演化直径 -> 定位几何中点 -> 物理劈裂边
     */
    rerootMidpoint() {
        if (!this.root || this.leaves.length < 2) return
        
        // 1. 寻找演化直径
        const tipA = this._findFar(this.leaves[0]!).node
        const { node: tipB, dist: totalDist } = this._findFar(tipA)
        
        // 2. 溯源路径
        const path: TreeNode[] = []
        let curr: TreeNode | null = tipB
        while (curr) { path.push(curr); curr = curr.parent }
        
        // 3. 寻找中点所在的边 (U, V)
        if (path.length < 2) return
        let v: TreeNode = tipB
        let u: TreeNode = path[1]!
        let d = 0
        for (let i = 0; i < path.length - 1; i++) {
            const node = path[i]
            if (node && d + node.branch_length >= totalDist / 2) {
                v = node
                u = path[i + 1]!
                break
            }
            if (node) d += node.branch_length
        }

        if (!u) return

        // 4. 执行边劈裂定根 (Edge Splitting)
        // A. 临时将树以 U 为根
        this.rerootAtNode(u)
        
        // B. 插入二叉虚拟根
        const newRoot: TreeNode = {
            id: `vroot_${Date.now()}`,
            children: [],
            parent: null,
            branch_length: 0,
            depth: 0,
            heightFromRoot: 0,
            isLeaf: false,
            parseIndex: 0
        }

        const distToV = totalDist / 2 - d
        const distToU = v.branch_length - distToV

        // C. 断开 U-V 原始链接，重新挂向新根
        u.children = u.children.filter(c => c !== v)
        v.parent = newRoot
        v.branch_length = Math.max(0, distToV)
        u.parent = newRoot
        u.branch_length = Math.max(0, distToU)

        newRoot.children = [u, v]
        this.root = newRoot

        // D. 强制执行层级重建
        this._processTree()
    }

    /**
     * 第二步：计算排序权重 (Weight Calculation)
     * 在排序前先预计算各支系的度衡量，避免排序过程中的重复递归
     */
    prepareWeights(_mode: 'ladder-right' | 'ladder-left' | 'taxonomic' | 'distance', annotations?: Record<string, string>) {
        if (!this.root) return
        
        const _recursiveWeight = (node: TreeNode): { count: number, minTaxon: string, maxDist: number } => {
            if (node.isLeaf) {
                node.leafCount = 1
                // 核心增强：如果存在分类学字典，则优先使用识别出的物种名参与排序搜索
                const identity = annotations ? (annotations[node.name || ''] || node.name || TAXONOMY_SORT_SENTINEL) : (node.name || TAXONOMY_SORT_SENTINEL);
                node.minTaxon = identity
                node.maxDistToLeaf = 0
                return { count: 1, minTaxon: identity, maxDist: 0 }
            }

            let count = 0
            let minTax = node.name || TAXONOMY_SORT_SENTINEL
            let maxD = 0

            if (node.children) {
                for (const child of node.children) {
                    const res = _recursiveWeight(child)
                    count += res.count
                    if (res.minTaxon < minTax) minTax = res.minTaxon
                    maxD = Math.max(maxD, res.maxDist + child.branch_length)
                }
            }
            node.leafCount = count
            node.minTaxon = minTax
            node.maxDistToLeaf = maxD
            return { count, minTaxon: minTax, maxDist: maxD }
        }
        _recursiveWeight(this.root)
    }

    /**
     * 第三步：执行拓扑排序 (Topological Sorting)
     * 目的：调整 Children 列表的逻辑顺序
     */
    applySorting(type: 'ladder-right' | 'ladder-left' | 'taxonomic' | 'distance' | 'original', annotations?: Record<string, string>) {
        if (!this.root) return
        
        // 1. 如果不是原始序列，先预计算权重
        if (type !== 'original') {
            this.prepareWeights(type as any, annotations)
        }
        
        // 2. 深度优先遍历并执行排序
        const _recursiveSort = (node: TreeNode) => {
            if (node.children && node.children.length > 1) {
                node.children.sort((a, b) => {
                    switch (type) {
                        case 'ladder-right': return (a.leafCount || 1) - (b.leafCount || 1)
                        case 'ladder-left': return (b.leafCount || 1) - (a.leafCount || 1)
                        case 'taxonomic': return (a.minTaxon || '').localeCompare(b.minTaxon || '')
                        case 'distance': return (a.maxDistToLeaf || 0) - (b.maxDistToLeaf || 0)
                        case 'original': return (a.parseIndex || 0) - (b.parseIndex || 0)
                        default: return 0
                    }
                })
                node.children.forEach(c => _recursiveSort(c))
            }
        }
        
        // 特殊处理：ladder-left 的逻辑稍微不同
        if (type === 'ladder-left') {
             const _sortLeft = (node: TreeNode) => {
                 if (node.children && node.children.length > 1) {
                     node.children.sort((a, b) => (b.leafCount || 1) - (a.leafCount || 1))
                     node.children.forEach(c => _sortLeft(c))
                 }
             }
             _sortLeft(this.root)
        } else {
             _recursiveSort(this.root)
        }
    }

    /**
     * 辅助寻找最远路径
     */
    _findFar(startNode: TreeNode): { node: TreeNode, dist: number } {
        let maxDist = -1, farNode = startNode
        const q: { node: TreeNode, d: number }[] = [{ node: startNode, d: 0 }]
        const visited = new Set([startNode.id])
        while (q.length > 0) {
            const { node, d } = q.shift()!
            if (d > maxDist) { maxDist = d; farNode = node }
            const neighbors = [...(node.children || []), node.parent].filter((n): n is TreeNode => n !== null && !visited.has(n.id))
            neighbors.forEach(n => {
                visited.add(n.id)
                q.push({ node: n, d: d + (n === node.parent ? node.branch_length : n.branch_length) })
            })
        }
        return { node: farNode, dist: maxDist }
    }

    /**
     * 将树重新定根到特定节点 (物理反转)
     */
    rerootAtNode(targetNode: TreeNode) {
        if (!this.root || targetNode === this.root) return
        const path: TreeNode[] = []
        let curr: TreeNode | null = targetNode
        while (curr) { path.push(curr); curr = curr.parent }

        for (let i = path.length - 1; i > 0; i--) {
            const p = path[i] as TreeNode, c = path[i - 1] as TreeNode
            p.children = p.children.filter(x => x !== c)
            c.children.push(p)
            p.parent = c
            p.branch_length = c.branch_length
            c.branch_length = 0
            c.parent = null
        }
        this.root = targetNode
    }

    getLeafCount(): number {
        return this.leaves.length
    }

    /**
     * 将当前内存中的树结构导出为 Newick 字符串
     */
    getNewick(): string {
        if (!this.root) return ""
        
        const _serialize = (node: TreeNode): string => {
            let s = ""
            if (node.children && node.children.length > 0) {
                s = "(" + node.children.map(c => _serialize(c)).join(",") + ")"
            }
            if (node.name) s += node.name
            if (node.branch_length !== undefined) {
                s += ":" + node.branch_length
            }
            return s
        }
        
        return _serialize(this.root) + ";"
    }
}
