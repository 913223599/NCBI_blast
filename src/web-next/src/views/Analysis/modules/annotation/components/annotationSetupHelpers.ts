/**
 * AnnotationSetup 纯逻辑辅助函数
 */
import type { AnnotationRunParams } from '../types';

export interface AssemblyHistoryItem {
  task_id?: string;
  id?: string;
  name?: string;
  status?: string;
  sample_type?: 'PHAGE' | 'BACTERIA' | 'VIRUS' | 'GENERAL';
  fasta_path?: string;
  assembly_fasta?: string;
  contigs_path?: string;
  output_fasta?: string;
  created_at?: string | number;
}

export const SAMPLE_FASTA = `>NC_005816.1 Yersinia pestis KIM 10 plasmid pPCP1, complete sequence
ATGAAACGCATTAGCACCACCATTACCACCACCATCACCATTACCACAGGTAACGGTGCGGGCTGA
CGTATCGCGATCATGGCGATGCTGGCGTGCCTGGCTATCACCGTGATCGTCGCGATCCTGGTGCGT
AAACCGGTTCTGCCGAACAAAGTTGTTGGTGTGACCACCCTGACCGATGACATCCTGCTGCTGAAA
TAG`;

export function getAssemblyTaskId(item: AssemblyHistoryItem): string {
  return String(item?.task_id || item?.id || '');
}

export function formatHistoryTime(val: unknown): string {
  if (typeof val === 'number' && Number.isFinite(val)) {
    const ms = val < 1e12 ? val * 1000 : val;
    const d = new Date(ms);
    if (!Number.isNaN(d.getTime())) {
      const pad = (n: number) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
  }
  if (typeof val === 'string') {
    const trimmed = val.trim();
    if (/^\d+(\.\d+)?$/.test(trimmed)) {
      return formatHistoryTime(Number(trimmed));
    }
    return trimmed.slice(0, 16);
  }
  return '';
}

export function buildAnnotationTaskName(now: Date = new Date()): string {
  const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, '');
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
  return `Annotation_${dateStr}_${timeStr}`;
}

export function extractCompletedAssemblyHistory(res: unknown): AssemblyHistoryItem[] {
  const resObj = (res && typeof res === 'object' ? res : null) as
    | { data?: unknown; history?: unknown; tasks?: unknown }
    | null;
  const list = Array.isArray(res) ? res : (resObj?.data || resObj?.history || resObj?.tasks || []);
  if (!Array.isArray(list)) return [];
  return (list as AssemblyHistoryItem[]).filter(
    (t) => t.status === 'SUCCESS' || t.status === 'completed' || t.status === 'success'
  );
}

export function resolveAssemblyFastaFallbackPath(task: AssemblyHistoryItem, tid: string): string {
  return (
    task.fasta_path ||
    task.assembly_fasta ||
    task.contigs_path ||
    task.output_fasta ||
    `results/assembly/${tid}/assemblerstep/assembly_run/assembly.fasta`
  );
}

export function validateAnnotationSubmit(
  inputMode: 'upload' | 'paste' | 'assembly',
  form: Pick<AnnotationRunParams, 'fasta_path' | 'fasta_content'>,
  inspectedContigCount: number,
  selectedContigCount: number
): string | null {
  if (inputMode === 'upload' && !form.fasta_path) {
    return '请先上传或选择 FASTA 文件';
  }
  if (inputMode === 'paste' && (!form.fasta_content || !form.fasta_content.trim())) {
    return '请在文本框中粘贴 FASTA 序列';
  }
  if (inputMode === 'assembly' && !form.fasta_path) {
    return '请选择一个有效的组装历史任务';
  }
  if (inspectedContigCount > 1 && selectedContigCount === 0) {
    return '检测到多条 Contig，请在序列列表中至少勾选 1 条序列进行分析';
  }
  return null;
}
