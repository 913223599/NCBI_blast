/**
 * historySorting.test.ts - 注释历史时序排序与时间格式化测试
 */
import { describe, it, expect } from 'vitest';
import { 
  parseDate, 
  formatDisplayTime, 
  sortAnnotationTasks, 
  type SortOrder 
} from './historySorting';

describe('historySorting 模块测试', () => {
  describe('parseDate 日期解析', () => {
    it('正确解析 YYYY-MM-DD HH:mm:ss 格式', () => {
      const d = parseDate('2026-10-12 10:59:59');
      expect(d).not.toBeNull();
      expect(d!.getFullYear()).toBe(2026);
      expect(d!.getMonth()).toBe(9); // 10月为索引9
      expect(d!.getDate()).toBe(12);
      expect(d!.getHours()).toBe(10);
      expect(d!.getMinutes()).toBe(59);
      expect(d!.getSeconds()).toBe(59);
    });

    it('正确解析 ISO 字符串及时间戳', () => {
      const d1 = parseDate('2026-10-15T20:45:00');
      expect(d1).not.toBeNull();
      expect(d1!.getHours()).toBe(20);

      const d2 = parseDate(1700000000);
      expect(d2).not.toBeNull();
    });

    it('非法或空输入返回 null', () => {
      expect(parseDate(null)).toBeNull();
      expect(parseDate(undefined)).toBeNull();
      expect(parseDate('')).toBeNull();
      expect(parseDate('invalid-date')).toBeNull();
    });
  });

  describe('formatDisplayTime 时间展示', () => {
    const fixedNow = new Date('2026-10-15T21:00:00');

    it('当天的任务显示具体时分秒', () => {
      const formatted = formatDisplayTime('2026-10-15 20:45:30', fixedNow);
      expect(formatted).toBe('20:45:30');
    });

    it('昨天的任务显示昨天 HH:mm', () => {
      const formatted = formatDisplayTime('2026-10-14 15:30:00', fixedNow);
      expect(formatted).toBe('昨天 15:30');
    });

    it('同一年往日的任务显示 MM-DD HH:mm', () => {
      const formatted1 = formatDisplayTime('2026-10-12 10:59:59', fixedNow);
      expect(formatted1).toBe('10-12 10:59');

      const formatted2 = formatDisplayTime('2026-09-21 18:04:30', fixedNow);
      expect(formatted2).toBe('09-21 18:04');
    });

    it('跨年任务显示完整 YYYY-MM-DD HH:mm', () => {
      const formatted = formatDisplayTime('2025-12-31 23:59:00', fixedNow);
      expect(formatted).toBe('2025-12-31 23:59');
    });
  });

  describe('sortAnnotationTasks 排序逻辑', () => {
    const mockTasks = [
      { task_id: '1', task_name: 'B017', created_at: '2026-10-12 10:59:59' },
      { task_id: '2', task_name: 'assembly', created_at: '2026-10-12 10:59:52' },
      { task_id: '3', task_name: '12-A_scaffold_1', created_at: '2026-10-10 15:07:16' },
      { task_id: '4', task_name: '12-A_scaffold_2', created_at: '2026-10-10 15:07:04' },
      { task_id: '5', task_name: '混合', created_at: '2026-10-10 14:53:43' },
      { task_id: '6', task_name: '二代测序', created_at: '2026-10-10 13:50:40' },
      { task_id: '7', task_name: '蜡样', created_at: '2026-09-21 18:04:30' },
    ];

    it('按发生顺序排序 (asc: 最早发生的在前，正序递增)', () => {
      const sorted = sortAnnotationTasks(mockTasks, 'asc');
      expect(sorted[0]!.task_name).toBe('蜡样'); // 09-21 18:04
      expect(sorted[1]!.task_name).toBe('二代测序'); // 10-10 13:50
      expect(sorted[2]!.task_name).toBe('混合'); // 10-10 14:53
      expect(sorted[3]!.task_name).toBe('12-A_scaffold_2'); // 10-10 15:07:04
      expect(sorted[4]!.task_name).toBe('12-A_scaffold_1'); // 10-10 15:07:16
      expect(sorted[5]!.task_name).toBe('assembly'); // 10-12 10:59:52
      expect(sorted[6]!.task_name).toBe('B017'); // 10-12 10:59:59
    });

    it('按最新优先排序 (desc: 最新发生的在前，倒序递减)', () => {
      const sorted = sortAnnotationTasks(mockTasks, 'desc');
      expect(sorted[0]!.task_name).toBe('B017'); // 10-12 10:59:59
      expect(sorted[1]!.task_name).toBe('assembly'); // 10-12 10:59:52
      expect(sorted[2]!.task_name).toBe('12-A_scaffold_1'); // 10-10 15:07:16
      expect(sorted[3]!.task_name).toBe('12-A_scaffold_2'); // 10-10 15:07:04
      expect(sorted[4]!.task_name).toBe('混合'); // 10-10 14:53
      expect(sorted[5]!.task_name).toBe('二代测序'); // 10-10 13:50
      expect(sorted[6]!.task_name).toBe('蜡样'); // 09-21 18:04
    });

    it('不修改原数组', () => {
      const copy = [...mockTasks];
      sortAnnotationTasks(mockTasks, 'asc');
      expect(mockTasks).toEqual(copy);
    });
  });
});
