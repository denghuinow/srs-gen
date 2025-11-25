# 基于日志重新生成SRS文档

## 功能说明

`regenerate_srs.py` 脚本可以从10轮迭代生成的日志文件中提取不同迭代轮次和模式的需求信息，然后调用 `DocGenerateAgent` 生成对应的SRS文档，无需重新运行完整的流程。

## 使用方法

### 基本用法

```bash
# 为单个文档生成不同迭代轮次的default模式SRS
python regenerate_srs.py "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7

# 生成default模式 + 消融模式的SRS（共5个文档）
python regenerate_srs.py "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7 \
    --modes no-clarify no-explore-clarify

# 批量处理多个文档（并发处理）
python regenerate_srs.py \
    "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    "output/v046_all_n50i10_q30i_q235i/1999 - tcs.pdf" \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7 \
    --modes no-clarify no-explore-clarify \
    --max-workers 4
```

### 参数说明

- `source_dirs`: 源目录路径（包含日志文件的原始目录，不会被修改），可以指定多个目录进行批量处理
- `--output-dir`: 目标输出目录路径（保存生成的SRS和日志，会按模式聚合，必需参数）
- `--iterations`: 要生成的迭代轮次列表（默认: 2 5 7）
  - 每个迭代轮次会生成一个default模式的SRS文档
- `--modes`: 消融模式列表（可选）
  - `no-clarify`: 使用第一次挖掘后未经评分和过滤的需求清单
  - `no-explore-clarify`: 使用ReqParse的响应作为requirement_structure
  - **注意**：消融模式不需要迭代次数，会自动生成对应的SRS文档
- `--max-workers`: 并发处理的最大工作线程数（默认: 4）

### 生成逻辑

当指定 `--iterations 2 5 7` 和 `--modes no-clarify no-explore-clarify` 时，会生成5个SRS文档：

1. **迭代2的default模式**：用户原始需求 + 第2轮迭代后评分>=1的需求
2. **迭代5的default模式**：用户原始需求 + 第5轮迭代后评分>=1的需求
3. **迭代7的default模式**：用户原始需求 + 第7轮迭代后评分>=1的需求
4. **no-clarify模式**：用户原始需求 + 第一次挖掘后未经评分和过滤的需求清单
5. **no-explore-clarify模式**：用户原始需求 + ReqParse的响应（作为requirement_structure）

**所有模式都包含用户原始需求（raw_input）**
- `--prompt-version`: 提示词版本（可选，默认使用配置中的版本）

### 批量处理

```bash
# 方式1：使用通配符批量处理（推荐，支持并发）
python regenerate_srs.py output/v046_all_n50i10_q30i_q235i/*/ \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7 \
    --modes no-clarify no-explore-clarify \
    --max-workers 8

# 方式2：手动指定多个目录
python regenerate_srs.py \
    "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    "output/v046_all_n50i10_q30i_q235i/1999 - tcs.pdf" \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7
```

## 输出文件

脚本会在**目标输出目录**中生成以下聚合目录结构（不会修改原始目录）：

### 目录结构

```
output/regenerated_srs/
├── srs_document_iter2/
│   ├── 2000 - nasa x38.doc.md
│   ├── 1999 - tcs.pdf.md
│   └── ...
├── srs_document_iter5/
│   ├── 2000 - nasa x38.doc.md
│   ├── 1999 - tcs.pdf.md
│   └── ...
├── srs_document_iter7/
│   ├── 2000 - nasa x38.doc.md
│   ├── 1999 - tcs.pdf.md
│   └── ...
├── srs_document_no-clarify/
│   ├── 2000 - nasa x38.doc.md
│   ├── 1999 - tcs.pdf.md
│   └── ...
├── srs_document_no-explore-clarify/
│   ├── 2000 - nasa x38.doc.md
│   ├── 1999 - tcs.pdf.md
│   └── ...
└── regenerate_srs.log
```

- `srs_document_iter{N}/`: default模式的SRS文档目录（N为迭代轮次）
  - 每个文档的SRS文件名为：`{doc_name}.md`
- `srs_document_{mode}/`: 消融模式的SRS文档目录
  - 每个文档的SRS文件名为：`{doc_name}.md`
- `regenerate_srs.log`: 脚本执行日志

## 工作原理

### Default模式
1. **提取需求清单**：从日志文件中提取指定迭代轮次后评分>=1的需求
2. **提取需求文本**：从日志中提取每个需求的完整文本内容
3. **提取原始输入**：从输出目录的 `input_*` 文件中读取原始输入
4. **生成SRS文档**：调用 `DocGenerateAgent` 生成SRS文档（包含原始需求+提取的需求）

### No-clarify模式
1. **提取第一次挖掘后的需求**：从日志中提取迭代1挖掘后未经评分和过滤的需求清单
2. **提取原始输入**：从输出目录的 `input_*` 文件中读取原始输入
3. **生成SRS文档**：调用 `DocGenerateAgent` 生成SRS文档（包含原始需求+第一次挖掘后的需求）

### No-explore-clarify模式
1. **提取ReqParse响应**：从日志中提取需求语义单元解析的结果（requirement_structure）
2. **提取原始输入**：从输出目录的 `input_*` 文件中读取原始输入
3. **生成SRS文档**：调用 `DocGenerateAgent` 生成SRS文档（包含原始需求+ReqParse的响应）

## 注意事项

- **原始目录不会被修改**：所有生成的SRS文档和日志都保存在指定的目标输出目录中
- **自动跳过已存在的文件**：如果目标文件已存在，脚本会自动跳过，避免重复生成。如需重新生成，请先删除对应文件
- 脚本会自动选择最新的日志文件（如果有多个）
- 对于 `no-explore-clarify` 模式，需要从日志中提取 `requirement_structure`，如果找不到会使用空字符串
- 确保源目录中包含：
  - `srs_gen_*.log` 日志文件
  - `input_*` 输入文件（可选）

## 重新执行失败任务

如果部分任务失败，可以直接重新执行相同的命令，脚本会自动跳过已成功生成的文件，只处理失败的任务：

```bash
# 重新执行，自动跳过已存在的文件
python regenerate_srs.py "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7 \
    --modes no-clarify no-explore-clarify
```

执行结果会显示：
- **成功**：新生成的文件
- **跳过**：已存在的文件（不会重新生成）
- **失败**：需要重新处理的任务

## 示例

```bash
# 只生成第5轮迭代的default模式SRS
python regenerate_srs.py "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    --output-dir "output/regenerated_srs" \
    --iterations 5

# 生成所有配置的SRS（包括default和消融模式）
python regenerate_srs.py "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7 10 \
    --modes no-clarify no-explore-clarify

# 批量处理多个文档（并发）
python regenerate_srs.py \
    "output/v046_all_n50i10_q30i_q235i/2000 - nasa x38.doc" \
    "output/v046_all_n50i10_q30i_q235i/1999 - tcs.pdf" \
    --output-dir "output/regenerated_srs" \
    --iterations 2 5 7 \
    --modes no-clarify no-explore-clarify \
    --max-workers 4
```

