/**
 * 版本号单一事实源同步与校验工具（读取根目录 version.json）
 * 用法：
 *   node scripts/sync_version.mjs --check   # 仅校验三处 package.json 与 version.json 一致
 *   node scripts/sync_version.mjs --write   # 将 version.json 同步写入三处 package.json
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')
const versionFile = path.join(repoRoot, 'version.json')
const meta = JSON.parse(fs.readFileSync(versionFile, 'utf-8'))
const expectedVersion = String(meta.version || '').trim()

if (!expectedVersion) {
  console.error('version.json 缺少有效的 version 字段')
  process.exit(1)
}

const targets = [
  path.join(repoRoot, 'package.json'),
  path.join(repoRoot, 'electron-shell', 'package.json'),
  path.join(repoRoot, 'src', 'web-next', 'package.json'),
]

const writeMode = process.argv.includes('--write')
let mismatched = false

for (const pkgPath of targets) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'))
  if (pkg.version !== expectedVersion) {
    if (writeMode) {
      pkg.version = expectedVersion
      fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf-8')
      console.log(`[SYNC] ${path.relative(repoRoot, pkgPath)} -> ${expectedVersion}`)
    } else {
      console.error(
        `[MISMATCH] ${path.relative(repoRoot, pkgPath)}: ${pkg.version} !== ${expectedVersion}`
      )
      mismatched = true
    }
  } else {
    console.log(`[OK] ${path.relative(repoRoot, pkgPath)} == ${expectedVersion}`)
  }
}

if (mismatched) {
  process.exit(1)
}
