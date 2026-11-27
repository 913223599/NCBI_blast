import { describe, expect, it } from 'vitest';
import {
  buildAnnotationTaskName,
  extractCompletedAssemblyHistory,
  formatHistoryTime,
  getAssemblyTaskId,
  resolveAssemblyFastaFallbackPath,
  validateAnnotationSubmit,
} from '../views/Analysis/modules/annotation/components/annotationSetupHelpers';

describe('annotationSetupHelpers', () => {
  it('能正确格式化秒/毫秒数字及字符串时间戳并过滤异常值', () => {
    const sec = 1700000000;
    const ms = 1700000000 * 1000;
    expect(formatHistoryTime(sec)).toBe(formatHistoryTime(ms));
    expect(formatHistoryTime(String(sec))).toBe(formatHistoryTime(sec));
    expect(formatHistoryTime('2026-11-27 10:30:55')).toBe('2026-11-27 10:30');
    expect(formatHistoryTime(null)).toBe('');
    expect(formatHistoryTime(Number.NaN)).toBe('');
  });

  it('能提取已完成组装历史并解析产物路径', () => {
    const completed = extractCompletedAssemblyHistory({
      tasks: [
        { task_id: 'a1', status: 'completed', fasta_path: 'out/a1.fasta' },
        { id: 'a2', status: 'running' },
        { id: 'a3', status: 'SUCCESS' },
      ],
    });
    expect(completed.map(getAssemblyTaskId)).toEqual(['a1', 'a3']);
    expect(resolveAssemblyFastaFallbackPath(completed[0]!, 'a1')).toBe('out/a1.fasta');
    expect(resolveAssemblyFastaFallbackPath(completed[1]!, 'a3')).toBe(
      'results/assembly/a3/assemblerstep/assembly_run/assembly.fasta'
    );
  });

  it('能校验各输入模式及多 Contig 勾选要求并生成默认任务名', () => {
    expect(validateAnnotationSubmit('upload', { fasta_path: '' }, 0, 0)).toBe('请先上传或选择 FASTA 文件');
    expect(validateAnnotationSubmit('paste', { fasta_content: '   ' }, 0, 0)).toBe('请在文本框中粘贴 FASTA 序列');
    expect(validateAnnotationSubmit('assembly', { fasta_path: '' }, 0, 0)).toBe('请选择一个有效的组装历史任务');
    expect(validateAnnotationSubmit('upload', { fasta_path: 'a.fa' }, 3, 0)).toContain('至少勾选 1 条');
    expect(validateAnnotationSubmit('upload', { fasta_path: 'a.fa' }, 3, 1)).toBeNull();

    const taskName = buildAnnotationTaskName(new Date('2026-11-27T08:05:09Z'));
    expect(taskName.startsWith('Annotation_20261127_')).toBe(true);
  });
});
