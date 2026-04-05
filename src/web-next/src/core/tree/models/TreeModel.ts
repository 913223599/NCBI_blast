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
    parseIndex?: number

    x?: number
    y?: number
    cartX?: number
    cartY?: number
    angle?: number
    radius?: number
}

/**
 * 进化树核心数据模型 (Station 2.0)
 */
export class TreeModel {
    root: TreeNode | null = null
    leaves: TreeNode[] = []
    nodesById: Record<string, TreeNode> = {}
    maxDepth: number = 0
    maxHeight: number = 0

    constructor() { }

    parse(s: string | undefined): TreeNode | null {
        if (!s || !s.trim()) return null
        let input = s.trim()
        if (input.endsWith(';')) input = input.substring(0, input.length - 1)

        let i = 0
        const parseNode = (parent: any): any => {
            const node: any = { children: [], parent, branch_length: 0, name: "" }
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
        this.leaves = []
        this.nodesById = {}
        this.maxDepth = 0
        this.maxHeight = 0
        if (!this.root) return

        let idCounter = 0
        const stack: any[] = [{ node: this.root, depth: 0, height: 0, parent: null }]

        while (stack.length > 0) {
            const { node, depth, height, parent } = stack.pop()
            // 唯一 ID 保护：定根后 ID 必须重刷，防止渲染器缓存错误
            node.id = `tree_n_${Math.random().toString(36).substr(2, 4)}_${idCounter++}`
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

    rerootMidpoint() {
        if (!this.root || this.leaves.length < 2) return
        
        // 1. 寻找演化直径
        const tipA = this._findFar(this.leaves[0] as TreeNode).node
        const { node: tipB, dist: totalDist } = this._findFar(tipA)
        
        // 2. 溯源路径
        const path: TreeNode[] = []
        let curr: any = tipB
        while (curr) { path.push(curr); curr = curr.parent }
        
        // 3. 寻找中点所在的边 (U, V)
        if (path.length < 2) return
        let v: TreeNode = tipB
        let u: TreeNode = path[1]! // 安全判定
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
        // 我们先将树以 U 为临时根
        this.rerootAtNode(u)
        
        // 创建新的二叉根
        const newRoot: TreeNode = {
            id: 'virtual_root_' + Date.now(),
            children: [],
            parent: null,
            branch_length: 0,
            depth: 0,
            heightFromRoot: 0,
            isLeaf: false,
            parseIndex: 0
        }

        // 把 U 和 V 分别作为新根的两个孩子
        const distToV = totalDist / 2 - d
        const distToU = v.branch_length - distToV

        // 调整 V，使其脱离原有父子关系，挂载到新根
        if (u.children) u.children = u.children.filter(c => c !== v)
        
        v.parent = newRoot
        v.branch_length = Math.max(0, distToV)
        
        u.parent = newRoot
        u.branch_length = Math.max(0, distToU)

        newRoot.children = [u, v]
        this.root = newRoot

        this._processTree()
    }

    /**
     * 系统发育树排序矩阵 (加固版本)
     */
    applySorting(type: 'ladder-right' | 'ladder-left' | 'taxonomic' | 'distance' | 'original') {
        if (!this.root) return
        this.countLeaves(this.root)
        
        const _recursiveSort = (node: TreeNode) => {
            if (node.children && node.children.length > 1) {
                node.children.sort((a, b) => {
                    switch (type) {
                        case 'ladder-right': return (a.leafCount || 1) - (b.leafCount || 1)
                        case 'ladder-left': return (b.leafCount || 1) - (a.leafCount || 1)
                        case 'taxonomic': return (a.name || '').localeCompare(b.name || '')
                        case 'distance': return a.branch_length - b.branch_length
                        case 'original': return (a.parseIndex || 0) - (b.parseIndex || 0)
                        default: return 0
                    }
                })
                node.children.forEach(c => _recursiveSort(c))
            }
        }
        _recursiveSort(this.root)
    }

    /**
     * 递归计算权重 (公共方法以供 UI 逻辑使用)
     */
    countLeaves(node: TreeNode): number {
        // 核心修复：动态判定叶子，不再信任可能过时的静态标识位
        const isLeaf = !node.children || node.children.length === 0
        node.isLeaf = isLeaf 
        
        if (isLeaf) {
            node.leafCount = 1
            return 1
        }
        
        let count = 0
        if (node.children) {
            for (const child of node.children) {
                count += this.countLeaves(child)
            }
        }
        node.leafCount = count
        return count
    }

    /**
     * 辅助寻找最远路径
     */
    _findFar(startNode: TreeNode) {
        let maxDist = -1, farNode = startNode
        const q: any[] = [{ node: startNode, d: 0 }]
        const visited = new Set([startNode.id])
        while (q.length > 0) {
            const { node, d } = q.shift()
            if (d > maxDist) { maxDist = d; farNode = node }
            const neighbors = [...(node.children || []), node.parent].filter(n => n && !visited.has(n.id))
            neighbors.forEach(n => {
                visited.add(n!.id)
                q.push({ node: n, d: d + (n === node.parent ? (node as TreeNode).branch_length : n!.branch_length) })
            })
        }
        return { node: farNode, dist: maxDist }
    }

    /**
     * 将树重新定根到特定节点
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
