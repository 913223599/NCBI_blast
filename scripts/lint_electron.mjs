import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const projectRoot = path.resolve(__dirname, '..')
const eslintBin = path.join(projectRoot, 'src', 'web-next', 'node_modules', 'eslint', 'bin', 'eslint.js')

const targets = [
  'electron-shell/main.js',
  'electron-shell/preload.js',
  'electron-shell/dev-runner.js',
  'electron-shell/electron-builder.config.js',
]

execFileSync(
  process.execPath,
  [eslintBin, '--no-config-lookup', '-c', 'electron-shell/eslint.config.mjs', ...targets],
  { cwd: projectRoot, stdio: 'inherit' }
)
