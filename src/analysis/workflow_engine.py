
import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import unquote
from src.workbench.pipelines.analysis_pipeline import AnalysisPipeline
from src.workbench.models.tool_config import ToolConfig

# =================================================================
# Node Execution Strategies (Phase 3 Refactoring)
# =================================================================

class NodeExecutor(ABC):
    """节点执行策略基类"""
    def __init__(self, engine):
        self.engine = engine
        self.pipeline = engine.pipeline
        self.output_dir = engine.output_dir
        self.logger = engine.logger

    @abstractmethod
    def execute(self, node, input_files, context, callback):
        """执行逻辑入口"""
        pass

    def _report(self, callback, node_id, status, msg):
        """统一状态上报"""
        if callback:
            callback(node_id, status, msg)

    def _sanitize_fasta(self, input_path, node_id):
        """清洗 FASTA 头部（处理 URL 编码并替换空格为下划线）"""
        in_path = Path(input_path)
        sanitized_path = self.output_dir / f"{node_id}_sanitized.fasta"
        try:
            with open(in_path, 'r', encoding='utf-8') as f_in:
                content = f_in.read()
            
            lines = content.split('\n')
            sanitized_lines = []
            for line in lines:
                if line.startswith('>'):
                    # 处理解码和空格替换
                    decoded_line = unquote(line)
                    sanitized_lines.append(decoded_line.replace(' ', '_'))
                else:
                    sanitized_lines.append(line)
            
            with open(sanitized_path, 'w', encoding='utf-8') as f_out:
                f_out.write('\n'.join(sanitized_lines))
            
            self.logger.info(f"FASTA sanitized: {in_path.name} -> {sanitized_path.name}")
            return sanitized_path
        except Exception as e:
            self.logger.warning(f"Sanitization failed for {node_id}: {e}")
            return in_path

    def _get_common_args(self, props, tool_id=None):
        """统一提取参数逻辑"""
        args = []
        # 针对特定工具的特殊处理
        is_f2d = tool_id in ['dist', 'fasta2dissim']
        
        for p_key, p_val in props.items():
            if p_val == "" or p_val is None: continue
            
            u_key = p_key.upper().strip()
            # 类型映射
            t_key = "match_len_min" if u_key == "MATCH_LEN" else p_key.lower().strip()
            is_truthy = (p_val is True or str(p_val).lower() == "true")
            
            if is_f2d:
                # 处理 fasta2dissim 的 naked flags
                if u_key in ["AA", "GLOBAL", "UNKNOWN_STRAND", "QC", "NOPROGRESS"]:
                    if is_truthy:
                        flag = f"-{t_key}"
                        if flag not in args: args.append(flag)
                    continue
                
                # 线程设置
                if u_key in ["THREADS", "T"]:
                    args.extend(["-threads", str(p_val)])
                    continue

            # 标准 key-value 形式
            val_str = str(p_val).strip()
            if val_str.lower() != "false" and val_str != "":
                clean_val = val_str.strip('"').strip("'")
                args.extend([f"-{t_key}", clean_val])
        
        return args

class Fasta2DissimExecutor(NodeExecutor):
    """处理距离矩阵计算 (dist, fasta2dissim)"""
    def execute(self, node, input_files, context, callback):
        node_id = node['id']
        out_dm = self.output_dir / f"{node_id}.dm"
        props = node.get('properties', {})
        
        # 1. 清洗输入
        in_fasta = self._sanitize_fasta(input_files[0], node_id)
        
        # 2. 构建基础参数
        ds_base = out_dm.with_suffix('').as_posix()
        threads = getattr(ToolConfig, 'MAX_THREADS', 4)
        args = [in_fasta.as_posix(), "-dataset", ds_base, "-threads", str(threads)]
        
        # 3. 合并自定义参数
        args.extend(self._get_common_args(props, 'fasta2dissim'))
        
        # 4. 执行命令
        self.logger.info(f"Executing fasta2dissim for {node_id}")
        self.pipeline.tree_tools._run_command("fasta2dissim.exe", args)
        
        if out_dm.exists():
            # 5. 后处理：修复 nan 
            content = out_dm.read_text(encoding='utf-8')
            if 'nan' in content:
                out_dm.write_text(content.replace('nan', '1.0'), encoding='utf-8')
            
            context[node_id] = str(out_dm)
            self._report(callback, node_id, 'completed', 'Matrix computed')
        else:
            self._report(callback, node_id, 'error', 'Matrix generation failed')

