# 多智能体 SRS 智能编制系统

基于 LangGraph/LangChain 和 OpenAI API 的多智能体系统，用于自动化编制软件需求规格说明书（SRS）。

## 功能特性

- **需求解析**：将自然语言需求解析为去重的原子需求列表
- **需求挖掘**：补充缺口（异常路径、权限、数据完整性等）
- **需求澄清**：对照基准SRS进行一致性评分
- **文档生成**：生成符合IEEE 830标准的SRS文档
- **消融实验**：支持多种模式评估各环节影响
- **迭代优化**：支持多轮迭代收敛需求质量

## 安装

1. 确保 Python >= 3.13
2. 安装依赖：
```bash
pip install -e .
```

3. 配置环境变量（推荐使用.env文件）：
```bash
# 复制示例配置文件
cp .env.example .env

# 编辑.env文件，设置你的配置
# OPENAI_API_KEY=your-api-key-here
# OPENAI_BASE_URL=https://api.openai.com/v1  # 可选，用于自定义API端点
# OPENAI_MODEL=gpt-4o-mini  # 可选，默认为 gpt-4o-mini
# MAX_ITERATIONS=5  # 可选，默认为 5
# MAX_TOKENS=16000  # 可选，文档生成时的最大输出token数，未设置则使用API默认值
# MAX_CONTINUATIONS=2  # 可选，当因max_tokens导致输出被截断时自动请求接续的次数上限，默认为 2
# ABLATION_MODE=default  # 可选：default, no-clarify, no-explore-clarify
```

或者直接设置环境变量：
```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选
export OPENAI_MODEL="gpt-4o-mini"  # 可选，默认为 gpt-4o-mini
export MAX_ITERATIONS="5"  # 可选，默认为 5
export MAX_TOKENS="16000"  # 可选，文档生成时的最大输出token数，未设置则使用API默认值
export MAX_CONTINUATIONS="2"  # 可选，当因max_tokens导致输出被截断时自动请求接续的次数上限，默认为 2
export ABLATION_MODE="default"  # 可选：default, no-clarify, no-explore-clarify
```

## 使用方法

### 基本用法

```bash
python main.py "用户需要登录系统，支持用户名密码登录" --baseline-srs baseline_srs.md
```

### 从文件读取需求

```bash
python main.py requirements.txt --baseline-srs baseline_srs.md --output output_srs.md
```

### 消融模式

```bash
# 跳过澄清阶段
python main.py requirements.txt --ablation-mode no-clarify

# 跳过挖掘和澄清阶段
python main.py requirements.txt --ablation-mode no-explore-clarify
```

### 完整参数

```bash
python main.py <input> \
    --baseline-srs <baseline_srs_file> \
    --ablation-mode <default|no-clarify|no-explore-clarify> \
    --max-iterations <number> \
    --output <output_srs.md> \
    --report <comparison_report.md>
```

参数说明：
- `input`: 需求输入（文本或文件路径）
- `--baseline-srs`: 基准SRS文件路径（可选）
- `--ablation-mode`: 消融模式（可选，默认：default）
- `--max-iterations`: 最大迭代次数（可选，默认：从.env或配置读取，默认值为5）
- `--output`: 输出SRS文档路径（默认：output_srs.md）
- `--report`: 输出对比报告路径（默认：comparison_report.md）

## 输出文件

- **SRS文档**：生成的IEEE 830标准SRS文档（默认：`output_srs.md`）
- **对比报告**：消融实验对比信息（默认：`comparison_report.md`），包含：
  - 总需求数
  - 进入最终清单数
  - 各代理耗时汇总
  - 各需求得分历史轨迹概览

## 项目结构

```
srs-gen/
├── main.py                 # 主入口
├── src/
│   ├── agents/            # 智能体模块
│   │   ├── req_parse.py   # 需求解析
│   │   ├── req_explore.py # 需求挖掘
│   │   ├── req_clarify.py # 需求澄清
│   │   └── doc_generate.py # 文档生成
│   ├── workflow/          # 工作流模块
│   │   ├── orchestrator.py # 工作流编排
│   │   └── state.py       # 状态管理
│   ├── models/            # 数据模型
│   │   ├── requirement.py # 需求数据模型
│   │   └── srs_template.py # SRS模板
│   └── utils/             # 工具函数
│       ├── timer.py       # 耗时统计
│       ├── score_history.py # 得分历史
│       └── comparison.py  # 对比报告
└── tests/                 # 测试文件
```

## 工作流程

1. **需求解析**：将自然语言需求解析为原子需求
2. **需求挖掘**：补充缺口，形成全局需求清单
3. **需求澄清**：对照基准SRS进行评分，移除负分条目
4. **迭代优化**：根据反馈修正扩充，直至收敛
5. **文档生成**：生成最终SRS文档

## 消融模式说明

- **default**：完整流程（解析→挖掘→澄清→生成）
- **no-clarify**：跳过澄清，默认0分，记录历史
- **no-explore-clarify**：跳过挖掘和澄清，原子需求直接映射

## 注意事项

- 确保已设置 `OPENAI_API_KEY` 环境变量
- 基准SRS文件应为Markdown格式
- 系统会自动记录各代理的耗时和需求得分历史

## 许可证

（待补充）
