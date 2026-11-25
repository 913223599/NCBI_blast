/**
 * 前端应用元信息单一来源
 * 与项目根目录 version.json 同步（由 tests/test_repo_hygiene.py 持续校验一致性）。
 */
import pkg from '../../package.json'

export const APP_NAME = 'NCBI Bio-Station'
export const APP_VERSION: string = typeof pkg.version === 'string' && pkg.version ? pkg.version : '2.1.0'
