/**
 * 菌毒种样本编码系统 — 类型定义
 *
 * 编码格式: XXABBBCCCPNNNN (14位)
 *   XX    = 来源 (2位, 用户自定义)
 *   A     = 大类 (1位, 1-9)
 *   BBB   = 属/家族 (3位字母, 非助记)
 *   CCC   = 种/型 (3位字母, 非助记)
 *   P     = 传代次数 (1位, 0-9)
 *   NNNN  = 流水号 (4位, 0001-9999)
 */

/* ========== 大类枚举 ========== */

/** 9 个固定大类 */
export const CATEGORY_MAP: Record<string, string> = {
  '1': '细菌',
  '2': '病毒',
  '3': '真菌',
  '4': '噬菌体',
  '5': '质粒/载体',
  '6': '细胞',
  '7': '核酸',
  '8': '蛋白/抗体',
  '9': '样本/其他',
} as const

/** 有效的大类编码 */
export type CategoryCode = '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9'

/* ========== 对照表词条 ========== */

/** 对照表词条层级 */
export type LookupLevel = 1 | 2 | 3

/**
 * 对照表词条
 *
 * 三层结构：
 *   level=1  大类 (A)       parentPath=""       fullPath="1"
 *   level=2  属   (BBB)     parentPath="1"      fullPath="1AKF"
 *   level=3  种   (CCC)     parentPath="1AKF"   fullPath="1AKFBXM"
 */
export interface CodeLookupEntry {
  /** 本层编码: A层为 "1"-"9", BBB/CCC层为 3位大写字母 */
  code: string

  /** 层级 */
  level: LookupLevel

  /** 父级路径 */
  parentPath: string

  /** 完整路径 = parentPath + code */
  fullPath: string

  /** 中文名称 */
  name: string

  /** 英文 / 学名 */
  latinName?: string

  /** 备注说明 */
  description?: string

  /** 是否为系统预置（预置词条不可删除） */
  isBuiltin: boolean

  /** 是否启用 */
  enabled: boolean

  /** 分类学官方核校验标记 */
  verified?: boolean
}

/* ========== 来源字典 ========== */

/** 来源字典词条 */
export interface SourceEntry {
  /** 2位编码（字母/数字/混合） */
  code: string

  /** 中文名称 */
  name: string

  /** 备注 */
  description?: string

  /** 系统预置 */
  isBuiltin: boolean

  /** 是否启用 */
  enabled: boolean
}

/* ========== 流水号计数器 ========== */

/** 流水号计数器（按 A+BBB+CCC 隔离） */
export interface SerialCounter {
  /** 计数器键: 如 "1AKFBXM" */
  counterKey: string

  /** 当前最大流水号 */
  currentValue: number

  /** 最后更新时间 (ISO 8601) */
  updatedAt: string
}

/* ========== 编码系统配置 ========== */

/** 全局配置 */
export interface CodeSystemConfig {
  /** 编码分配方式: random=随机 sequential=顺序 */
  assignMode: 'random' | 'sequential'

  /** 流水号位数 (默认 4) */
  serialDigits: number

  /** 配置版本 */
  version: string
}

/* ========== 编码解析结果 ========== */

/** 将14位编号拆解后的结构 */
export interface ParsedCode {
  /** 原始编号 */
  raw: string

  /** 来源编码 (2位) */
  source: string

  /** 大类编码 (1位) */
  category: CategoryCode

  /** 属编码 (3位) */
  genus: string

  /** 种编码 (3位) */
  species: string

  /** 传代次数 (0-9) */
  passage: number

  /** 流水号 */
  serial: number

  /** 分类路径 = A + BBB + CCC */
  taxonomyPath: string
}

/** 解析后带名称翻译的完整信息 */
export interface ResolvedCode extends ParsedCode {
  /** 来源名称 */
  sourceName: string

  /** 大类名称 */
  categoryName: string

  /** 属名称 */
  genusName: string

  /** 种名称 */
  speciesName: string
}

/* ========== 编号生成请求 ========== */

/** 生成编号时需要提供的参数 */
export interface CodeGenerationRequest {
  /** 来源编码 (2位) */
  sourceCode: string

  /** 大类编码 */
  categoryCode: CategoryCode

  /** 属编码 (3位字母) */
  genusCode: string

  /** 种编码 (3位字母) */
  speciesCode: string

  /** 传代次数 (0-9) */
  passage: number
}

/* ========== 验证结果 ========== */

/** 编码校验结果 */
export interface CodeValidationResult {
  /** 是否有效 */
  valid: boolean

  /** 错误信息列表 */
  errors: string[]
}