class MakeDistTreeExecutor(NodeExecutor):
    """处理构树逻辑 (tree, makeDistTree)"""
    def execute(self, node, input_files, context, callback):
        node_id = node['id']
        out_tree = self.output_dir / f"{node_id}.tree"
        props = node.get('properties', {}).copy()
        
        # 1. 合并元数据默认值
        tool_meta = self.engine.tools_metadata.get('makeDistTree', {})
        for pm in tool_meta.get('params', []):
            name = pm['name'].lstrip('-')
            if name not in props and pm.get('default') is not None:
                props[name] = pm['default']

        # 2. 提取并清理参数
        params = {}
        for k, v in props.items():
            if v in [None, "", '""', "''"]: continue
            u_key = k.upper().strip()
            if u_key in ["DATA", "OUTPUT_TREE", "INPUT_TREE"]: continue
            params[k.lower().strip()] = str(v).strip('"').strip("'")

        # 3. 核心修复：Variance 'none' 修正
        if params.get('variance', '').lower() in ['', 'none']:
            params['variance'] = 'lin'

        # 4. 调用 Factory
        self.logger.info(f"Delegating makeDistTree to TreeFactory for node {node_id}")
        self.pipeline.tree_tools.exec_make_dist_tree(Path(input_files[0]), out_tree, params)
        
        if out_tree.exists():
            context[node_id] = str(out_tree)
            self._report(callback, node_id, 'completed', 'Tree constructed (Binary)')
        else:
            self._report(callback, node_id, 'error', 'Tree generation failed')

class PrintDistTreeExecutor(NodeExecutor):
    """处理树导出 (printDistTree)"""
    def execute(self, node, input_files, context, callback):
        node_id = node['id']
        out_nwk = self.output_dir / f"{node_id}_export.nwk"
        props = node.get('properties', {}).copy()
        
        # 合并默认值
        tool_def = self.engine.tools_metadata.get('printDistTree', {})
        for param in tool_def.get('params', []):
            p_name = param['name'].lstrip('-')
            p_default = param.get('default')
            if p_default is not None and p_name not in props:
                props[p_name] = p_default

        # 提取参数逻辑
        params = {}
        for k, v in props.items():
            if v in [None, "", '""', "''"]: continue
            if k.upper() in ["INPUT_TREE", "TREE", "FORMAT", "NEWICK"]: continue
            params[k.lower()] = str(v).strip('"').strip("'")
            
        self.logger.info(f"Delegating printDistTree to TreeFactory for node {node_id}")
        self.pipeline.tree_tools.exec_print_dist_tree(Path(input_files[0]), out_nwk, params=params)
        
        if out_nwk.exists():
            context[node_id] = str(out_nwk)
            self._report(callback, node_id, 'completed', 'Tree exported')
        else:
            self._report(callback, node_id, 'error', 'Export failed')

class TreePreviewExecutor(NodeExecutor):
    """处理树预览 (tree_preview)"""
    def execute(self, node, input_files, context, callback):
        node_id = node['id']
        in_path = Path(input_files[0])
        try:
            target_nwk = in_path
            # 如果是二进制格式则转换
            if in_path.suffix == '.tree':
                target_nwk = self.output_dir / f"{node_id}.nwk"
                self.logger.info(f"Converting {in_path} to Newick: {target_nwk}")
                self.pipeline.tree_tools.exec_print_dist_tree(in_path, target_nwk)
            
            if target_nwk.exists():
                content = target_nwk.read_text(encoding='utf-8')
                preview_snippet = content[:50].replace('\n', '')
                self.logger.info(f"Node {node_id} preview: {preview_snippet}...")
                context[node_id] = str(target_nwk)
                self._report(callback, node_id, 'completed', f'Preview Ready::{target_nwk}')
            else:
                self._report(callback, node_id, 'error', 'Preview conversion failed')
        except Exception as e:
            self.logger.error(f"Failed to process tree for preview: {e}")
            self._report(callback, node_id, 'error', 'Read failed')

