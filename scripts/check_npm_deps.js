'use strict';

/**
 * 校验指定目录 package.json 中声明的全部依赖是否已真实安装在 node_modules 下。
 * 用法: node scripts/check_npm_deps.js <packageDir>
 * 退出码: 0 = 全部完整; 1 = 存在缺失依赖或无法读取清单
 */
const fs = require('fs');
const path = require('path');

function main() {
  const targetArg = process.argv[2] || '.';
  const pkgDir = path.resolve(targetArg);
  const pkgFile = path.join(pkgDir, 'package.json');

  if (!fs.existsSync(pkgFile)) {
    console.error(`[npm][ERROR] package.json not found: ${pkgFile}`);
    process.exit(1);
  }

  let pkgJson;
  try {
    pkgJson = JSON.parse(fs.readFileSync(pkgFile, 'utf-8'));
  } catch (err) {
    console.error(`[npm][ERROR] Failed to parse ${pkgFile}: ${err.message}`);
    process.exit(1);
  }

  const depGroups = [
    pkgJson.dependencies || {},
    pkgJson.devDependencies || {},
  ];
  const allDeps = [];
  for (const group of depGroups) {
    for (const name of Object.keys(group)) {
      if (!allDeps.includes(name)) {
        allDeps.push(name);
      }
    }
  }

  const label = path.basename(pkgDir) || targetArg;
  if (allDeps.length === 0) {
    console.log(`[npm] ${label}: no dependencies declared.`);
    process.exit(0);
  }

  const nodeModulesDir = path.join(pkgDir, 'node_modules');
  const missing = [];
  for (const depName of allDeps) {
    const depSegments = depName.split('/');
    const depPkgJson = path.join(nodeModulesDir, ...depSegments, 'package.json');
    if (!fs.existsSync(depPkgJson)) {
      missing.push(depName);
    }
  }

  if (missing.length > 0) {
    console.log(
      `[npm][WARN] ${label}: missing ${missing.length}/${allDeps.length} package(s): ${missing.join(', ')}`
    );
    process.exit(1);
  }

  console.log(`[npm] ${label}: all ${allDeps.length} declared packages ready.`);
  process.exit(0);
}

main();

