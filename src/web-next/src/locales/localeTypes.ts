/**
 * 编译期国际化键名联合类型（零运行时开销）
 * 直接引用 src/resources/locales/zh_CN/*.json 的静态 JSON 类型，作为全站唯一事实源。
 */
import type zhBlast from '../../../resources/locales/zh_CN/blast.json'
import type zhCommon from '../../../resources/locales/zh_CN/common.json'
import type zhDash from '../../../resources/locales/zh_CN/dash.json'
import type zhHelp from '../../../resources/locales/zh_CN/help.json'
import type zhMetadata from '../../../resources/locales/zh_CN/metadata.json'
import type zhNode from '../../../resources/locales/zh_CN/node.json'
import type zhOthers from '../../../resources/locales/zh_CN/others.json'
import type zhParam from '../../../resources/locales/zh_CN/param.json'
import type zhShell from '../../../resources/locales/zh_CN/shell.json'
import type zhStrain from '../../../resources/locales/zh_CN/strain.json'
import type zhStudioTools from '../../../resources/locales/zh_CN/studio_tools.json'
import type zhUi from '../../../resources/locales/zh_CN/ui.json'
import type zhWorkbench from '../../../resources/locales/zh_CN/workbench.json'

export type LocaleKey =
  | keyof typeof zhBlast
  | keyof typeof zhCommon
  | keyof typeof zhDash
  | keyof typeof zhHelp
  | keyof typeof zhMetadata
  | keyof typeof zhNode
  | keyof typeof zhOthers
  | keyof typeof zhParam
  | keyof typeof zhShell
  | keyof typeof zhStrain
  | keyof typeof zhStudioTools
  | keyof typeof zhUi
  | keyof typeof zhWorkbench

/**
 * 既支持全部编译期静态键自动补全，又兼容少量运行时拼接键（如动态状态/元数据前缀）。
 */
export type TranslationKey = LocaleKey | (string & {})
