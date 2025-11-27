# requirement_structure 和 baseline_requirement_structure 字段说明

本文档详细解释 `WorkflowState` 中这两个关键字段的含义、用途和使用场景。

## 字段概览

```python
requirement_structure: str  # 需求结构（Markdown格式）
baseline_requirement_structure: str  # 基准需求语义单元（通过ReqParseAgent解析baseline_gend_srs得到）
```

## 1. requirement_structure（需求结构）

### 定义
- **类型**: `str`
- **格式**: Markdown 格式的文本
- **来源**: 在 `_parse_node` 中直接设置为 `raw_input`（原始输入文档）

### 设置位置

```48:49:srs-gen/src/workflow/orchestrator.py
# requirement_structure 直接使用 raw_input，不再通过 ReqParseAgent 解析
state["requirement_structure"] = state["raw_input"]  # type: ignore
```

### 主要用途

#### 1.1 no-explore-clarify 模式下的需求生成

在 `no-explore-clarify` 消融模式下，`requirement_structure` 被直接用于生成需求列表，跳过需求探索（explore）和澄清（clarify）阶段：

```86:92:srs-gen/src/workflow/orchestrator.py
if self.ablation_mode == "no-explore-clarify":
    requirement_structure = state.get("requirement_structure", "")  # type: ignore
    state["requirements"] = self._build_requirements_from_structure(
        requirement_structure,
        raw_input,
        state["iteration_count"]
    )
```

#### 1.2 SRS 文档生成时的需求文本

在 `DocGenerateAgent` 中，如果处于 `no-explore-clarify` 模式，会直接使用 `requirement_structure` 作为需求文本：

```52:55:srs-gen/src/agents/doc_generate.py
# no-explore-clarify模式：直接使用ReqParse的响应（requirement_structure）
if ablation_mode == "no-explore-clarify" and requirement_structure:
    self.logger.info("no-explore-clarify模式：直接使用ReqParse的响应作为requirements_text")
    requirements_text = requirement_structure
```

### 使用场景总结

| 场景 | 用途 | 说明 |
|------|------|------|
| **默认模式** | 存储原始输入 | 保存用户提供的原始需求文档 |
| **no-explore-clarify 模式** | 直接生成需求 | 跳过探索和澄清，直接从原始输入生成需求列表 |
| **SRS 生成** | 需求文本来源 | 在 no-explore-clarify 模式下作为生成 SRS 的需求文本 |

---

## 2. baseline_requirement_structure（基准需求语义单元）

### 定义
- **类型**: `str`
- **格式**: 通过 `ReqParseAgent` 解析 `baseline_gend_srs` 得到的结构化需求语义单元
- **来源**: 在 `_parse_node` 中，如果存在 `baseline_gend_srs`，使用 `ReqParseAgent` 解析生成

### 设置位置

```51:58:srs-gen/src/workflow/orchestrator.py
# 如果存在 baseline_gend_srs，使用 ReqParseAgent 解析它生成需求语义单元
baseline_gend_srs = state.get("baseline_gend_srs", "")
if baseline_gend_srs:
    agent = ReqParseAgent(self.client, self.timer_manager, prompt_version=self.prompt_version)
    baseline_requirement_structure = agent.parse(baseline_gend_srs, input_type="基准生成的SRS")
    state["baseline_requirement_structure"] = baseline_requirement_structure  # type: ignore
else:
    state["baseline_requirement_structure"] = ""  # type: ignore
```

### 主要用途

#### 2.1 需求探索阶段的上下文示例

在 `ReqExploreAgent` 的 `explore` 方法中，`baseline_requirement_structure` 作为上下文示例传递给模型，帮助模型理解需求挖掘的方向和标准：

```79:85:srs-gen/src/agents/req_explore.py
prompt = self.prompt_loader.format(
    "req_explore",
    max_new_requirements_count=new_req_count,
    raw_input=raw_input,
    baseline_requirement_structure=baseline_requirement_structure,
    next_requirement_id=next_id
)
```

**作用**: 为需求探索提供参考标准，让模型了解"好的需求应该是什么样的"，从而提高挖掘质量。

