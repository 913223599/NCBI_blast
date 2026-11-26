/**
 * Electron Builder 统一打包配置（动态读取根目录 version.json 单一事实源）
 * 用法：cd electron-shell && npm run dist
 */
const fs = require('node:fs')
const path = require('node:path')

const repoRoot = path.resolve(__dirname, '..')
const versionMeta = JSON.parse(
  fs.readFileSync(path.join(repoRoot, 'version.json'), 'utf-8')
)

const productName = versionMeta.name || 'NCBI Bio-Station'
const appVersion = versionMeta.version || '2.1.0'

/** @type {import('electron-builder').Configuration} */
module.exports = {
  appId: 'org.ncbi.biostation.desktop',
  productName,
  copyright: 'Copyright (c) NCBI Bio-Station Contributors',
  extraMetadata: {
    version: appVersion,
  },
  directories: {
    output: '../dist/electron',
    buildResources: 'assets',
  },
  files: [
    'main.js',
    'preload.js',
    'package.json',
    '!**/*.log*',
    '!**/*.old',
  ],
  extraResources: [
    {
      from: '../version.json',
      to: 'version.json',
    },
    {
      from: '../src/web-next/dist',
      to: 'web-next-dist',
    },
    {
      from: '../src/resources',
      to: 'src/resources',
    },
    {
      from: '../resources/help',
      to: 'resources/help',
    },
    {
      from: '../mail_config.default.json',
      to: 'mail_config.default.json',
    },
  ],
  asar: true,
  win: {
    target: [
      { target: 'nsis', arch: ['x64'] },
      { target: 'portable', arch: ['x64'] },
    ],
    artifactName: '${productName}-${version}-${arch}-${target}.${ext}',
  },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
  },
}