class ExportExecutor(NodeExecutor):
    """处理导出逻辑 (export)"""
    def execute(self, node, input_files, context, callback):
        node_id = node['id']
        in_path = Path(input_files[0])
        fmt = node.get('properties', {}).get('fmt', 'Newick')
        
        if fmt == 'Newick' and in_path.suffix == '.tree':
            out_nwk = self.output_dir / f"{node_id}.nwk"
            self.logger.info(f"Exporting {in_path} to Newick: {out_nwk}")
            self.pipeline.tree_tools.exec_print_dist_tree(in_path, out_nwk)
            context[node_id] = str(out_nwk if out_nwk.exists() else in_path)
        else:
            context[node_id] = str(in_path)
            
        self._report(callback, node_id, 'completed', 'Exported')

class GenericToolExecutor(NodeExecutor):
    """处理通用工具 (tools_metadata)"""
    def execute(self, node, input_files, context, callback):
        node_id = node['id']
        node_type = node.get('type')
        tool_meta = self.engine.tools_metadata.get(node_type, {})
        out_file = self.output_dir / f"{node_id}.out"
        
        # 构建参数
        args = [str(f) for f in input_files]
        props = node.get('properties', {})
        
        for pm in tool_meta.get('params', []):
            p_name = pm['name'].lstrip('-')
            val = props.get(p_name) or props.get(p_name.lower())
            if not val and p_name == "match_len_min": 
                val = props.get("MATCH_LEN")
            
            if val is not None and str(val).strip() != "":
                args.extend([pm['name'], str(val)])

        log_args = [f'"{a}"' if ' ' in str(a) else str(a) for a in args]
        self.logger.info(f"Executing: {node_type}.exe {' '.join(log_args)}")
        res = self.pipeline.tree_tools._run_command(f"{node_type}.exe", args)
        out_file.write_text(res.stdout, encoding='utf-8')
        
        context[node_id] = str(out_file)
        self._report(callback, node_id, 'completed', 'Completed')