#### 2.2 SRS 文档生成时的上下文示例

在 `DocGenerateAgent` 中，`baseline_requirement_structure` 作为 `context_examples` 传递给模型，作为生成 SRS 文档的参考示例：

```69:74:srs-gen/src/agents/doc_generate.py
prompt = self.prompt_loader.format(
    "doc_generate",
    raw_input=raw_input,
    requirements_text=requirements_text,
    style_profile=style_profile,
    context_examples=baseline_requirement_structure if baseline_requirement_structure else context,
)
```

**作用**: 为 SRS 文档生成提供参考示例，帮助模型理解目标文档的结构、风格和内容深度。

### 使用场景总结

| 场景 | 用途 | 说明 |
|------|------|------|
| **需求探索** | 上下文示例 | 为 ReqExploreAgent 提供参考标准，指导需求挖掘方向 |
| **SRS 生成** | 上下文示例 | 为 DocGenerateAgent 提供参考示例，指导文档生成风格和结构 |
| **质量提升** | 基准参考 | 通过对比基准文档的结构，提高生成质量 |

---

## 两个字段的对比

| 特性 | requirement_structure | baseline_requirement_structure |
|------|----------------------|-------------------------------|
| **数据来源** | `raw_input`（用户原始输入） | `baseline_gend_srs`（基准生成的 SRS） |
| **处理方式** | 直接赋值，不经过解析 | 通过 `ReqParseAgent` 解析生成 |
| **主要用途** | 存储原始需求文档 | 提供参考标准和示例 |
| **使用模式** | no-explore-clarify 模式 | 所有模式（如果提供了 baseline_gend_srs） |
| **作用阶段** | 需求生成、SRS 生成 | 需求探索、SRS 生成 |
| **作用方式** | 直接使用 | 作为上下文示例 |

---

## 工作流中的流转

### Parse 节点
1. `requirement_structure` ← `raw_input`（直接赋值）
2. `baseline_requirement_structure` ← `ReqParseAgent.parse(baseline_gend_srs)`（如果存在）

### Explore 节点
1. 使用 `baseline_requirement_structure` 作为上下文示例传递给 `ReqExploreAgent`
2. 在 `no-explore-clarify` 模式下，使用 `requirement_structure` 直接生成需求列表

### Generate 节点
1. 在 `no-explore-clarify` 模式下，使用 `requirement_structure` 作为需求文本
2. 使用 `baseline_requirement_structure` 作为上下文示例传递给 `DocGenerateAgent`

---

## 实际示例

### 示例 1: requirement_structure 的内容

```markdown
# 项目需求文档

## 功能需求
1. 系统必须支持用户登录功能
2. 系统必须支持用户注册功能
3. 系统必须支持密码重置功能

## 非功能需求
1. 系统响应时间应小于 2 秒
2. 系统应支持 1000 并发用户
```

### 示例 2: baseline_requirement_structure 的内容

```markdown
# 基准需求语义单元

## REQ-001: 用户认证
系统必须提供用户登录功能，支持用户名和密码认证。

## REQ-002: 用户注册
系统必须提供用户注册功能，包括邮箱验证。

## REQ-003: 密码管理
系统必须提供密码重置功能，通过邮箱发送重置链接。
```

---

## 注意事项

1. **requirement_structure**:
   - 在默认模式下，主要用于存储原始输入，不直接参与生成
   - 在 `no-explore-clarify` 模式下，是核心数据源

2. **baseline_requirement_structure**:
   - 如果未提供 `baseline_gend_srs`，该字段为空字符串
   - 作为上下文示例使用，不直接参与需求生成，而是提供参考标准
   - 有助于提高生成质量，但不是必需的

3. **字段依赖**:
   - `baseline_requirement_structure` 依赖于 `baseline_gend_srs` 的存在
   - 如果 `baseline_gend_srs` 为空，`baseline_requirement_structure` 也会为空

4. **性能考虑**:
   - `baseline_requirement_structure` 的生成需要调用 `ReqParseAgent`，会增加处理时间
   - 但作为上下文示例，可以显著提高生成质量

