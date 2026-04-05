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
                while (true) {
                    node.children.push(parseNode(node))
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
            node.id = node.name ? node.name.replace(/[^\w]/g, '_') : `node_${idCounter++}`
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
                for (let j = node.children.length - 1; j >= 0; j--) {
                    stack.push({
                        node: node.children[j],
                        depth: depth + 1,
                        height: height + (node.children[j].branch_length || 0),
                        parent: node
                    })
                }
            }
        }
    }

    rerootMidpoint() {
        if (!this.root || this.leaves.length < 2) return
        const tipA = this._findFar(this.leaves[0] as TreeNode).node
        const { node: tipB } = this._findFar(tipA)
        this.rerootAtNode(tipB)
        this._processTree()
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
}
