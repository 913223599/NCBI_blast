# 假定蛋白被错误归入“其他功能蛋白”问题记录

## 现象
样本 G2-1_Anno（ANNO_5A8C0B32）圈图图例中“其他功能蛋白”109 个，“假定蛋白”仅 18 个。
`unknown function`、`Uncharacterized ... intergenic region`、`Phage protein` 等均被标为 Other Functional。

## 根因
1. 后端 `AnnotationFuser.is_unannotated` 旧正则漏判 `unknown function` / `Uncharacterized ...` / `Phage protein`，
   `infer_category` 因此认为其“已注释”，未命中任何规则时兜底为 `Other Functional`。
2. 旧 `infer_category` 将 product 与 notes 拼接后匹配，notes 中其他引擎证据
   （如 `Phold Structure: DNA, RNA and nucleotide metabolism`）把未知蛋白误判为 Metabolism/Lysis 等。
3. Pharokka 引擎将原始 PHROG `function` 文本直接写入 `category`；流水线阶段 5 仅填充空值，不重算。
4. 前端 `parser.ts` 无条件采信 gbk 中的 `/category`（或原始 `/function`），
   `render.ts` 对假定蛋白仍会从 notes 推断大类，且 `startsWith("pha")` 会把 `phage tail ...` 误判为假定蛋白。

## 修复
| 文件 | 修改 |
| --- | --- |
| `src/analysis/annotation/fuser.py` | 假定蛋白规则扩充；`infer_category` 改为 product 优先、notes 兜底 |
| `src/analysis/annotation/pipeline.py` | 阶段 5 对所有 CDS 强制重算 category |
| `src/analysis/annotation/engines/pharokka_engine.py` | 原始 PHROG function 只存 `function` 字段 |
| `src/web-next/.../viewer/utils/render.ts` | 假定蛋白规则与后端对齐，假定蛋白直接返回 Hypothetical |
| `src/web-next/.../viewer/utils/parser.ts` | 假定蛋白强制 Hypothetical；`/category` 仅在属于标准大类时采信 |

## 验证
- `tests/test_annotation_fixes.py` 新增 2 个分类回归用例，8 个相关用例全部通过。
- 对 ANNO_5A8C0B32 的 features.json 回放：Hypothetical 18 -> 111，Other Functional 101 -> 11。
- 已有任务结果为旧代码生成，需重新运行注释后生效（前端解析修复对旧 gbk 也会即时纠正显示）。
