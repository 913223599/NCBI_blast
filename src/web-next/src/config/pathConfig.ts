// src/config/pathConfig.ts
// 自动定位项目根目录，通过环境变量覆盖或相对路径计算
export const PROJECT_ROOT = import.meta.env.VITE_PROJECT_ROOT
  ? import.meta.env.VITE_PROJECT_ROOT
  : new URL('../../', import.meta.url).pathname.replace(/^file:/, '');

export const TOOLS_ROOT = `${PROJECT_ROOT}/tools`;
export const SRA_TOOLS_BIN = `${TOOLS_ROOT}/ncbi_dist/bin/sra-tools`;
export const TREE_TOOLS_BIN = `${TOOLS_ROOT}/ncbi_dist/bin/tree-tools`;
export const DOCS_ROOT = `${TOOLS_ROOT}/docs/detailed`;
