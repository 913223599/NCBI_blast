export interface TreeNode {
    id: string
    name?: string
    children: TreeNode[]
    parent: TreeNode | null
    branch_length: number
    original_length?: number // Keep for scientific accuracy
    depth: number
    heightFromRoot: number
    isLeaf: boolean
    leafCount?: number

    // Layout properties (optional until layout runs)
    x?: number
    y?: number
    cartX?: number
    cartY?: number
    angle?: number
    radius?: number
    bbox?: { minX: number; minY: number; maxX: number; maxY: number }
    color?: string
}

export interface Dataset {
    name: string
    type: 'discrete' | 'continuous' | 'bar'
    data: Record<string, number | string>
    colorMap?: Record<string, string>
    gradient?: string[]
    showLegend: boolean
}

export class TreeModel {
    root: TreeNode | null = null
    leaves: TreeNode[] = []
    nodesById: Record<string, TreeNode> = {}
    maxDepth: number = 0
    maxHeight: number = 0
    datasets: Dataset[] = []

    constructor() { }

    parse(newickStr: string): TreeNode | null {
        if (!newickStr || !newickStr.trim()) {
            console.error("[TreeModel Error] Empty Newick string.")
            return null
        }

        // internal parser
        const parseNewick = (s: string): any => {
            const ancestors: any[] = []
            let tree: any = {}
            const tokens = s.split(/\s*(;|\(|\)|,|:)\s*/)
            for (let i = 0; i < tokens.length; i++) {
                const token = tokens[i]
                switch (token) {
                    case '(': // new children
                        const subtree = {}
                        tree.children = [subtree]
                        ancestors.push(tree)
                        tree = subtree
                        break
                    case ',': // another branch
                        const nextSubtree = {}
                        ancestors[ancestors.length - 1].children.push(nextSubtree)
                        tree = nextSubtree
                        break
                    case ')': // optional name next
                        tree = ancestors.pop()
                        break
                    case ':': // optional length next
                        break
                    default:
                        const x = tokens[i - 1]
                        if (x == ')' || x == '(' || x == ',') {
                            tree.name = token
                        } else if (x == ':') {
                            tree.branch_length = parseFloat(token)
                        }
                }
            }
            return tree
        }

        try {
            // Cast the loose parser result to strict TreeNode structure in _processTree
            const rawRoot = parseNewick(newickStr)
            this.root = rawRoot as TreeNode
            this._processTree()
            return this.root
        } catch (e: any) {
            console.error("Error parsing Newick string: " + e.message)
            throw e
        }
    }

    _processTree() {
        this.leaves = []
        this.nodesById = {}
        this.maxDepth = 0
        this.maxHeight = 0

        let counter = 0
        if (!this.root) return

        // Explicitly type the stack
        const stack: { node: any; depth: number; height: number; parent: TreeNode | null }[] = [
            { node: this.root, depth: 0, height: 0, parent: null }
        ]

        while (stack.length > 0) {
            const { node, depth, height, parent } = stack.pop()!

            // Assign ID and standard props
            node.id = node.name ? node.name.replace(/\s+/g, '_') : "node_" + (counter++)
            node.depth = depth
            node.heightFromRoot = height
            node.parent = parent
            node.branch_length = node.branch_length || 0 // Ensure number

            if (depth > this.maxDepth) this.maxDepth = depth
            if (height > this.maxHeight) this.maxHeight = height

            this.nodesById[node.id] = node as TreeNode

            if (!node.children || node.children.length === 0) {
                node.isLeaf = true
                node.children = [] // normalize
                this.leaves.push(node as TreeNode)
            } else {
                node.isLeaf = false
                for (let i = node.children.length - 1; i >= 0; i--) {
                    const child = node.children[i]
                    const rawDist = child.branch_length ? parseFloat(child.branch_length) : 0.01
                    // Clamp negative lengths
                    const dist = Math.max(0, rawDist)
                    child.branch_length = dist
                    child.original_length = rawDist

                    stack.push({
                        node: child,
                        depth: depth + 1,
                        height: height + dist,
                        parent: node as TreeNode
                    })
                }
            }
        }
    }

    getLeafCount(): number {
        return this.leaves.length
    }

    // ... other methods (reroot, prune) can be added later
}