class WorkflowEngine:
    """
    Bio-Circuit Workflow Engine.
    Executes a topology graph of bio-analysis nodes.
    """
    
    def __init__(self, output_dir=None):
        self.logger = logging.getLogger(__name__)
        self.pipeline = AnalysisPipeline()
        self.output_dir = Path(output_dir) if output_dir else ToolConfig.RESULTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._load_metadata()
        
        # 实例化策略执行器 (Phase 3)
        self._executors = {
            'dist': Fasta2DissimExecutor(self),
            'fasta2dissim': Fasta2DissimExecutor(self),
            'tree': MakeDistTreeExecutor(self),
            'makeDistTree': MakeDistTreeExecutor(self),
            'printDistTree': PrintDistTreeExecutor(self),
            'tree_preview': TreePreviewExecutor(self),
            'export': ExportExecutor(self),
            'generic': GenericToolExecutor(self)
        }

    def run_topology(self, topology_json, progress_callback=None):
        """
        Execute a topology based on JSON definition with multi-input support.
        """
        try:
            if isinstance(topology_json, str):
                data = json.loads(topology_json)
            else:
                data = topology_json
                
            nodes = {n['id']: n for n in data.get('nodes', [])}
            connections = data.get('connections', [])
            
            # node_id -> output_file_path
            context = {}
            
            # --- Phase 1: FASTA Inputs ---
            fasta_nodes = [n for n in nodes.values() if n.get('type') == 'fasta']
            for node in fasta_nodes:
                self._report(progress_callback, node['id'], 'running', 'Loading sequence...')
                props = node.get('properties', {})
                path = props.get('file') or props.get('path')
                
                # Priority 1: Check existing file path
                if path and os.path.exists(path):
                    context[node['id']] = str(path)
                    self._report(progress_callback, node['id'], 'completed', 'Loaded')
                else:
                    # Priority 2: Check raw sequence and create temporary file
                    sequence = props.get('sequence')
                    if sequence and sequence.strip():
                        temp_name = f"input_{node['id']}.fasta"
                        temp_path = self.output_dir / temp_name
                        try:
                            with open(temp_path, 'w', encoding='utf-8') as f:
                                # Ensure it looks like FASTA if header missing
                                if not sequence.strip().startswith('>'):
                                    f.write(f">temporary_input_{node['id']}\n")
                                f.write(sequence)
                            
                            context[node['id']] = str(temp_path)
                            self.logger.info(f"Generated temp file for sequence input: {temp_path}")
                            self._report(progress_callback, node['id'], 'completed', 'Sequence Injected')
                        except Exception as e:
                            self.logger.error(f"Failed to create temp file: {e}")
                            self._report(progress_callback, node['id'], 'error', f'Temp file error: {str(e)}')
                    else:
                        error_msg = f'No file or sequence provided for node {node["id"]}'
                        self.logger.warning(error_msg)
                        self._report(progress_callback, node['id'], 'error', error_msg)

            # --- Phase 2: Propagation Loop ---
            processed = set(context.keys())
            
            for _ in range(len(nodes) + 1):
                made_progress = False
                
                # Check each node if it's ready to fire
                for node_id, node in nodes.items():
                    if node_id in processed: continue
                    if node.get('type') == 'fasta': continue

                    # Count required inputs from metadata
                    node_type = node.get('type')
                    tool_meta = self.tools_metadata.get(node_type)
                    required_in_count = len(tool_meta.get('in', [])) if tool_meta else 1
                    
                    # Find all incoming connections for this node
                    incoming = [c for c in connections if self._get_node_id_from_pin(c['target']) == node_id]
                    
                    # Prepare inputs for this node
                    node_inputs = {}
                    for conn in incoming:
                        s_node_id = self._get_node_id_from_pin(conn['source'])
                        if s_node_id in context:
                            # Map Pin Index from target ID: 'node-xxx::in::0' -> 0
                            try:
                                if '::' in conn['target']:
                                    t_pin_idx = int(conn['target'].split('::')[-1])
                                else:
                                    t_pin_idx = int(conn['target'].split('-')[-1])
                                node_inputs[t_pin_idx] = context[s_node_id]
                            except:
                                continue

                    # If all required inputs (or at least one for generic nodes) are ready
                    if len(node_inputs) >= required_in_count or (not tool_meta and len(node_inputs) > 0):
                        # Sort inputs by pin index to maintain positional order
                        sorted_inputs = list(dict(sorted(node_inputs.items())).values())
                        
                        self._execute_node(node, sorted_inputs, context, progress_callback)
                        if node_id in context:
                            processed.add(node_id)
                            made_progress = True

                if not made_progress: break
                    
            return context

        except Exception as e:
            self.logger.error(f"Workflow fatal error: {e}")
            if progress_callback: progress_callback('system', 'error', str(e))
            raise e

    def _get_node_id_from_pin(self, pin_id):
        # 新格式: 'node-1700::out::0' -> 'node-1700'
        if '::' in pin_id:
            return pin_id.split('::')[0]
        
        # 旧格式: 'node-1700-out-0' -> 'node-1700'
        parts = pin_id.split('-')
        if len(parts) >= 3:
            return '-'.join(parts[:-2])
        return pin_id

    def _execute_node(self, node, input_files, context, callback):
        """
        路由节点到对应的执行策略 (Phase 3)
        """
        node_id = node['id']
        node_type = node.get('type')
        
        try:
            self._report(callback, node_id, 'running', f'Processing {node_type}...')
            
            # 1. 查找专用执行器
            executor = self._executors.get(node_type)
            
            # 2. 如果没有专用执行器，检查是否在通用元数据中
            if not executor and node_type in self.tools_metadata:
                executor = self._executors['generic']
                
            if executor:
                executor.execute(node, input_files, context, callback)
            else:
                self._report(callback, node_id, 'warning', f'Unknown type {node_type}')

        except Exception as e:
            self.logger.error(f"Node {node_id} execution failed: {e}")
            self._report(callback, node_id, 'error', f"Execution Error: {str(e)}")

    def _report(self, callback, node_id, status, msg):
        if callback:
            callback(node_id, status, msg)

    def _load_metadata(self):
        self.tools_metadata = {}
        metadata_path = Path(__file__).parent.parent / "resources" / "tools_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.tools_metadata = {t['id']: t for t in data.get('tools', [])}
            except Exception as e:
                self.logger.error(f"Failed to load tools metadata: {e}")
