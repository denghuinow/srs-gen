# 提示词管理

本目录包含所有智能体的提示词模板文件，支持版本管理。

## 目录结构

```
prompts/
├── v1/                   # v1 版本提示词
│   ├── req_explore.md           # 需求挖掘智能体提示词
│   ├── req_clarify.md           # 需求澄清智能体提示词
│   ├── doc_generate.md          # 文档生成智能体提示词
│   └── req_parse.md             # 需求解析智能体提示词
├── v2/                   # v2 版本提示词（示例）
│   ├── req_explore.md
│   ├── req_clarify.md
│   └── ...
└── README.md
```

**目录结构说明：**
- 版本作为文件夹：每个版本（v1, v2, v3...）是一个独立的文件夹
- 文件名区分agent：每个agent的提示词使用对应的文件名（如 `req_explore.md`）
- 接续生成：不需要单独的续接提示词，系统使用对话前缀续写方式自动接续（参考 srs-eval 实现）

## 使用方法

### 通过命令行参数指定版本

```bash
python main.py input.txt --prompt-version v1
```

### 通过环境变量指定版本

```bash
export PROMPT_VERSION=v1
python main.py input.txt
```

### 默认版本

如果不指定版本，系统将使用 `v1` 作为默认版本。

## 创建新版本

要创建新版本的提示词，只需创建一个新的版本文件夹并复制所有提示词文件，例如：

```bash
# 创建 v2 版本目录
mkdir prompts/v2

# 复制所有 v1 版本的提示词文件到 v2
cp prompts/v1/*.md prompts/v2/

# 编辑 v2 目录下的提示词文件进行修改
# 例如：编辑 prompts/v2/req_explore.md
```

然后使用 `--prompt-version v2` 来使用新版本。

**优势：**
- 同一版本的所有提示词在一个文件夹下，便于管理和对比
- 创建新版本时只需复制整个版本文件夹
- 可以轻松对比不同版本的提示词差异

## 提示词模板变量

每个提示词模板支持使用 Python 的 `format()` 方法进行变量替换。变量使用 `{variable_name}` 格式。

### req_explore 模板变量
- `{max_new_requirements_count}`: 每轮迭代需要生成的新需求最大数量
- `{raw_input}`: 客户原始需求文档（来自命令行参数 `input`）
- `{baseline_requirement_structure}`: 需求分析参考基准（通过解析 `--baseline-gend-srs` 得到）
- `{existing_requirements_list}`: 已分析需求清单文本（含ID、评分和内容）
- `{next_requirement_id}`: 下一个可用的需求ID

### req_clarify 模板变量
- `{baseline_srs}`: 基准SRS文档内容（来自命令行参数 `--baseline-srs`）
- `{requirements_list_text}`: 待评分需求清单文本（格式：REQ-XXX: 需求内容）

### doc_generate 模板变量
- `{raw_input}`: 项目摘要（来自命令行参数 `input`）
- `{requirements_text}`: 需求文本（格式化的需求列表）
- `{style_profile}`: 文档样式配置（IEEE 830标准）
- `{context_examples}`: 上下文示例（用于参考）

### req_parse 模板变量
- `{baseline_gend_srs}`: 基准生成的SRS文档内容（来自命令行参数 `--baseline-gend-srs`）

