// --- Tree Engine: Replicating iTOL Core Features ---
var TreeEngine = (function () {

    // --- Model: Data & Parsing ---
    class TreeModel {
        constructor() {
            this.root = null;
            this.leaves = [];
            this.nodesById = {};
            this.maxDepth = 0;
            this.maxHeight = 0;
            this.datasets = []; // Initialize datasets: { name, type, data, colorMap }
        }

        parse(newickStr) {
            this.logToEngine("[TreeModel] Parsing Newick data...");
            if (!newickStr || !newickStr.trim()) {
                this.logToEngine("[TreeModel Error] Empty Newick string.");
                return null;
            }

            // Standalone Newick Parser Implementation
            const parseNewick = (s) => {
                var ancestors = [];
                var tree = {};
                var tokens = s.split(/\s*(;|\(|\)|,|:)\s*/);
                for (var i = 0; i < tokens.length; i++) {
                    var token = tokens[i];
                    switch (token) {
                        case '(': // new children
                            var subtree = {};
                            tree.children = [subtree];
                            ancestors.push(tree);
                            tree = subtree;
                            break;
                        case ',': // another branch
                            var subtree = {};
                            ancestors[ancestors.length - 1].children.push(subtree);
                            tree = subtree;
                            break;
                        case ')': // optional name next
                            tree = ancestors.pop();
                            break;
                        case ':': // optional length next
                            break;
                        default:
                            var x = tokens[i - 1];
                            if (x == ')' || x == '(' || x == ',') {
                                tree.name = token;
                            } else if (x == ':') {
                                tree.branch_length = parseFloat(token);
                            }
                    }
                }
                return tree;
            };

            try {
                this.root = parseNewick(newickStr);
                this._processTree();
                return this.root;
            } catch (e) {
                this.logToEngine("Error parsing Newick string: " + e.message);
                alert("Error parsing tree file. Invalid format?");
                return null;
            }
        }

        logToEngine(msg) {
            if (window.TreeEngine && window.TreeEngine.logToSystem) {
                window.TreeEngine.logToSystem(msg);
            } else {
                console.log(msg);
            }
        }

        _processTree() {
            this.leaves = [];
            this.nodesById = {};
            this.maxDepth = 0;
            this.maxHeight = 0;

            let counter = 0;
            // UPDATE: Start height with root's branch_length to reserve space for the stem
            // SAFETY: Check for NaN
            let val = this.root.branch_length ? parseFloat(this.root.branch_length) : 0;
            if (isNaN(val)) val = 0;
            const rootLen = val;
            const stack = [{ node: this.root, depth: 0, height: rootLen, parent: null }];

            while (stack.length > 0) {
                const { node, depth, height, parent } = stack.pop();
                node.id = node.name ? node.name.replace(/\s+/g, '_') : "node_" + (counter++);
                node.depth = depth;
                node.heightFromRoot = height;
                node.parent = parent;

                if (depth > this.maxDepth) this.maxDepth = depth;
                if (height > this.maxHeight) this.maxHeight = height;

                this.nodesById[node.id] = node;

                if (!node.children || node.children.length === 0) {
                    node.isLeaf = true;
                    this.leaves.push(node);
                } else {
                    node.isLeaf = false;
                    for (let i = node.children.length - 1; i >= 0; i--) {
                        const child = node.children[i];
                        const dist = child.branch_length ? parseFloat(child.branch_length) : 0.01;
                        child.branchlength = dist;
                        stack.push({ node: child, depth: depth + 1, height: height + dist, parent: node });
                    }
                }
            }
        }

        addDataset(name, data, options = {}) {
            // Check if dataset exists, replace if so
            const idx = this.datasets.findIndex(d => d.name === name);
            const ds = {
                name: name,
                data: data, // Map: nodeName -> value
                type: options.type || 'discrete', // 'discrete' or 'continuous' or 'bar'
                colorMap: options.colorMap || {}, // value -> color
                gradient: options.gradient || ['#eff3ff', '#08519c'],
                showLegend: options.showLegend !== false
            };
            if (idx >= 0) {
                this.datasets[idx] = ds;
            } else {
                this.datasets.push(ds);
            }
        }

        removeDataset(name) {
            this.datasets = this.datasets.filter(d => d.name !== name);
        }

        getLeafCount() { return this.leaves.length; }

        _countLeaves(node) {
            // Post-order iterative DFS to calculate leaf counts
            const stack = [node];
            const resultStack = [];
            while (stack.length > 0) {
                const n = stack.pop();
                resultStack.push(n);
                if (n.children) {
                    n.children.forEach(c => stack.push(c));
                }
            }
            while (resultStack.length > 0) {
                const n = resultStack.pop();
                if (!n.children || n.children.length === 0) {
                    n.leafCount = 1;
                } else {
                    n.leafCount = n.children.reduce((sum, c) => sum + (c.leafCount || 0), 0);
                }
            }
            return node.leafCount;
        }

        ladderize(direction = 'asc') {
            this._countLeaves(this.root);
            const stack = [this.root];
            while (stack.length > 0) {
                const node = stack.pop();
                if (node.children) {
                    node.children.sort((a, b) => {
                        return direction === 'asc' ? a.leafCount - b.leafCount : b.leafCount - a.leafCount;
                    });
                    node.children.forEach(c => stack.push(c));
                }
            }
            this._processTree();
        }

        // --- Rerooting Logic ---
        /**
         * Reroot the tree at the edge leading to 'nodeId'.
         * @param {string} nodeId - The ID of the node to root above.
         * @param {number|null} position - Optional distance from the node to place root. If null, uses midpoint (0.5).
         */
        reroot(nodeId, position = null) {
            const target = this.nodesById[nodeId];
            if (!target || target === this.root || !target.parent) {
                console.warn("Cannot reroot: Invalid node or is already root.");
                return false;
            }

            const oldParent = target.parent;
            const edgeLen = target.branch_length || 0;
            const distToTarget = position !== null ? position : edgeLen / 2;
            const distToParent = edgeLen - distToTarget;

            // 1. Create New Root
            const newRoot = {
                id: "ROOT_" + Date.now().toString(36),
                name: "Root",
                children: [],
                branch_length: 0,
                parent: null
            };

            // 2. Prepare Path for Reversal: [Target, P1, P2, ... OldRoot]
            // We need to invert pointers along the path from oldParent up to original root.
            let path = [];
            let curr = oldParent;
            while (curr) {
                path.push(curr);
                curr = curr.parent;
            }

            // 3. Detach Target from Old Parent
            oldParent.children = oldParent.children.filter(c => c !== target);

            // 4. Connect New Root
            // Side A: Target
            target.parent = newRoot;
            target.branch_length = distToTarget;
            newRoot.children.push(target);

            // Side B: The rest of the tree (starting with oldParent)
            // Initial connection: NewRoot -> OldParent
            // But OldParent needs to be inverted.

            let prevNode = newRoot;
            let nextDist = distToParent;

            // Iterate up the path
            for (let i = 0; i < path.length; i++) {
                const node = path[i];
                const originalParent = node.parent; // Save for next iteration (this is P(i+1))
                const originalDist = node.branch_length || 0; // Distance to P(i+1)

                // Invert relationship: node becomes child of prevNode
                node.parent = prevNode;
                node.branch_length = nextDist;

                // If not first node (oldParent), we must add it to prevNode's children
                // (For first node, we handled it separately? No, let's allow the loop to handle children push)
                prevNode.children.push(node);

                // Remove the child we came from (path[i-1]) from this node's children list
                // For path[0] (oldParent), we already removed 'target' manually.
                if (i > 0) {
                    const childCameFrom = path[i - 1];
                    node.children = node.children.filter(c => c !== childCameFrom);
                }

                // Setup for next iteration
                prevNode = node;
                nextDist = originalDist; // The edge length transitions to the next link
            }

            // 5. Clean up Old Root (path[last])
            const oldRoot = path[path.length - 1];
            // After inversion, OldRoot is a leaf or child of Path[last-1].
            // It has children = original_children - child_on_path.
            // If it was a binary root (2 children), now it has 1 child left.
            // A node with 1 child and no data significance should be collapsed.
            if (oldRoot.children.length === 1 && oldRoot.id.toLowerCase().includes('root') && oldRoot.branch_length > 0) {
                // Merge oldRoot into its only child
                const child = oldRoot.children[0];
                const parent = oldRoot.parent;

                // Add distances
                child.branch_length = (child.branch_length || 0) + oldRoot.branch_length;
                child.parent = parent;

                // Update parent's children list
                parent.children = parent.children.map(c => c === oldRoot ? child : c);

                // Remove oldRoot from lookup (optional)
                delete this.nodesById[oldRoot.id];
            }

            // 6. Finalize
            this.root = newRoot;
            this._processTree(); // Recalc heights
            return true;
        }

        /**
         * Prune (remove) a node and its subtree from the tree.
         * If the removal leaves the parent with only one child, the parent is also removed (path compression),
         * unless the parent is the root.
         * @param {string} nodeId - ID of the node to prune.
         */
        prune(nodeId) {
            const target = this.nodesById[nodeId];
            if (!target) return false;

            // Cannot prune root
            if (target === this.root) {
                console.warn("Cannot prune the root node.");
                return false;
            }

            const parent = target.parent;
            if (!parent) return false; // Should act same as root check

            // 1. Remove target from parent's children
            parent.children = parent.children.filter(c => c !== target);

            // 2. Clean up topology (Path Compression)
            // If parent is NOT root and has only 1 child left, we can remove the parent
            // and connect that single child to the grandparent.
            // If parent has only 1 child left (Path Compression)
            if (parent.children.length === 1) {
                const surviving = parent.children[0];

                if (parent !== this.root) {
                    // Logic A: Internal Node Collapse -> Merge into Grandparent
                    const grandParent = parent.parent;
                    if (grandParent) {
                        const distP = parent.branch_length ? parseFloat(parent.branch_length) : 0;
                        const distC = surviving.branch_length ? parseFloat(surviving.branch_length) : 0;
                        const combined = (isNaN(distP) ? 0 : distP) + (isNaN(distC) ? 0 : distC);

                        surviving.parent = grandParent;
                        surviving.branch_length = combined;

                        const idx = grandParent.children.indexOf(parent);
                        if (idx !== -1) grandParent.children[idx] = surviving;
                        else grandParent.children.push(surviving);
                    }
                } else {
                    // Logic B: Root Collapse -> Promote Child to New Root
                    // "Main stem should be only one"
                    const distRoot = parent.branch_length ? parseFloat(parent.branch_length) : 0;
                    const distChild = surviving.branch_length ? parseFloat(surviving.branch_length) : 0;
                    const combined = (isNaN(distRoot) ? 0 : distRoot) + (isNaN(distChild) ? 0 : distChild);

                    surviving.parent = null;
                    surviving.branch_length = combined;
                    this.root = surviving;
                }
            }
            // Note: If parent IS root and has 1 child, it's fine. The root will just have degree 1.
            // Or we could promote the child to be new root, but that changes the tree height basis. 
            // Usually keeping root as is is safer.

            // 3. Rebuild Tree Index & Layout
            this._processTree();
            return true;
        }

        // --- Advanced: Midpoint Rooting ---
        midpointRoot() {
            // 1. Calculate distances from Root (handled in processTree)
            // 2. Find Furthest Leaf A from Root
            // _processTree already sets 'heightFromRoot'.

            // To be precise, we need graph diameter. BFS/DFS on undirected graph.
            // But since we have parent pointers, we can traverse.

            // Helper: Find furthest node and distance from startNode
            const findFurthest = (startNode) => {
                let maxLen = -1;
                let target = null;
                const visited = new Set();

                const traverse = (node, currentDist) => {
                    visited.add(node.id);
                    if (currentDist > maxLen) {
                        maxLen = currentDist;
                        target = node;
                    }

                    // Children
                    if (node.children) {
                        node.children.forEach(c => {
                            if (!visited.has(c.id)) traverse(c, currentDist + (c.branch_length || 0));
                        });
                    }
                    // Parent
                    if (node.parent && !visited.has(node.parent.id)) {
                        traverse(node.parent, currentDist + (node.branch_length || 0));
                    }
                };

                traverse(startNode, 0);
                return { node: target, dist: maxLen };
            };

            // Step 1: Find Node A (furthest from arbitrary leaf, e.g. leaves[0])
            if (this.leaves.length === 0) return false;
            const resA = findFurthest(this.leaves[0]);
            const nodeA = resA.node;

            // Step 2: Find Node B (furthest from A) -> this path is Diameter
            // Also need to track path to find midpoint
            const findPathToFurthest = (startNode) => {
                let maxLen = -1;
                let endNode = null;
                let bestPath = []; // store nodes

                // BFS for path finding might be cleaner, but DFS with stack works
                const visited = new Set();

                // stack: { node, dist, path }
                // Optimization: Backtracking DFS

                // Let's use simple recursion with path copy (simpler code, ok for client side < 5000 nodes)
                // For huge trees, better use parent pointers via DFS.

                const getPath = (curr, goal) => {
                    // We don't know goal yet. We need full traversal.
                };

                // Let's just store "parent pointers" for the BFS/DFS traversal temporary to reconstruct path
                const pathParent = {}; // id -> parentId
                const dists = {};

                const queue = [{ node: startNode, dist: 0 }];
                visited.add(startNode.id);
                dists[startNode.id] = 0;

                let furthest = startNode;

                while (queue.length > 0) {
                    const { node, dist } = queue.shift();

                    if (dist > dists[furthest.id]) {
                        furthest = node;
                    }

                    const neighbors = [...(node.children || [])];
                    if (node.parent) neighbors.push(node.parent);

                    neighbors.forEach(neighbor => {
                        if (!visited.has(neighbor.id)) {
                            visited.add(neighbor.id);
                            dists[neighbor.id] = dist + (neighbor === node.parent ? node.branch_length : neighbor.branch_length);
                            pathParent[neighbor.id] = node;
                            queue.push({ node: neighbor, dist: dists[neighbor.id] });
                        }
                    });
                }

                return { endNode: furthest, maxDist: dists[furthest.id], pathParent };
            };

            const resB = findPathToFurthest(nodeA);
            const nodeB = resB.endNode;
            const totalDist = resB.maxDist;
            const midDist = totalDist / 2;

            // Reconstruct path from B to A
            let curr = nodeB;
            let distSoFar = 0;
            let targetEdgeChild = null; // The child node of the edge containing midpoint
            let distOnEdge = 0; // Distance from targetEdgeChild to the midpoint

            while (curr !== nodeA) {
                const parent = resB.pathParent[curr.id];
                // Distance of this hop
                // Is edge (parent -> curr). If parent is real parent, len is curr.branch_length. 
                // If curr is real parent, len is parent.branch_length.
                // We treated graph undirected.

                let edgeLen = 0;
                if (curr.parent === parent) edgeLen = curr.branch_length;
                else edgeLen = parent.branch_length; // curr is parent of 'parent'

                if (distSoFar + edgeLen >= midDist) {
                    // Midpoint is on this edge
                    targetEdgeChild = curr.parent === parent ? curr : parent;

                    // We need to root "above" targetEdgeChild.
                    // If targetEdgeChild == curr, we are moving up the tree. Midpoint is (midDist - distSoFar) from curr (bottom).
                    // So we root above curr. position = edgeLen - (midDist - distSoFar)? 
                    // No. reroot(node, pos) means pos from node.
                    // If we root at curr, pos is distance from curr.

                    const distFromCurr = midDist - distSoFar;

                    if (curr.parent === parent) {
                        // Edge is Parent -> Child(curr).
                        // We came from Child. Midpoint is distFromCurr away from Child.
                        // So we root above Child at distFromCurr.
                        this.reroot(curr.id, distFromCurr);
                    } else {
                        // Edge is Child(curr) -> Parent(parent).
                        // We came from Parent (logically in undirected path, but practically pathParent maps B->...->A).
                        // Wait, we are tracing B to A.
                        // 'curr' is closer to B. 'parent' is closer to A.
                        // distSoFar is distance from B to curr.

                        // If (curr.parent === parent), physical tree is P -> C(curr).
                        // B is below C. A is above P.
                        // Path goes B ... -> C -> P -> ... A.
                        // We are at C. We walked from B.
                        // Midpoint is on C->P edge.
                        // Default reroot(C, x) puts root on C->P edge at distance x from C.
                        // distFromCurr is distance from C.
                        // So reroot(C.id, distFromCurr).

                        if (curr.parent === parent) {
                            this.reroot(curr.id, distFromCurr);
                        } else {
                            // Physical tree is C(parent) -> P(curr). (curr is real parent).
                            // B is below curr. A is below parent.
                            // Path goes B ... -> curr -> parent -> ... A.
                            // Midpoint on curr->parent edge.
                            // We need to root above 'parent' (the child node physically).
                            // branch_length is on 'parent'.
                            // distance from curr is distFromCurr.
                            // distance from parent is edgeLen - distFromCurr.
                            this.reroot(parent.id, edgeLen - distFromCurr);
                        }
                    }
                    return true;
                }

                distSoFar += edgeLen;
                curr = parent;
            }
            return false;
        }

        // --- Dataset Management ---
        addDataset(config) {
            this.datasets = this.datasets || [];
            this.datasets.push(config);
            instance.update();
        }
    }

    // --- Controller: Layout Logic ---
    class LayoutEngine {
        constructor(model) {
            this.model = model;
            this.settings = {
                mode: 'rect', // 'rect', 'circular', 'unrooted'
                branchStyle: 'square', // 'square', 'slanted', 'curved'
                rotation: 0,
                arc: 350,
                invert: false,
                useBranchLengths: true,
                showLabels: true,
                showInternalLabels: false,
                showBranchLengths: false,
                labelShiftX: 0,
                scaleX: 1,
                scaleY: 1,
                fontSize: 12,
                branchWidth: 1,
                branchColor: '#000000',
                dashed: false,
                leafSpacing: 20,
                datasetLaneWidth: 15,
                datasetGap: 2,
                alignLabels: false,
                showGuideLines: true,
                centerOffset: 0
            };
        }

        calculateCoordinates() {
            if (this.settings.mode === 'circular') {
                this._layoutCircular();
            } else if (this.settings.mode === 'unrooted') {
                this._layoutUnrooted();
            } else {
                this._layoutRectangular();
            }
            this._calculateSubtreeBBoxes();
        }

        _calculateSubtreeBBoxes() {
            // Post-order to aggregate BBoxes
            const stack = [this.model.root];
            const resultStack = [];
            while (stack.length > 0) {
                const n = stack.pop();
                resultStack.push(n);
                if (n.children) n.children.forEach(c => stack.push(c));
            }

            while (resultStack.length > 0) {
                const node = resultStack.pop();
                const x = node.isLeaf && this.settings.mode === 'rect' ? node.x : (node.cartX || node.x || 0);
                const y = node.isLeaf && this.settings.mode === 'rect' ? node.y : (node.cartY || node.y || 0);

                let minX = x, minY = y, maxX = x, maxY = y;

                if (node.children && node.children.length > 0) {
                    node.children.forEach(c => {
                        if (c.bbox) {
                            minX = Math.min(minX, c.bbox.minX);
                            minY = Math.min(minY, c.bbox.minY);
                            maxX = Math.max(maxX, c.bbox.maxX);
                            maxY = Math.max(maxY, c.bbox.maxY);
                        }
                    });
                }
                node.bbox = { minX, minY, maxX, maxY };
            }
        }

        _layoutRectangular() {
            const spacing = this.settings.leafSpacing * this.settings.scaleY;
            const currentLeaves = this.model.leaves;

            // 1. Assign leaf Y coordinates
            if (this.settings.invert) {
                currentLeaves.forEach((leaf, i) => {
                    leaf.y = (currentLeaves.length - 1 - i) * spacing;
                });
            } else {
                currentLeaves.forEach((leaf, i) => {
                    leaf.y = i * spacing;
                });
            }

            // 2. Iterative Post-order traversal to calculate internal node positions
            const stack = [this.model.root];
            const resultStack = [];
            while (stack.length > 0) {
                const n = stack.pop();
                resultStack.push(n);
                if (n.children) {
                    n.children.forEach(c => stack.push(c));
                }
            }

            while (resultStack.length > 0) {
                const node = resultStack.pop();
                if (node.isLeaf) {
                    const metric = this.settings.useBranchLengths ? node.heightFromRoot : node.depth;
                    node.x = metric * this.settings.scaleX;
                } else {
                    const childYs = node.children.map(c => c.y);
                    node.y = childYs.reduce((a, b) => a + b, 0) / childYs.length;
                    const metric = this.settings.useBranchLengths ? node.heightFromRoot : node.depth;
                    node.x = metric * this.settings.scaleX;
                }
            }

            const maxD = this.settings.useBranchLengths ? this.model.maxHeight : this.model.maxDepth;
            this.settings.maxLayoutX = maxD * this.settings.scaleX;
            this.canvasWidth = this.settings.maxLayoutX + 400;
            this.canvasHeight = currentLeaves.length * spacing + 100;
        }

        _layoutCircular() {
            const totalLeaves = this.model.getLeafCount();
            const sweepRadians = (this.settings.arc / 360) * 2 * Math.PI;
            const startAngle = (this.settings.rotation / 360) * 2 * Math.PI;
            // Use user-defined offset, default to 0 if not set. 
            // In previous hardcoded logic: (root has 1 child) ? 0 : 25. Now we trust the slider.
            const INNER_RADIUS = this.settings.centerOffset !== undefined ? this.settings.centerOffset : 0;

            // Step 1: Horizontal Scaling affects radial expansion
            let maxRadius = 0;

            // Step 2: Assign angles to leaves (Pre-order already captured in model.leaves)
            const divisor = (this.settings.arc >= 360) ? totalLeaves : (totalLeaves - 1 || 1);
            this.model.leaves.forEach((leaf, i) => {
                leaf.angle = startAngle + (i / divisor) * sweepRadians;
            });

            // Step 3: Iterative Post-order to calculate internal node angles and radii
            const stack = [this.model.root];
            const resultStack = [];
            while (stack.length > 0) {
                const n = stack.pop();
                resultStack.push(n);
                if (n.children) {
                    n.children.forEach(c => stack.push(c));
                }
            }

            while (resultStack.length > 0) {
                const node = resultStack.pop();
                const depth = this.settings.useBranchLengths ? node.heightFromRoot : node.depth;
                node.radius = INNER_RADIUS + (depth * this.settings.scaleX);

                if (!node.isLeaf) {
                    const avgAngle = node.children.reduce((a, b) => a + b.angle, 0) / node.children.length;
                    node.angle = avgAngle;
                }

                node.cartX = node.radius * Math.cos(node.angle);
                node.cartY = node.radius * Math.sin(node.angle);
                if (node.radius > maxRadius) maxRadius = node.radius;
            }

            this.settings.maxLayoutRadius = maxRadius;
            this.canvasWidth = maxRadius * 2 + 300;
            this.canvasHeight = maxRadius * 2 + 300;
            this.settings.maxLayoutRadius = maxRadius;
        }

        _layoutUnrooted() {
            // Fix: Use 0 as default for true unrooted/star view, or user setting
            const INNER_RADIUS = this.settings.centerOffset !== undefined ? this.settings.centerOffset : 0;
            let maxR = 0;

            // 1. Calculate Leaf Counts
            this.model._countLeaves(this.model.root);

            // 2. Generate Ladderized Leaf List
            const sortedLeaves = [];
            const ladderizedDFS = (node) => {
                if (node.isLeaf) {
                    sortedLeaves.push(node);
                    return;
                }
                if (node.children) {
                    const sortedChildren = [...node.children].sort((a, b) => (a.leafCount || 0) - (b.leafCount || 0));
                    sortedChildren.forEach(c => ladderizedDFS(c));
                }
            };
            ladderizedDFS(this.model.root);

            // 3. Assign Angles
            const totalLeaves = sortedLeaves.length;
            const startAngle = 0;
            const sweep = 2 * Math.PI;

            sortedLeaves.forEach((leaf, i) => {
                leaf.angle = startAngle + (i / totalLeaves) * sweep;
            });

            // 4. Internal Nodes (Bottom-Up)
            const stack = [this.model.root];
            const resultStack = [];
            while (stack.length > 0) {
                const n = stack.pop();
                resultStack.push(n);
                if (n.children) n.children.forEach(c => stack.push(c));
            }

            while (resultStack.length > 0) {
                const node = resultStack.pop();
                const depth = this.settings.useBranchLengths ? node.heightFromRoot : node.depth;
                node.radius = INNER_RADIUS + (depth * this.settings.scaleX);

                if (!node.isLeaf && node.children && node.children.length > 0) {
                    let xSum = 0, ySum = 0;
                    let count = 0;
                    node.children.forEach(c => {
                        xSum += Math.cos(c.angle);
                        ySum += Math.sin(c.angle);
                        count++;
                    });

                    if (count > 0 && (Math.abs(xSum) > 1e-6 || Math.abs(ySum) > 1e-6)) {
                        node.angle = Math.atan2(ySum, xSum);
                    } else if (count > 0) {
                        node.angle = node.children[0].angle;
                    }
                }

                node.cartX = node.radius * Math.cos(node.angle);
                node.cartY = node.radius * Math.sin(node.angle);
                if (node.radius > maxR) maxR = node.radius;
            }

            this.settings.maxLayoutRadius = maxR;
            this.canvasWidth = maxR * 2 + 300;
            this.canvasHeight = maxR * 2 + 300;
        }
        /*
        _layoutUnrooted_OLD_Disabled() {
            const INNER_RADIUS = 20;
            let maxR = 0;

            // Pre-calculate leaf counts iteratively
            this.model._countLeaves(this.model.root);

            // Iterative Pre-order to assign angles
            const stack = [{ node: this.model.root, start: 0, end: 2 * Math.PI }];
            while (stack.length > 0) {
                const { node, start, end } = stack.pop();
                const sweep = end - start;
                const depth = this.settings.useBranchLengths ? node.heightFromRoot : node.depth;
                node.radius = INNER_RADIUS + (depth * this.settings.scaleX);
                node.angle = start + sweep / 2;
                node.cartX = node.radius * Math.cos(node.angle);
                node.cartY = node.radius * Math.sin(node.angle);
                if (node.radius > maxR) maxR = node.radius;

                if (node.children && node.children.length > 0) {
                    const totalSubtreeLeaves = node.children.map(c => c.leafCount || 1);
                    const total = totalSubtreeLeaves.reduce((a, b) => a + b, 0);

                    // OPTIMIZATION: Sort children by leaf weight (Ladderize locally) to reduce crossover visual clutter
                    // Combine children with their weights for sorting
                    let indexedChildren = node.children.map((c, idx) => ({ node: c, weight: totalSubtreeLeaves[idx] }));
                    indexedChildren.sort((a, b) => a.weight - b.weight); // Ascending order

                    // Re-assign sorted children to node (temporary for layout, or permanent?)
                    // Permanent is fine for visual stability
                    node.children = indexedChildren.map(x => x.node);
                    // Re-extract weights in new order
                    const sortedWeights = indexedChildren.map(x => x.weight);

                    // Push correctly to maintain clockwise order:
                    let currentPos = start;
                    node.children.forEach((child, i) => {
                        const childSweep = (sortedWeights[i] / total) * sweep;
                        stack.push({ node: child, start: currentPos, end: currentPos + childSweep });
                        currentPos += childSweep;
                    });
                }
            }

            this.canvasWidth = maxR * 2 + 300;
            this.canvasHeight = maxR * 2 + 300;
        } */
    }

    // --- View: SVG Rendering ---
    /**
     * HybridRenderer: iTOL-grade rendering architecture
     * Layers:
     * 1. Bottom Canvas: High-performance branch drawing
     * 2. Top SVG: Interactive text labels, tooltips and scale bars
     */
    class HybridRenderer {
        constructor(containerId) {
            this.container = document.getElementById(containerId);
            this.canvas = null;
            this.ctx = null;
            this.svg = null;
            this.g = null;
            this.canvasInited = false;
        }

        _initLayers() {
            if (this.canvasInited) return;
            this.container.innerHTML = '';
            this.container.style.position = 'relative';
            this.container.style.overflow = 'hidden';

            // 1. Bottom Canvas
            this.canvas = document.createElement('canvas');
            this.canvas.style.position = 'absolute';
            this.canvas.style.top = '0';
            this.canvas.style.left = '0';
            this.canvas.style.pointerEvents = 'none'; // Passthrough to SVG
            this.ctx = this.canvas.getContext('2d');
            this.container.appendChild(this.canvas);

            // 2. Top SVG
            this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
            this.svg.setAttribute("width", "100%");
            this.svg.setAttribute("height", "100%");
            this.svg.setAttribute("id", "main_svg");
            this.svg.style.position = 'absolute';
            this.svg.style.top = '0';
            this.svg.style.left = '0';
            this.svg.style.background = 'transparent';

            this.g = document.createElementNS("http://www.w3.org/2000/svg", "g");
            this.g.setAttribute("id", "dataset_grp");
            this.svg.appendChild(this.g);
            this.container.appendChild(this.svg);

            this.resizeHandler = () => this.resize();
            window.addEventListener('resize', this.resizeHandler);
            this.canvasInited = true;
            this.resize();
        }

        dispose() {
            if (this.resizeHandler) {
                window.removeEventListener('resize', this.resizeHandler);
                this.resizeHandler = null;
            }
            if (this.container) {
                this.container.innerHTML = ''; // Clean up DOM
            }
        }

        resize() {
            if (!this.container || !this.canvas) return;
            this.canvas.width = this.container.clientWidth;
            this.canvas.height = this.container.clientHeight;

            // Sync current matrix center for Unrooted/Circular if view changed size
            // Note: This optional step keeps the tree centered.
            // But strict "misalignment" fix just needs canvas.width update.

            if (this.lastArgs) this.render(...this.lastArgs);
        }

        render(model, settings, layoutDim, persistentMatrix) {
            this.lastArgs = arguments;
            if (!this.container) return;
            this._initLayers();

            var mode = settings.mode;
            var matrix = instance.currentMatrix || { a: 1, b: 0, c: 0, d: 1, e: 20, f: 20 };
            instance.currentMatrix = matrix; // Ensure sync

            // Reset SVG labels
            this.g.innerHTML = '';
            this.g.setAttribute("transform", `matrix(${matrix.a},0,0,${matrix.d},${matrix.e},${matrix.f})`);

            // Coordinate System Shift for Circular
            let offsetX = 0, offsetY = 0;
            if (mode === 'circular' || mode === 'unrooted') {
                offsetX = this.canvas.width / 2;
                offsetY = this.canvas.height / 2;
                this.svg.setAttribute("viewBox", `${-this.canvas.width / 2} ${-this.canvas.height / 2} ${this.canvas.width} ${this.canvas.height}`);
            } else {
                this.svg.setAttribute("viewBox", `0 0 ${this.canvas.width} ${this.canvas.height}`);
            }

            // --- ZOOM & PAN (Attached to SVG for interaction) ---
            var self = this;
            this.svg.onwheel = function (e) {
                e.preventDefault();
                var scaleFactor = e.deltaY > 0 ? 0.9 : 1.1;
                var pt = self.svg.createSVGPoint();
                pt.x = e.clientX; pt.y = e.clientY;
                var cursor = pt.matrixTransform(self.svg.getScreenCTM().inverse());

                matrix.e = cursor.x - (cursor.x - matrix.e) * scaleFactor;
                matrix.f = cursor.y - (cursor.y - matrix.f) * scaleFactor;
                matrix.a *= scaleFactor;
                matrix.d *= scaleFactor;

                self.updateTransform(matrix, settings);
                instance.saveState();
            };

            // --- Pan Handling (Middle Click OR Space+Left Click) ---
            var isDragging = false, startX, startY;

            // Helper to check if pan condition is met
            const isPanStart = (e) => {
                // Middle click (button 1) OR (Left click (button 0) AND Space is pressed)
                return e.button === 1 || (e.button === 0 && e.getModifierState && e.getModifierState('Space')) || (e.button === 0 && keysPressed[' ']);
            };

            // Global Key Tracker for Space (since getModifierState('Space') isn't always reliable on all browsers/OS)
            var keysPressed = {};
            window.addEventListener('keydown', (e) => { keysPressed[e.key] = true; if (e.key === ' ' && !isDragging) this.svg.style.cursor = "grab"; });
            window.addEventListener('keyup', (e) => { delete keysPressed[e.key]; if (e.key === ' ' && !isDragging) this.svg.style.cursor = "default"; });

            this.svg.onmousedown = (e) => {
                if (isPanStart(e)) {
                    isDragging = true;
                    startX = e.clientX;
                    startY = e.clientY;
                    this.svg.style.cursor = "grabbing";
                    e.preventDefault(); // Prevent text selection or other default behaviors
                }
            };

            this.svg.onmousemove = (e) => {
                // Change cursor hint when space is held
                if (!isDragging) {
                    this.svg.style.cursor = (keysPressed[' ']) ? "grab" : "default";
                    return;
                }

                matrix.e += (e.clientX - startX);
                matrix.f += (e.clientY - startY);
                startX = e.clientX; startY = e.clientY;
                self.updateTransform(matrix, settings);
                instance.saveState();
            };

            this.svg.onmouseup = (e) => {
                if (isDragging) {
                    isDragging = false;
                    this.svg.style.cursor = (keysPressed[' ']) ? "grab" : "default";
                }
            };

            this.svg.onmouseleave = () => {
                if (isDragging) {
                    isDragging = false;
                    this.svg.style.cursor = "default";
                }
            };

            this.svg.style.cursor = "default";

            // --- ACTUAL DRAWING ---
            // --- ACTUAL DRAWING ---
            this._drawEdgesCanvas(model.root, settings, matrix, offsetX, offsetY);

            if (settings.showLabels) {
                this._drawLabels(model.root, this.g, settings);
            }

            // Draw datasets AFTER labels to use the calculated maxLabelEndRadius for concentric rings
            this._drawDatasetsCanvas(model, settings, matrix, offsetX, offsetY);

            this.updateScaleBar(settings, matrix.a);
        }

        updateTransform(matrix, settings) {
            this.g.setAttribute("transform", `matrix(${matrix.a},0,0,${matrix.d},${matrix.e},${matrix.f})`);
            this.updateScaleBar(settings, matrix.a);

            const model = instance.model;
            let offsetX = 0, offsetY = 0;
            if (settings.mode === 'circular' || settings.mode === 'unrooted') {
                offsetX = this.canvas.width / 2;
                offsetY = this.canvas.height / 2;
            }

            // Redraw branches on canvas with new transform
            this._drawEdgesCanvas(model.root, settings, matrix, offsetX, offsetY);
            // Datasets might need re-calc if labels changed, but usually transform is enough? 
            // Actually labels track zoom, so maxLabelEndRadius is stable in local coords? 
            // Wait, maxLabelEndRadius is calculated in LOCAL coords (pre-transform) in _drawLabels?
            // Let's check _drawLabels again. Use s.maxLayoutRadius vs current.radius. 
            // Yes, it uses layout coords. So it is stable under Pan/Zoom.
            this._drawDatasetsCanvas(model, settings, matrix, offsetX, offsetY);
        }

        _drawEdgesCanvas(node, s, m, ox, oy) {
            if (!this.ctx) return;
            const ctx = this.ctx;
            // CRITICAL: Reset transform logic to identity before clearing
            // This prevents smearing if previous frame left a dirty state
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

            ctx.save();
            ctx.setTransform(m.a, 0, 0, m.d, m.e + ox, m.f + oy);
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';

            // Viewport in local coordinates for culling
            const vMinX = (0 - (m.e + ox)) / m.a;
            const vMaxX = (this.canvas.width - (m.e + ox)) / m.a;
            const vMinY = (0 - (m.f + oy)) / m.d;
            const vMaxY = (this.canvas.height - (m.f + oy)) / m.d;

            const stack = [node];
            while (stack.length > 0) {
                const current = stack.pop();
                if (!current) continue;

                // Frustum Culling
                if (current.bbox) {
                    if (current.bbox.maxX < vMinX || current.bbox.minX > vMaxX ||
                        current.bbox.maxY < vMinY || current.bbox.minY > vMaxY) {
                        continue;
                    }
                }

                if (current.children) {
                    current.children.forEach(child => {
                        const cx = s.mode === 'rect' ? current.x : current.cartX;
                        const cy = s.mode === 'rect' ? current.y : current.cartY;
                        const chx = s.mode === 'rect' ? child.x : child.cartX;
                        const chy = s.mode === 'rect' ? child.y : child.cartY;

                        const screenDist = Math.abs(chx - cx) * m.a + Math.abs(chy - cy) * m.d;
                        const isUltraSmall = screenDist < 0.5;

                        ctx.beginPath();
                        ctx.strokeStyle = child.color || current.color || s.branchColor || "#000";
                        ctx.lineWidth = s.branchWidth || 1;
                        if (s.dashed) ctx.setLineDash([4, 2]); else ctx.setLineDash([]);

                        if (isUltraSmall) {
                            ctx.moveTo(cx, cy);
                            ctx.lineTo(chx, chy);
                        } else if (s.mode === 'circular' || s.mode === 'unrooted') {
                            if (s.mode === 'circular' && s.branchStyle === 'square') {
                                ctx.moveTo(current.cartX, current.cartY);
                                ctx.arc(0, 0, current.radius, current.angle, child.angle, child.angle < current.angle);
                                ctx.lineTo(child.cartX, child.cartY);
                            } else {
                                ctx.moveTo(current.cartX, current.cartY);
                                ctx.lineTo(child.cartX, child.cartY);
                            }
                        } else {
                            if (s.branchStyle === 'slanted') {
                                ctx.moveTo(current.x, current.y);
                                ctx.lineTo(child.x, child.y);
                            } else if (s.branchStyle === 'curved') {
                                ctx.moveTo(current.x, current.y);
                                ctx.bezierCurveTo(current.x, current.y, current.x, child.y, child.x, child.y);
                            } else {
                                ctx.moveTo(current.x, current.y);
                                ctx.lineTo(current.x, child.y);
                                ctx.lineTo(child.x, child.y);
                            }
                        }
                        ctx.stroke();

                        // LOD for labels
                        if (m.a > 0.5) {
                            if (s.showBranchLengths && child.branch_length !== undefined) this._drawBranchValueCanvas(current, child, s);
                        }
                        stack.push(child);
                    });
                }
            }

            // --- DRAW ROOT STEM ---
            // If the root has a length (independent root), we need to draw the line connecting to the "origin"
            // FIX: Access root via instance.model or pass it. node is usually root, but let's be safe.
            const root = (typeof instance !== 'undefined' && instance.model) ? instance.model.root : node;

            if (root && root.branch_length > 0) {
                ctx.beginPath();
                ctx.strokeStyle = root.color || s.branchColor || "#000";
                ctx.lineWidth = s.branchWidth || 1;

                // Coordinates of the Root Node
                const rx = s.mode === 'rect' ? root.x : root.cartX;
                const ry = s.mode === 'rect' ? root.y : root.cartY;

                if (s.mode === 'rect') {
                    // Stem starts at (rx - len, ry)
                    // Note: rx already includes the length because of _processTree update
                    // FIX: use 's' (settings) instead of 'this.settings'
                    const stemStart = (rx - root.branch_length * s.scaleX);
                    ctx.moveTo(stemStart, ry);
                    ctx.lineTo(rx, ry);
                } else if (s.mode === 'circular' || s.mode === 'unrooted') {
                    // Circular: Root Node is at some radius. Stem starts at Center (0,0) or (INNER_RADIUS?)
                    // If Offset is used, it adds hole.
                    // Logic: Stem connects "Logical Origin" to Root Node.
                    // In Circular, Origin is (0,0). 
                    ctx.moveTo(0, 0);
                    ctx.lineTo(rx, ry);
                }
                ctx.stroke();
            }

            ctx.restore();
        }

        getExportSVGString(model, s, m) {
            let svgContent = "";

            // SVG Transform Note:
            // For Rectangular: viewBox="0 0 W H". Origin is Top-Left. Canvas & SVG match.
            // For Circular: viewBox="-W/2 -H/2 W H". Origin is Center.
            // Canvas uses Top-Left origin + (W/2, H/2) offset.
            // SVG uses Center origin.
            // Thus, we do NOT need to add (W/2, H/2) to the translation 'e, f' for SVG export.
            // Just using the matrix translation is correct for both cases relative to their viewBox.

            // Group for tree structure
            svgContent += `<g id="tree_structure" transform="matrix(${m.a},0,0,${m.d},${m.e},${m.f})">`;

            const fmt = (n) => n.toFixed(2);

            const stack = [model.root];
            while (stack.length > 0) {
                const current = stack.pop();
                if (!current) continue;

                if (current.children) {
                    current.children.forEach(child => {
                        const cx = s.mode === 'rect' ? current.x : current.cartX;
                        const cy = s.mode === 'rect' ? current.y : current.cartY;
                        const chx = s.mode === 'rect' ? child.x : child.cartX;
                        const chy = s.mode === 'rect' ? child.y : child.cartY;

                        let pathD = "";

                        if (s.mode === 'circular' && s.branchStyle === 'square') {
                            const r = current.radius;
                            const startAngle = current.angle;
                            const endAngle = child.angle;

                            const arcEndCompX = r * Math.cos(endAngle);
                            const arcEndCompY = r * Math.sin(endAngle);

                            // Calculate flags
                            let delta = endAngle - startAngle;
                            const ccw = child.angle < current.angle;
                            const sweep = ccw ? 0 : 1;
                            const large = Math.abs(delta) > Math.PI ? 1 : 0;

                            pathD = `M ${fmt(cx)} ${fmt(cy)} A ${fmt(r)} ${fmt(r)} 0 ${large} ${sweep} ${fmt(arcEndCompX)} ${fmt(arcEndCompY)} L ${fmt(chx)} ${fmt(chy)}`;

                        } else if (s.mode === 'rect') {
                            if (s.branchStyle === 'slanted') {
                                pathD = `M ${fmt(cx)} ${fmt(cy)} L ${fmt(chx)} ${fmt(chy)}`;
                            } else if (s.branchStyle === 'curved') {
                                pathD = `M ${fmt(cx)} ${fmt(cy)} C ${fmt(cx)} ${fmt(cy)}, ${fmt(cx)} ${fmt(chy)}, ${fmt(chx)} ${fmt(chy)}`;
                            } else {
                                // Square
                                pathD = `M ${fmt(cx)} ${fmt(cy)} L ${fmt(cx)} ${fmt(chy)} L ${fmt(chx)} ${fmt(chy)}`;
                            }
                        } else {
                            // Unrooted / Circular Linear
                            pathD = `M ${fmt(cx)} ${fmt(cy)} L ${fmt(chx)} ${fmt(chy)}`;
                        }

                        const color = child.color || current.color || s.branchColor || "#000";
                        const width = s.branchWidth || 1;
                        const dash = s.dashed ? 'stroke-dasharray="4,2"' : '';

                        svgContent += `<path d="${pathD}" stroke="${color}" stroke-width="${width}" fill="none" ${dash} stroke-linecap="round" stroke-linejoin="round"/>`;

                        stack.push(child);
                    });
                }
            }

            // Draw Root Stem
            if (model.root && model.root.branch_length > 0) {
                const root = model.root;
                const rx = s.mode === 'rect' ? root.x : root.cartX;
                const ry = s.mode === 'rect' ? root.y : root.cartY;
                let stemD = "";

                if (s.mode === 'rect') {
                    const stemStart = (rx - root.branch_length * s.scaleX);
                    stemD = `M ${fmt(stemStart)} ${fmt(ry)} L ${fmt(rx)} ${fmt(ry)}`;
                } else {
                    stemD = `M 0 0 L ${fmt(rx)} ${fmt(ry)}`;
                }
                const color = root.color || s.branchColor || "#000";
                const width = s.branchWidth || 1;
                svgContent += `<path d="${stemD}" stroke="${color}" stroke-width="${width}" fill="none"/>`;
            }

            svgContent += "</g>";
            return svgContent;
        }

        _drawMetaLabelCanvas(node, s) {
            const ctx = this.ctx;
            ctx.font = `bold ${(s.fontSize * 0.7)}px Arial`;
            ctx.fillStyle = "#64748b";
            if (s.mode === 'rect') {
                ctx.textAlign = 'right';
                ctx.fillText(node.name, node.x - 5, node.y - 5);
            } else {
                var tx = node.cartX + 5 * Math.cos(node.angle);
                var ty = node.cartY + 5 * Math.sin(node.angle);
                ctx.textAlign = 'left';
                ctx.fillText(node.name, tx, ty);
            }
        }

        _drawBranchValueCanvas(node, child, s) {
            const ctx = this.ctx;
            ctx.font = `${(s.fontSize * 0.6)}px Arial`;
            ctx.fillStyle = "#94a3b8";
            ctx.textAlign = 'center';
            const val = parseFloat(child.branch_length).toFixed(4);
            if (s.mode === 'rect') {
                ctx.fillText(val, (node.x + child.x) / 2, child.y - 3);
            } else {
                ctx.fillText(val, (node.cartX + child.cartX) / 2, (node.cartY + child.cartY) / 2);
            }
        }

        _drawDatasetsCanvas(model, s, m, ox, oy) {
            if (!this.ctx || !model.datasets || model.datasets.length === 0) return;
            const ctx = this.ctx;
            const isRect = s.mode === 'rect';

            // 1. Determine Start Radius / X Offset
            // Use MAX of (Tree Layout Radius) AND (Max Label End Radius)
            // This ensures heatmap is outside BOTH the tree branches AND strings.
            const layoutLimit = isRect ? s.maxLayoutX : s.maxLayoutRadius;
            let currentRadius = Math.max(layoutLimit, this.maxLabelEndRadius || 0);

            // Add a clean buffer (e.g. 20px) to separate from tree/text
            currentRadius += 20;

            const gap = s.datasetGap || 2;
            const width = s.datasetLaneWidth || 15;

            ctx.save();
            // We need to apply transform because we are drawing in world space like edges
            ctx.setTransform(m.a, 0, 0, m.d, m.e + ox, m.f + oy);

            model.datasets.forEach(ds => {
                if (!ds.data) return;

                // Color lookup helper
                const getColor = (val) => {
                    if (ds.type === 'continuous') {
                        // Simple 2-color gradient interpolation
                        // Assuming val is normalized 0-1 or handled elsewhere. 
                        // For now we assume discrete logic for MVP, or exact color map match
                        return ds.colorMap[val] || "#cccccc";
                    }
                    return ds.colorMap[val] || "#cccccc";
                };

                model.leaves.forEach(leaf => {
                    const val = ds.data[leaf.name];
                    if (val === undefined || val === null || val === "") return;

                    ctx.fillStyle = getColor(val);

                    if (isRect) {
                        // Rectangular: Draw simple blocks
                        // X = currentRadius (interpreted as X offset), Y = leaf.y
                        const x = currentRadius;
                        const y = leaf.y - (width / 2); // Center on node Y? No, usually simple stack.
                        // Actually spacing in tree is s.leafSpacing? 
                        // Let's assume height is fixed or dynamic? Fixed for now.
                        const h = Math.max(2, (s.scaleY * 10) || 10); // Heuristic height
                        ctx.fillRect(x, leaf.y - h / 2, width, h);
                    } else {
                        // Circular: Concentric Rings
                        // Inner Radius = currentRadius
                        // Outer Radius = currentRadius + width
                        // Start Angle = leaf.angle - half_step ??
                        // To allow continuous rings, we need to know angle step. 
                        // But we process leaves individually. 
                        // We can just draw arcs centered on leaf.angle

                        // We need to know the angular width allocated to this leaf.
                        // In LayoutEngine, circular layout doesn't explicitly store "wedge size".
                        // But we can estimate or draw thick lines.
                        // Drawing thick ARC segments is better.
                        const totalLeaves = model.leaves.length;
                        const arcPerLeaf = (2 * Math.PI) / totalLeaves; // Approximate if uniform
                        // Better: Draw from (angle - arc/2) to (angle + arc/2)

                        // Let's us stroke with lineWidth. faster.
                        // But stroke is centered on path. 
                        // Path is arc at radius = currentRadius + width/2
                        const rMid = currentRadius + width / 2;

                        ctx.beginPath();
                        ctx.arc(0, 0, rMid, leaf.angle - (arcPerLeaf / 2) * 1.05, leaf.angle + (arcPerLeaf / 2) * 1.05); // 1.05 overlap to prevent cracks
                        ctx.lineWidth = width;
                        ctx.strokeStyle = getColor(val);
                        ctx.stroke();
                    }
                });

                // Advance radius for next dataset
                currentRadius += width + gap;
            });

            ctx.restore();
        }

        _drawLabels(node, group, s) {
            this.maxLabelEndRadius = 0; // Reset max label radius for heatmap
            const m = instance.currentMatrix;
            const ox = (s.mode === 'circular' || s.mode === 'unrooted') ? this.canvas.width / 2 : 0;
            const oy = (s.mode === 'circular' || s.mode === 'unrooted') ? this.canvas.height / 2 : 0;

            // Viewport in local coordinates
            const vMinX = (0 - (m.e + ox)) / m.a;
            const vMaxX = (this.canvas.width - (m.e + ox)) / m.a;
            const vMinY = (0 - (m.f + oy)) / m.d;
            const vMaxY = (this.canvas.height - (m.f + oy)) / m.d;

            const stack = [node];
            const searchQuery = instance.lastSearchQuery;
            let regex = null;
            if (searchQuery) {
                try { regex = new RegExp(searchQuery, 'i'); } catch (e) { }
            }

            while (stack.length > 0) {
                const current = stack.pop();
                if (!current) continue;

                const isSelected = instance.selectedNodeIds.has(current.id);

                // Culling for Labels: Check if node point is somewhat near viewport
                const nx = s.mode === 'rect' ? current.x : current.cartX;
                const ny = s.mode === 'rect' ? current.y : current.cartY;

                const isNearViewport = (nx > vMinX - 500 && nx < vMaxX + 500 && ny > vMinY - 500 && ny < vMaxY + 500);

                // Expanded Visibility Logic: Draw all nodes for interaction (even internal ones)
                // But only draw text labels if name exists and fits visibility settings
                if (isNearViewport) {
                    const groupItem = document.createElementNS("http://www.w3.org/2000/svg", "g");

                    // Determine if we should draw the text label
                    const shouldDrawLabel = (current.name && current.isLeaf) || (s.showInternalLabels && current.name && !current.isLeaf);

                    // Alignment Guide Line (Dashed) - Only for leaves
                    if (shouldDrawLabel && current.isLeaf && s.alignLabels && s.showGuideLines) {
                        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
                        const xStart = (s.mode === 'rect') ? current.x : current.cartX;
                        const yStart = (s.mode === 'rect') ? current.y : current.cartY;
                        let xEnd, yEnd;

                        if (s.mode === 'rect') {
                            xEnd = (s.maxLayoutX || current.x) + 5 + (s.labelShiftX || 0);
                            yEnd = current.y;
                        } else {
                            const alignRadius = (s.maxLayoutRadius || current.radius);
                            xEnd = alignRadius * Math.cos(current.angle);
                            yEnd = alignRadius * Math.sin(current.angle);
                        }
                        line.setAttribute("x1", xStart); line.setAttribute("y1", yStart);
                        line.setAttribute("x2", xEnd); line.setAttribute("y2", yEnd);
                        line.setAttribute("stroke", "#94a3b8"); // Darker color
                        line.setAttribute("stroke-width", "1");
                        line.setAttribute("stroke-dasharray", "3,3");
                        groupItem.appendChild(line);
                    }

                    let isMatch = false;

                    if (shouldDrawLabel) {
                        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
                        text.textContent = current.name;
                        const fontSize = s.fontSize || 10;
                        text.setAttribute("font-size", fontSize + "px");
                        text.setAttribute("font-family", s.fontFamily || "Arial");

                        // Search highlight logic
                        if (current.name && regex) {
                            try { isMatch = regex.test(current.name); } catch (e) { }
                        }

                        text.setAttribute("fill", isMatch ? "#ef4444" : (s.labelColor || "#000"));
                        if (isMatch) {
                            text.setAttribute("font-weight", "bold");
                            text.style.textShadow = "0 0 5px rgba(239, 68, 68, 0.4)";
                        } else {
                            if (s.fontBold) text.setAttribute("font-weight", "bold");
                        }

                        if (s.fontItalic) text.setAttribute("font-style", "italic");

                        if (s.mode === 'rect') {
                            const tx = s.alignLabels && current.isLeaf ? (s.maxLayoutX || current.x) : current.x;
                            text.setAttribute("x", tx + 10 + (s.labelShiftX || 0));
                            text.setAttribute("y", current.y);
                            text.setAttribute("alignment-baseline", "middle");
                            text.setAttribute("text-anchor", "start");
                        } else {
                            let angleDeg = current.angle * (180 / Math.PI);
                            angleDeg = (angleDeg % 360 + 360) % 360;
                            let rotate = angleDeg, anchor = "start";
                            // Only align for leaves
                            let tx = (s.alignLabels && current.isLeaf) ? (s.maxLayoutRadius || current.radius) * Math.cos(current.angle) : current.cartX;
                            let ty = (s.alignLabels && current.isLeaf) ? (s.maxLayoutRadius || current.radius) * Math.sin(current.angle) : current.cartY;
                            const shift = 10 + (s.labelShiftX || 0);
                            tx += shift * Math.cos(current.angle);
                            ty += shift * Math.sin(current.angle);
                            if (angleDeg > 90 && angleDeg < 270) { rotate += 180; anchor = "end"; }
                            text.setAttribute("x", tx); text.setAttribute("y", ty);
                            text.setAttribute("text-anchor", anchor);
                            text.setAttribute("transform", `rotate(${rotate}, ${tx}, ${ty})`);
                            text.setAttribute("alignment-baseline", "middle");
                        }

                        // --- Track Max Radius/X for Heatmaps ---
                        let textWidth = 0;
                        if (instance.ctx) { // Use instance.ctx or this.ctx depending on scope. this.ctx is available in TreeEngine methods.
                            // However, inside forEach/while, verify 'this'. 
                            // method _drawLabels is called with 'this' bound? Yes.
                            this.ctx.font = (s.fontBold ? "bold " : "") + (s.fontItalic ? "italic " : "") + fontSize + "px " + (s.fontFamily || "Arial");
                            textWidth = this.ctx.measureText(current.name).width;
                        } else {
                            textWidth = current.name.length * (fontSize * 0.6);
                        }

                        // Calculate End Position based on Mode
                        let currentEndPos = 0;
                        if (s.mode === 'rect') {
                            // Rect Mode: Use X coordinate
                            const tx = s.alignLabels && current.isLeaf ? (s.maxLayoutX || current.x) : current.x;
                            currentEndPos = tx + 10 + (s.labelShiftX || 0) + textWidth;
                        } else {
                            // Circular/Unrooted Mode: Use Radius
                            let baseRadius = current.radius;
                            if (s.mode === 'circular' && s.alignLabels && current.isLeaf) {
                                baseRadius = s.maxLayoutRadius || current.radius;
                            }
                            currentEndPos = baseRadius + 10 + (s.labelShiftX || 0) + textWidth;
                        }

                        if (currentEndPos > this.maxLabelEndRadius) {
                            this.maxLabelEndRadius = currentEndPos;
                        }
                        groupItem.appendChild(text);
                    } else {
                        // Check match for hidden nodes too (in case user searches for ID)
                        if (current.name && regex) {
                            try { isMatch = regex.test(current.name); } catch (e) { }
                        }
                    }

                    // Interaction Layer
                    const hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                    hit.setAttribute("cx", s.mode === 'rect' ? current.x : current.cartX);
                    hit.setAttribute("cy", s.mode === 'rect' ? current.y : current.cartY);
                    hit.setAttribute("r", isMatch ? "8" : "5");
                    hit.setAttribute("fill", isMatch ? "rgba(239, 68, 68, 0.2)" : (isSelected ? "rgba(255, 0, 150, 0.3)" : "transparent"));
                    if (isSelected) {
                        hit.setAttribute("stroke", "#ff0096");
                        hit.setAttribute("stroke-width", "2");
                    }
                    hit.style.cursor = "pointer";

                    // Support for the new High-End Tooltip System
                    hit.onmouseenter = (e) => {
                        if (window.TooltipFix) {
                            let helpText = `<strong>${current.name || '内部节点'}</strong>`;
                            if (current.branchLength !== undefined) helpText += `<br/>分支长度: <code>${current.branchLength.toFixed(4)}</code>`;
                            if (current.bootstrap !== undefined) helpText += `<br/>置信度: <code>${current.bootstrap}</code>`;
                            if (current.isLeaf) helpText += `<br/>类型: <em>叶节点</em>`;

                            window.TooltipFix.show(hit, helpText);
                            // console.log("Showing tooltip for", current.name);
                        } else {
                            console.warn("TooltipFix not found!");
                        }
                    };
                    hit.onmouseleave = () => {
                        if (window.TooltipFix) {
                            window.TooltipFix.hide();
                        }
                    };

                    hit.onclick = (e) => {
                        e.stopPropagation();

                        // Select Logic
                        if (!e.ctrlKey && !e.metaKey) {
                            instance.selectedNodeIds.clear();
                        }

                        if (instance.selectedNodeIds.has(current.id)) {
                            instance.selectedNodeIds.delete(current.id);
                        } else {
                            instance.selectedNodeIds.add(current.id);
                        }

                        // Visual update
                        instance.update();

                        // Notify UI for Floating Toolbar
                        if (window.updateFloatingToolbar) window.updateFloatingToolbar();
                    };
                    groupItem.appendChild(hit);
                    group.appendChild(groupItem);
                }
                if (current.children) {
                    for (let i = current.children.length - 1; i >= 0; i--) {
                        stack.push(current.children[i]);
                    }
                }
            }
        }

        _drawDatasetsCanvas(model, s, m, ox, oy) {
            if (!this.ctx || !model.datasets || model.datasets.length === 0) return;
            const ctx = this.ctx;
            const isRect = s.mode === 'rect';

            // 1. Determine Start Radius / X Offset
            const layoutLimit = isRect ? s.maxLayoutX : s.maxLayoutRadius;
            // Use MeasureText result from previous pass (maxLabelEndRadius)
            let currentRadius = Math.max(layoutLimit || 0, this.maxLabelEndRadius || 0);
            currentRadius += 20; // Safe buffer

            const gap = s.datasetGap || 2;
            const width = s.datasetLaneWidth || 15;

            ctx.save();
            ctx.setTransform(m.a, 0, 0, m.d, m.e + ox, m.f + oy);

            model.datasets.forEach(ds => {
                // Color lookup helper (locally scoped or use global if available)
                // Re-using simple logic for demo

                model.leaves.forEach(leaf => {
                    const val = ds.data[leaf.name];
                    // Allow 0 or empty string as valid data, only skip undefined/null
                    if (val === undefined || val === null) return;

                    const color = (ds.colorMap && ds.colorMap[val]) ? ds.colorMap[val] : "#cbd5e1";

                    ctx.fillStyle = color;

                    if (isRect) {
                        ctx.fillRect(currentRadius, leaf.y - width / 2, width, (s.scaleY * 10) || 10);
                    } else {
                        // Circular: Use GLOBAL currentRadius for perfect concentricity
                        // Do NOT use leaf.radius here.
                        const rIn = currentRadius;
                        const rOut = rIn + width;

                        // Calculate arc segment
                        const totalLeaves = model.leaves.length;
                        const arcPerLeaf = (2 * Math.PI) / totalLeaves;

                        ctx.beginPath();
                        // Overlap slightly (1.05) to avoid gaps
                        ctx.arc(0, 0, rIn, leaf.angle - arcPerLeaf / 2 * 1.05, leaf.angle + arcPerLeaf / 2 * 1.05);
                        ctx.arc(0, 0, rOut, leaf.angle + arcPerLeaf / 2 * 1.05, leaf.angle - arcPerLeaf / 2 * 1.05, true);
                        ctx.fill();
                    }
                });

                // Advance radius for next dataset layer
                currentRadius += width + gap;
            });

            ctx.restore();
        }

        updateScaleBar(s, zoom) {
            const container = document.getElementById('scale-bar-container');
            const line = document.getElementById('scale-bar-line');
            const text = document.getElementById('scale-bar-text');
            if (!container || !line || !text) return;
            const totalScale = (s.scaleX || 1) * zoom;
            if (isNaN(totalScale) || totalScale <= 0) { container.style.display = 'none'; return; }
            container.style.display = 'block';
            const minPx = 80, maxPx = 120;
            let barValue = Math.pow(10, Math.floor(Math.log10(minPx / totalScale)));
            const candidates = [1, 2, 5, 10, 20, 50, 100];
            let bestVal = barValue;
            for (let mult of candidates) {
                let current = barValue * mult;
                if (current * totalScale >= minPx) { bestVal = current; break; }
            }
            const barWidth = bestVal * totalScale;
            line.style.width = Math.min(200, barWidth) + "px";
            let valStr = bestVal.toString();
            if (bestVal < 0.0001) valStr = bestVal.toExponential(2);
            else if (valStr.length > 10) valStr = bestVal.toFixed(6).replace(/\.?0+$/, "");
            text.textContent = "Scale: " + valStr;
        }
    }

    // --- Main Controller ---
    var instance = {
        model: new TreeModel(),
        layout: null,
        renderer: null,
        selectedNodeIds: new Set(),
        lastSearchQuery: "",

        // Helper to send logs to Python backend
        logToSystem: function (msg) {
            console.log(msg); // Keep console for browser devtools

            // Try local bridge first
            if (window.py_bridge && typeof window.py_bridge.on_js_log === 'function') {
                window.py_bridge.on_js_log(msg);
                return;
            }

            // Try parent bridge (IFrame support)
            if (window.parent && window.parent.py_bridge && typeof window.parent.py_bridge.on_js_log === 'function') {
                window.parent.py_bridge.on_js_log(msg);
            }
        },

        init: function (containerId, newickStr) {
            this.logToSystem("[TreeEngine] Initializing with " + (newickStr ? newickStr.length : 0) + " bytes of data");
            this.model = new TreeModel();
            try {
                if (this.model.parse(newickStr)) {
                    this.logToSystem("[TreeEngine] Parse Success! Leaves: " + this.model.getLeafCount());
                    this.model.datasets = []; // Initialize

                    // Default sort for better initial view
                    this.model.ladderize('desc');

                    this.layout = new LayoutEngine(this.model);

                    // Fix: Dispose old renderer to prevent ghost event listeners
                    if (this.renderer && this.renderer.dispose) {
                        this.renderer.dispose();
                    }
                    this.renderer = new HybridRenderer(containerId);
                    if (this.renderer.container) this.renderer._initLayers(); // Fix: Ensure canvas exists before autoFit

                    // Try to restore previous session state
                    const hasSaved = this.loadState();

                    if (!hasSaved) {
                        this.currentMatrix = { a: 1, b: 0, c: 0, d: 1, e: 20, f: 20 };
                        this.autoFit();
                    }

                    this.update();
                    this.bindUI();

                    this.logToSystem("[TreeEngine] Render complete validation.");
                } else {
                    var err = "Model parse returned null!";
                    this.logToSystem("[TreeEngine Error] " + err);
                    alert(err); // Keep alert for critical failures
                }
            } catch (e) {
                var errMsg = "TreeEngine Init Error: " + e.message;
                this.logToSystem(errMsg);
                console.error(e);
                alert("Engine Error: " + e.message);
            }
        },

        autoFit: function () {
            if (!this.layout || !this.renderer || !this.renderer.container) return;

            const containerWidth = this.renderer.container.clientWidth || 800;
            const containerHeight = this.renderer.container.clientHeight || 600;
            const maxDepth = this.layout.settings.useBranchLengths ? this.model.maxHeight : this.model.maxDepth;
            const leafCount = this.model.getLeafCount();

            if (maxDepth > 0) {
                // 1. Horizontal Scale
                let targetWidth = containerWidth * 0.5; // Aim to leave room for labels
                this.layout.settings.scaleX = Math.max(1, Math.min(5000, targetWidth / maxDepth));

                // 2. Vertical Proportions (only for rectangular)
                if (this.layout.settings.mode === 'rect') {
                    const targetHeight = containerHeight * 0.8;
                    const idealSpacing = Math.max(5, Math.min(40, targetHeight / leafCount));
                    this.layout.settings.scaleY = idealSpacing / 20;

                    const scaleYSlider = document.getElementById('internalScaleY');
                    if (scaleYSlider) {
                        scaleYSlider.value = this.layout.settings.scaleY;
                        const valY = document.getElementById('valScaleY');
                        if (valY) valY.innerText = parseFloat(scaleYSlider.value).toFixed(1);
                    }
                }

                // 3. Adaptive Line Width & Font Size
                const densityFactor = Math.max(1, Math.sqrt(leafCount));
                this.layout.settings.branchWidth = parseFloat(Math.max(0.5, Math.min(2.5, 10 / densityFactor)).toFixed(1));
                this.layout.settings.fontSize = parseFloat(Math.max(6, Math.min(14, 50 / densityFactor)).toFixed(1));

                // Update UI Inputs
                const syncValue = (id, val) => {
                    const el = document.getElementById(id);
                    if (el) el.value = val;
                };

                syncValue('internalScaleTimeScaling', (this.layout.settings.scaleX / (this.layout.settings.mode === 'rect' ? 1.5 : 10)).toFixed(1)); // Heuristic sync
                syncValue('lineWidth', this.layout.settings.branchWidth);
                syncValue('fontSize', this.layout.settings.fontSize);

                // 4. Transform Reset to Frame the tree
                // 4. Transform Reset to Frame the tree
                const mode = this.layout.settings.mode;
                const canvasW = this.renderer.canvas.width;
                const canvasH = this.renderer.canvas.height;

                if (mode === 'rect') {
                    // Calculate tree dimensions in pixel space
                    // Height = number of leaves * spacing (which is scaleY*20)
                    const rawHeight = leafCount * 20;
                    const pixelHeight = rawHeight * this.layout.settings.scaleY;

                    // Width = maxDepth * scaleX
                    const pixelWidth = maxDepth * this.layout.settings.scaleX;

                    // Center vertically: (ContainerH - TreeH) / 2
                    // Center horizontally: (ContainerW - TreeW) / 2
                    // Clamp to min padding of 40 to avoid top-left cut-off
                    const centerY = (canvasH - pixelHeight) / 2;
                    const targetF = Math.max(40, centerY);

                    const centerX = (canvasW - pixelWidth) / 2;
                    const targetE = Math.max(40, centerX);

                    // console.log(`[AutoFit] W:${canvasW} H:${canvasH} TreeW:${pixelWidth} TreeH:${pixelHeight} => E:${targetE} F:${targetF}`);

                    this.currentMatrix = { a: 1, b: 0, c: 0, d: 1, e: targetE, f: targetF };
                } else {
                    // Tree origin (0,0) is at canvas center. We want it at container center.
                    this.currentMatrix = {
                        a: 1, b: 0, c: 0, d: 1,
                        e: (containerWidth / 2) - (canvasW / 2),
                        f: (containerHeight / 2) - (canvasH / 2)
                    };
                }

                this.logToSystem("[TreeEngine] Auto-fit invoked. Mode: " + mode + " Matrix reset.");
            }
            this.update();
        },

        lastSearchQuery: '',
        isUpdating: false,

        search: function (query) {
            this.lastSearchQuery = query;
            if (!query) {
                this._fastUpdate();
                return;
            }

            let regex = null;
            try { regex = new RegExp(query, 'i'); } catch (e) { regex = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'); }

            const matches = this.model.leaves.filter(leaf => regex.test(leaf.name));
            if (matches.length > 0) {
                const isRect = this.layout.settings.mode === 'rect';
                const avgX = matches.reduce((sum, m) => sum + (isRect ? m.x : m.cartX), 0) / matches.length;
                const avgY = matches.reduce((sum, m) => sum + (isRect ? m.y : m.cartY), 0) / matches.length;

                const container = this.renderer.container;
                let targetE, targetF;

                if (isRect) {
                    targetE = (container.clientWidth / 2) - avgX * this.currentMatrix.a;
                    targetF = (container.clientHeight / 2) - avgY * this.currentMatrix.d;
                } else {
                    // Circular/Unrooted have origin at center
                    targetE = -avgX * this.currentMatrix.a;
                    targetF = -avgY * this.currentMatrix.d;
                }

                let startE = this.currentMatrix.e;
                let startF = this.currentMatrix.f;
                let startTime = null;

                const animate = (timestamp) => {
                    if (!startTime) startTime = timestamp;
                    const progress = Math.min(1, (timestamp - startTime) / 400);
                    const eased = progress < 0.5 ? 2 * progress * progress : -1 + (4 - 2 * progress) * progress;

                    this.currentMatrix.e = startE + (targetE - startE) * eased;
                    this.currentMatrix.f = startF + (targetF - startF) * eased;

                    this._fastUpdate();
                    if (progress < 1) requestAnimationFrame(animate);
                };
                requestAnimationFrame(animate);
            } else {
                this._fastUpdate();
            }
        },

        // Fast update for animations to avoid state scraping/saving overhead
        _fastUpdate: function () {
            if (!this.layout || !this.renderer) return;
            this.layout.calculateCoordinates();
            this.renderer.render(this.model, this.layout.settings, null, this.currentMatrix);
        },



        update: function () {
            if (!this.layout || this.isUpdating) return;
            this.isUpdating = true;

            requestAnimationFrame(() => {
                if (this.layout.settings.mode === 'circular') {
                    const arcVal = this.layout.settings.arc || 350;
                    const valArcLabel = document.getElementById('valArc');
                    if (valArcLabel) valArcLabel.innerText = arcVal + "°";
                }

                this.layout.calculateCoordinates();
                this.renderer.render(this.model, this.layout.settings, null, this.currentMatrix);

                if (this.layout.settings.useBranchLengths) {
                    this.renderer.updateScaleBar(this.layout.settings, this.currentMatrix.a);
                }
                this.saveState();
                this.isUpdating = false;
            });
        },

        saveState: function () {
            // Persistence disabled per user request
            // if (!this.layout) return;
            // try {
            //     const state = {
            //         settings: this.layout.settings,
            //         matrix: this.currentMatrix
            //     };
            //     localStorage.setItem('tree_explorer_v1_state', JSON.stringify(state));
            // } catch (e) {
            //     console.warn("Failed to save state to localStorage", e);
            // }
        },

        loadState: function () {
            // Persistence disabled per user request
            return false;
            /*
           try {
               const saved = localStorage.getItem('tree_explorer_v1_state');
               if (saved) {
                   const state = JSON.parse(saved);
                   if (state.settings && this.layout) {
                       // Merge saved settings into current settings
                       Object.assign(this.layout.settings, state.settings);
                   }
                   if (state.matrix) {
                       this.currentMatrix = state.matrix;
                   }
                   return true;
               }
           } catch (e) {
               console.warn("Failed to load state from localStorage", e);
           }
           return false;
           */
        },

        sort: function (direction) {
            if (this.model) {
                this.model.ladderize(direction);
                this.update();
            }
        },

        setMode: function (mode) {
            if (!this.layout) return;
            this.layout.settings.mode = mode;

            // UI Label consistency is now handled by static HTML + dedicated Arc slider

            // Sync Styles: Circular/Unrooted don't support "Curved" well
            const curvedBtn = document.getElementById('styleCurved');
            if (curvedBtn) {
                if (mode !== 'rect') {
                    curvedBtn.disabled = true;
                    curvedBtn.style.opacity = "0.4";
                    curvedBtn.style.cursor = "not-allowed";
                    curvedBtn.title = "仅矩形模式可用";
                    if (this.layout.settings.branchStyle === 'curved') {
                        // Reset to square if curved was active
                        document.getElementById('styleSquare').click();
                    }
                } else {
                    curvedBtn.disabled = false;
                    curvedBtn.style.opacity = "1";
                    curvedBtn.style.cursor = "pointer";
                    curvedBtn.title = "";
                }
            }
            this.autoFit();
        },

        bindUI: function () {
            var self = this;
            if (!this.layout) return;
            var s = this.layout.settings;

            function bind(selector, settingKey, isInt = false) {
                const el = document.querySelector(selector);
                if (el) el.addEventListener('input', function () {
                    let val = isInt ? parseFloat(this.value) : this.value;
                    // Force 1 decimal place for width and font size
                    if (isInt && (settingKey === 'branchWidth' || settingKey === 'fontSize')) {
                        val = parseFloat(val.toFixed(1));
                    }
                    s[settingKey] = val;
                    self.update();
                });
            }

            bind('#rotation', 'rotation', true);
            bind('#fontSize', 'fontSize', true);
            bind('#fontName', 'fontFamily');
            bind('#labelShift', 'labelShiftX', true);
            bind('#centerOffset', 'centerOffset', true);
            bind('#lineWidth', 'branchWidth', true);
            bind('#lineWidth', 'branchWidth', true);
            bind('#defaultBranchColor', 'branchColor');
            bind('#arc', 'arc', true);

            const scaleXEl = document.getElementById('internalScaleTimeScaling');
            if (scaleXEl) scaleXEl.addEventListener('input', function () {
                s.scaleX = parseFloat(this.value) * 1.5;
                self.update();
            });

            const scaleYEl = document.getElementById('internalScaleY');
            if (scaleYEl) scaleYEl.addEventListener('input', function () {
                s.scaleY = parseFloat(this.value);
                self.update();
            });

            function bindToggleGroup(btnIds, settingKey, valueMap) {
                btnIds.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.addEventListener('click', function () {
                        s[settingKey] = valueMap[id];
                        btnIds.forEach(otherId => {
                            const other = document.getElementById(otherId);
                            if (other) other.classList.remove('active');
                        });
                        this.classList.add('active');
                        self.update();
                    });
                });
            }

            // --- New PT-Switch Handlers (Class-Based) ---
            const switchMapping = {
                'checkShowLabels': 'showLabels',
                'checkShowInternal': 'showInternalLabels',
                'checkAlignLabels': 'alignLabels',
                'checkShowGuideLines': 'showGuideLines',
                'checkShowBrLen': 'showBranchLengths',
                'checkUseBrLen': 'useBranchLengths',
                'checkInvert': 'invert'
            };

            Object.keys(switchMapping).forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    // Restore visual state from settings without triggering animations initially
                    const isOn = s[switchMapping[id]];
                    el.classList.toggle('active', isOn === true || isOn === 'true');
                }
            });

            // --- Legacy Toggle Groups (Only for remaining elements) ---
            bindToggleGroup(['styleSquare', 'styleSlanted', 'styleCurved'], 'branchStyle', {
                'styleSquare': 'square',
                'styleSlanted': 'slanted',
                'styleCurved': 'curved'
            });
            bindToggleGroup(['invert1', 'invert2'], 'invert', { 'invert1': true, 'invert2': false });

            const getGroup = () => document.getElementById('dataset_grp');
            const applyZoom = (scale) => {
                const g = getGroup(); if (!g) return;
                const transform = g.getAttribute('transform') || 'matrix(1,0,0,1,0,0)';
                const m = transform.match(/matrix\(([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+)\)/);
                if (m) {
                    const newZoom = parseFloat(m[1]) * scale;
                    g.setAttribute("transform", `matrix(${newZoom},0,0,${parseFloat(m[4]) * scale},${m[5]},${m[6]})`);
                    if (this.renderer) this.renderer.updateScaleBar(s, newZoom);
                }
            };

            if (document.getElementById('zoomIn')) document.getElementById('zoomIn').onclick = () => {
                const m = this.currentMatrix;
                const centerX = this.renderer.canvas.width / 2;
                const centerY = this.renderer.canvas.height / 2;
                const scale = 1.2;

                // Zoom relative to center
                m.e = centerX - (centerX - m.e) * scale;
                m.f = centerY - (centerY - m.f) * scale;
                m.a *= scale; m.d *= scale;

                this.update();
            };
            if (document.getElementById('zoomOut')) document.getElementById('zoomOut').onclick = () => {
                const m = this.currentMatrix;
                const centerX = this.renderer.canvas.width / 2;
                const centerY = this.renderer.canvas.height / 2;
                const scale = 1 / 1.2;

                m.e = centerX - (centerX - m.e) * scale;
                m.f = centerY - (centerY - m.f) * scale;
                m.a *= scale; m.d *= scale;

                this.update();
            };
            if (document.getElementById('zoomFit')) document.getElementById('zoomFit').onclick = () => {
                this.autoFit();
            };
        },

        exportSVG: function () {
            const svg = document.getElementById('main_svg');
            if (!svg) return;

            // 1. Get Labels (innerHTML)
            const labelsContent = svg.innerHTML;

            // 2. Generate Vector Paths for Branches
            // We must use the renderer's method if it exists
            let branchesContent = "";
            if (this.renderer && this.renderer.getExportSVGString) {
                branchesContent = this.renderer.getExportSVGString(this.model, this.layout.settings, this.currentMatrix);
            }

            // 3. Construct Final SVG String
            // We use the outer wrapper attributes (viewBox, width, height)
            let source = svg.outerHTML;
            // Remove innerHTML from source (hacky string manipulation or clone)
            // Safer: Reconstruct tag based on attributes.
            const w = svg.getAttribute("width") || "100%";
            const h = svg.getAttribute("height") || "100%";
            const vb = svg.getAttribute("viewBox");

            let finalSVG = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${w}" height="${h}" viewBox="${vb}">
<style>
text { font-family: Arial, sans-serif; }
</style>
${branchesContent}
${labelsContent}
</svg>`;

            // Add XML declaration
            finalSVG = '<?xml version="1.0" standalone="no"?>\r\n' + finalSVG;

            // Priority: Use Python Bridge for native save dialog (Better UX)
            if (window.parent && window.parent.py_bridge && window.parent.py_bridge.save_file) {
                const success = window.parent.py_bridge.save_file(finalSVG, "tree_view.svg");
                if (success) {
                    console.log("SVG saved via bridge.");
                }
                return;
            }

            // Fallback: Browser download
            const blob = new Blob([finalSVG], { type: "image/svg+xml;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "tree_export.svg";
            a.click();
            setTimeout(() => {
                alert("SVG 已导出 (如未下载请检查浏览器拦截设置)");
            }, 500);
        },

        // --- Batch Operations API ---
        batchColor: function (color) {
            const ids = this.selectedNodeIds;
            if (ids.size === 0) return;

            const traverse = (node) => {
                if (ids.has(node.id)) {
                    // Color this node and all descendants
                    const colorSubtree = (n) => {
                        n.color = color;
                        if (n.children) n.children.forEach(colorSubtree);
                    };
                    colorSubtree(node);
                } else if (node.children) {
                    node.children.forEach(traverse);
                }
            };

            if (this.model.root) traverse(this.model.root);
            this.update();
            this.clearSelection();
        },

        clearSelection: function () {
            this.selectedNodeIds.clear();
            this.update();
            if (window.updateFloatingToolbar) window.updateFloatingToolbar();
        },

        exportSelectedSubtree: function () {
            const ids = this.selectedNodeIds;
            if (ids.size === 0) return;

            // Find the highest selected node (closest to root) to be the root of exported tree
            // Simplified logic: export the first found selected node as a subtree
            let targetNode = null;

            const findTarget = (node) => {
                if (targetNode) return;
                if (ids.has(node.id)) {
                    targetNode = node;
                    return;
                }
                if (node.children) node.children.forEach(findTarget);
            };
            if (this.model.root) findTarget(this.model.root);

            if (targetNode) {
                // Recursive Newick Builder
                const toNewick = (n) => {
                    let s = "";
                    if (n.children && n.children.length > 0) {
                        s += "(" + n.children.map(toNewick).join(",") + ")";
                    }
                    if (n.name) s += n.name;
                    if (n.branchLength !== undefined) s += ":" + n.branchLength;
                    return s;
                };

                const newickData = toNewick(targetNode) + ";";
                const blob = new Blob([newickData], { type: "text/plain" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `subtree_${targetNode.name || 'export'}.nwk`;
                a.click();
            }
        },

        resize: function () {
            if (this.renderer) this.renderer.resize();
            // User Request: "Put the tree back in the middle of the drawing area"
            // So we MUST call autoFit to recalibrate the matrix for the new center.
            this.autoFit();
            // update() is called inside autoFit(), so no need to call it again here.
        }
    };

    return instance;
})();
