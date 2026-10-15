/**
 * historySorting.ts - 注释历史时序排序与时间解析工具模块
 * 遵循单一职责原则，专门负责任务发生时间格式化、时序高精度比对与正反向排序
 */

export type SortOrder = 'asc' | 'desc';

/**
 * 安全解析各类时间输入（支持 YYYY-MM-DD HH:mm:ss、ISO 格式以及秒级/毫秒级数值时间戳）
 */
export function parseDate(timeVal?: string | number | null): Date | null {
  if (!timeVal) return null;

  if (typeof timeVal === 'number') {
    // 自动兼容秒级与毫秒级时间戳
    return new Date(timeVal > 1e11 ? timeVal : timeVal * 1000);
  }

  const str = String(timeVal).trim();
  if (!str) return null;

  // 跨浏览器兼容：将空格分隔符替换为 T，确保所有 JavaScript 引擎（如 V8/Webkit）均能正确解析
  const normalizedStr = str.replace(' ', 'T');
  const d = new Date(normalizedStr);

  return isNaN(d.getTime()) ? null : d;
}

/**
 * 智能展示人性化发生时间，彻底杜绝只截取时分秒带来的跨天错乱感
 * @param timeVal 时间输入值
 * @param now 可注入的当前基准时间（默认系统当前时间）
 */
export function formatDisplayTime(timeVal?: string | number | null, now = new Date()): string {
  const d = parseDate(timeVal);
  if (!d) return String(timeVal || '-');

  const pad = (n: number) => n.toString().padStart(2, '0');
  const hours = pad(d.getHours());
  const minutes = pad(d.getMinutes());
  const seconds = pad(d.getSeconds());

  const isSameYear = d.getFullYear() === now.getFullYear();
  const isToday = isSameYear && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();

  // 1. 当天任务：显示精确时分秒
  if (isToday) {
    return `${hours}:${minutes}:${seconds}`;
  }

  // 2. 昨天任务：显示昨天与时分
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const isYesterday = d.getFullYear() === yesterday.getFullYear() &&
                      d.getMonth() === yesterday.getMonth() &&
                      d.getDate() === yesterday.getDate();
  if (isYesterday) {
    return `昨天 ${hours}:${minutes}`;
  }

  const month = pad(d.getMonth() + 1);
  const date = pad(d.getDate());

  // 3. 同一年非今天非昨天：显示 月-日 时:分
  if (isSameYear) {
    return `${month}-${date} ${hours}:${minutes}`;
  }

  // 4. 跨年份任务：显示完整 年-月-日 时:分
  return `${d.getFullYear()}-${month}-${date} ${hours}:${minutes}`;
}

/**
 * 按照发生时间严格执行确定性排序
 * @param tasks 任务列表
 * @param order 'asc' 为按发生顺序正序排列（最早发生在前），'desc' 为最新优先排列（最新发生在前）
 */
export function sortAnnotationTasks<T extends { created_at?: string | number }>(
  tasks: T[], 
  order: SortOrder = 'asc'
): T[] {
  if (!Array.isArray(tasks) || tasks.length <= 1) {
    return Array.isArray(tasks) ? [...tasks] : [];
  }

  return [...tasks].sort((a, b) => {
    const timeA = parseDate(a.created_at)?.getTime() || 0;
    const timeB = parseDate(b.created_at)?.getTime() || 0;

    if (order === 'asc') {
      // 发生先后（最早在先）
      return timeA - timeB;
    } else {
      // 最新优先（最新在先）
      return timeB - timeA;
    }
  });
}
