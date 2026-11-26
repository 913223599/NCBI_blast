/**
 * 全站 Vue SFC 解析与模板编译门禁测试
 * 使用 @vue/compiler-sfc 对 src 下所有生产 .vue 文件执行 parse + compileTemplate + compileScript 校验，
 * 提前捕获模板表达式语法错误（如格式化器将单引号字符串意外折行导致的 Vite Dev 500）。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

const SRC_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function collectVueFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === '__tests__' || entry.name === 'node_modules') continue
      files.push(...collectVueFiles(full))
    } else if (entry.name.endsWith('.vue')) {
      files.push(full)
    }
  }
  return files
}

describe('全站 Vue SFC 语法与模板编译守护', () => {
  it('所有生产 .vue 文件应通过 @vue/compiler-sfc 解析、模板编译与脚本编译', () => {
    const vueFiles = collectVueFiles(SRC_ROOT)
    expect(vueFiles.length).toBeGreaterThan(50)

    const failures: string[] = []
    const sfcFs = {
      fileExists: (file: string) => fs.existsSync(file),
      readFile: (file: string) => fs.readFileSync(file, 'utf-8'),
      realpath: (file: string) => fs.realpathSync(file),
    }

    for (const file of vueFiles) {
      const rel = path.relative(SRC_ROOT, file).replace(/\\/g, '/')
      const source = fs.readFileSync(file, 'utf-8')
      const { descriptor, errors } = parse(source, { filename: file })
      if (errors.length > 0) {
        failures.push(`[parse] ${rel}: ${errors.map((e) => e.message).join('; ')}`)
        continue
      }

      if (descriptor.template) {
        const tplResult = compileTemplate({
          source: descriptor.template.content,
          filename: file,
          id: rel,
          compilerOptions: {},
        })
        if (tplResult.errors.length > 0) {
          failures.push(
            `[template] ${rel}: ${tplResult.errors
              .map((e) => (typeof e === 'string' ? e : e.message))
              .join('; ')}`
          )
        }
      }

      if (descriptor.script || descriptor.scriptSetup) {
        try {
          compileScript(descriptor, { id: rel, fs: sfcFs })
        } catch (err) {
          failures.push(`[script] ${rel}: ${err instanceof Error ? err.message : String(err)}`)
        }
      }
    }

    expect(failures).toEqual([])
  })
})
