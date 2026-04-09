/**
 * 样本编号生成与解析
 *
 * 职责：拼接/解析 14 位编号，验证编号格式。
 *       依赖 useSerialCounter 获取流水号，依赖 useCodeLookup 翻译名称。
 *       本身不管理对照表数据，也不管理计数器状态。
 *
 * 编码格式: XXABBBCCCPNNNN (14位)
 */
import type {
  CategoryCode,
  ParsedCode,
  ResolvedCode,
  CodeGenerationRequest,
  CodeValidationResult,
} from '../types/codeSystem'
import { CATEGORY_MAP } from '../types/codeSystem'
import { useSerialCounter } from './useSerialCounter'
import { useCodeLookup } from './useCodeLookup'

/** 14位编号正则: 2位来源 + 1位数字 + 3字母 + 3字母 + 1位数字 + 4位数字 */
const CODE_REGEX = /^[A-Z0-9]{2}[1-9][A-Z]{3}[A-Z]{3}[0-9][0-9]{4}$/

/** 默认流水号位数 */
const DEFAULT_SERIAL_DIGITS = 4

export function useCodeGenerator() {
  const counter = useSerialCounter()
  const lookup = useCodeLookup()

  /* ========== 生成 ========== */

  /**
   * 预览即将生成的 14 位样本编号（不消耗流水号）
   * @param request - 生成请求参数
   */
  function preview(request: CodeGenerationRequest): string {
    const validation = validateRequest(request)
    if (!validation.valid) {
      throw new Error(`编号预览失败: ${validation.errors.join('; ')}`)
    }

    const taxonomyPath = `${request.categoryCode}${request.genusCode}${request.speciesCode}`
    const nextValue = counter.getCurrentValue(taxonomyPath) + 1
    const serialStr = padSerial(nextValue, DEFAULT_SERIAL_DIGITS)

    return (
      request.sourceCode +
      request.categoryCode +
      request.genusCode +
      request.speciesCode +
      String(request.passage) +
      serialStr
    )
  }

  /**
   * 正式提交并生成编号（消耗流水号，由 Dialog 在确认时调用）
   */
  function commit(request: CodeGenerationRequest): string {
    const validation = validateRequest(request)
    if (!validation.valid) {
      throw new Error(`编号提交失败: ${validation.errors.join('; ')}`)
    }

    const taxonomyPath = `${request.categoryCode}${request.genusCode}${request.speciesCode}`
    const serialValue = counter.increment(taxonomyPath)
    const serialStr = padSerial(serialValue, DEFAULT_SERIAL_DIGITS)

    return (
      request.sourceCode +
      request.categoryCode +
      request.genusCode +
      request.speciesCode +
      String(request.passage) +
      serialStr
    )
  }

  /**
   * 批量生成编号
   * @param request - 生成请求（来源/大类/属/种/传代次数）
   * @param count - 生成数量
   * @returns 编号字符串数组
   */
  function generateBatch(
    request: CodeGenerationRequest,
    count: number
  ): string[] {
    const validation = validateRequest(request)
    if (!validation.valid) {
      throw new Error(`批量生成失败: ${validation.errors.join('; ')}`)
    }

    const taxonomyPath = `${request.categoryCode}${request.genusCode}${request.speciesCode}`
    const serialValues = counter.incrementBatch(taxonomyPath, count)

    return serialValues.map(
      (serialValue) =>
        request.sourceCode +
        request.categoryCode +
        request.genusCode +
        request.speciesCode +
        String(request.passage) +
        padSerial(serialValue, DEFAULT_SERIAL_DIGITS)
    )
  }

  /* ========== 解析 ========== */

  /**
   * 将 14 位编号拆解为结构化字段
   * @param code - 14位编号字符串
   * @returns 解析结果，无效时返回 null
   */
  function parse(code: string): ParsedCode | null {
    if (!CODE_REGEX.test(code)) return null

    const source = code.substring(0, 2)
    const category = code.substring(2, 3) as CategoryCode
    const genus = code.substring(3, 6)
    const species = code.substring(6, 9)
    const passage = parseInt(code.substring(9, 10), 10)
    const serial = parseInt(code.substring(10, 14), 10)

    return {
      raw: code,
      source,
      category,
      genus,
      species,
      passage,
      serial,
      taxonomyPath: `${category}${genus}${species}`,
    }
  }

  /**
   * 解析并翻译为完整的中文名称信息
   * @param code - 14位编号字符串
   * @returns 带名称的完整解析结果，无效时返回 null
   */
  function resolve(code: string): ResolvedCode | null {
    const parsed = parse(code)
    if (!parsed) return null

    const sourceName = lookup.getSourceName(parsed.source)
    const categoryName = lookup.getCategoryName(parsed.category)
    const { genusName, speciesName } = lookup.resolveTaxonomyPath(
      parsed.category,
      parsed.genus,
      parsed.species
    )

    return {
      ...parsed,
      sourceName,
      categoryName,
      genusName,
      speciesName,
    }
  }

  /* ========== 验证 ========== */

  /**
   * 验证编号格式是否合法
   * @param code - 待验证的编号
   */
  function validateCode(code: string): CodeValidationResult {
    const errors: string[] = []

    if (typeof code !== 'string') {
      errors.push('编号必须为字符串')
      return { valid: false, errors }
    }

    if (code.length !== 14) {
      errors.push(`编号长度应为14位，当前${code.length}位`)
    }

    if (!CODE_REGEX.test(code)) {
      errors.push('编号格式不符合 XXABBBCCCPNNNN 规范')
    }

    if (code.length >= 3) {
      const category = code.substring(2, 3)
      if (!CATEGORY_MAP[category]) {
        errors.push(`大类编码 "${category}" 无效，有效值为 1-9`)
      }
    }

    if (code.length >= 10) {
      const passage = parseInt(code.substring(9, 10), 10)
      if (isNaN(passage) || passage < 0 || passage > 9) {
        errors.push('传代次数应为 0-9')
      }
    }

    if (code.length >= 14) {
      const serial = parseInt(code.substring(10, 14), 10)
      if (isNaN(serial) || serial < 1) {
        errors.push('流水号应为 0001 以上的正整数')
      }
    }

    return { valid: errors.length === 0, errors }
  }

  /**
   * 验证生成请求参数
   */
  function validateRequest(
    request: CodeGenerationRequest
  ): CodeValidationResult {
    const errors: string[] = []

    if (!/^[A-Z0-9]{2}$/.test(request.sourceCode)) {
      errors.push('来源编码应为2位大写字母或数字')
    }

    if (!CATEGORY_MAP[request.categoryCode]) {
      errors.push(`大类编码 "${request.categoryCode}" 无效`)
    }

    if (!/^[A-Z]{3}$/.test(request.genusCode)) {
      errors.push('属编码应为3位大写字母')
    }

    if (!/^[A-Z]{3}$/.test(request.speciesCode)) {
      errors.push('种编码应为3位大写字母')
    }

    if (
      !Number.isInteger(request.passage) ||
      request.passage < 0 ||
      request.passage > 9
    ) {
      errors.push('传代次数应为 0-9 的整数')
    }

    return { valid: errors.length === 0, errors }
  }

  /* ========== 内部工具 ========== */

  /**
   * 将流水号补零至指定位数
   * 溢出时自动扩展位数
   */
  function padSerial(value: number, digits: number): string {
    const strValue = String(value)
    if (strValue.length >= digits) return strValue
    return strValue.padStart(digits, '0')
  }

  return {
    preview,
    commit,
    generateBatch,
    parse,
    resolve,
    validateCode,
    validateRequest,

    // 暴露子模块
    lookup,
    counter,
  }
}
