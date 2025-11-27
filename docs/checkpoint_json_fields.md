# Checkpoint JSON 字段说明文档

本文档详细说明 checkpoint JSON 文件中各字段的含义。

## 文件命名规则

Checkpoint 文件命名格式：`checkpoint_{node_name}_iter{iteration}.json`

- `node_name`: 节点名称，可能的值：
  - `parse`: 解析阶段
  - `explore`: 需求探索阶段
  - `clarify`: 需求澄清阶段
  - `generate`: 生成阶段
- `iteration`: 迭代次数（整数）

## 顶层字段结构

```json
{
  "node_name": "节点名称",
  "iteration": 迭代次数,
  "timestamp": 时间戳,
  "state": { ... }
}
```

### 顶层字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `node_name` | string | 保存 checkpoint 时的节点名称（parse/explore/clarify/generate） |
| `iteration` | int | 当前迭代次数，可能为 null |
| `timestamp` | float | 保存 checkpoint 时的 Unix 时间戳 |
| `state` | object | 工作流状态对象，包含所有工作流数据 |

## state 对象字段

### 1. 字符串字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `raw_input` | string | 原始输入文档内容 |
| `baseline_srs` | string | 基准 SRS 文档内容 |
| `baseline_gend_srs` | string | 基准生成的 SRS 文档内容 |
| `requirement_structure` | string | 需求结构描述 |
| `baseline_requirement_structure` | string | 基准需求结构描述 |
| `ablation_mode` | string | 消融实验模式 |
| `output_dir_base` | string | 输出目录基础路径 |
| `task_name` | string | 任务名称 |
| `_version_to_generate` | string | 待生成的版本标识 |
| `_version_name` | string | 版本名称 |
| `_last_generated_version` | string | 最后生成的版本标识 |

### 2. 数值字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `iteration_count` | int | 当前迭代计数 |
| `max_iterations` | int | 最大迭代次数 |
| `max_new_requirements_per_iteration` | int | 每次迭代最大新需求数量 |
| `_cumulative_clarify_time` | float | 累计澄清时间（秒） |
| `_cumulative_version_gen_time` | float | 累计版本生成时间（秒） |
| `_workflow_start_time` | float | 工作流开始时间（Unix 时间戳） |

### 3. 布尔字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `convergence_reached` | boolean | 是否达到收敛条件 |

### 4. requirements 字段（RequirementList）

需求清单对象，包含所有已发现的需求。

```json
{
  "requirements": [
    {
      "id": "REQ-001",
      "text": "需求文本内容",
      "score": 1,
      "reason": "评分理由",
      "iteration": 1,
      "evidence": "评分引用的基准证据"
    }
  ]
}
```

#### Requirement 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | string | 需求ID，格式如 "REQ-001" |
| `text` | string | 需求文本内容 |
| `score` | int \| null | 评分值，范围 -2 到 +2，null 表示未评分 |
| `reason` | string \| null | 评分理由（仅用于审计，不传递给 ReqExplore） |
| `iteration` | int \| null | 生成该需求时的迭代轮次 |
| `evidence` | string \| null | 评分引用的基准证据 |

### 5. score_history 字段（ScoreHistory）

评分历史记录，记录每个需求在不同迭代中的评分变化。

```json
{
  "score_history": {
    "REQ-001": [
      {
        "iteration": 1,
        "score": 1,
        "reason": "评分理由",
        "evidence": "证据信息"
      },
      {
        "iteration": 2,
        "score": 2,
        "reason": "更新后的评分理由",
        "evidence": "新的证据信息"
      }
    ],
    "REQ-002": [...]
  }
}
```

#### ScoreRecord 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `iteration` | int | 评分时的迭代轮次 |
| `score` | int | 评分值，范围 -2 到 +2 |
| `reason` | string \| null | 评分理由 |
| `evidence` | string \| null | 评分引用的基准证据 |

### 6. timer_manager 字段（TimerManager）

计时器管理器，记录各个 Agent 的执行时间统计。

```json
{
  "timer_manager": {
    "total_start_time": 1234567890.123,
    "timers": {
      "ReqExploreAgent": {
        "name": "ReqExploreAgent",
        "start_time": 1234567890.123,
        "elapsed_time": 5.67,
        "call_count": 10
      },
      "ReqClarifyAgent": {
        "name": "ReqClarifyAgent",
        "start_time": 1234567891.234,
        "elapsed_time": 3.45,
        "call_count": 5
      }
    }
  }
}
```

#### TimerManager 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `total_start_time` | float \| null | 总开始时间（Unix 时间戳） |
| `timers` | object | 各个计时器的字典，key 为 Agent 名称 |

#### AgentTimer 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `name` | string | 计时器名称（Agent 名称） |
| `start_time` | float \| null | 开始时间（Unix 时间戳） |
| `elapsed_time` | float | 累计已用时间（秒） |
| `call_count` | int | 调用次数 |

### 7. req_explore_messages 字段

需求探索阶段的对话消息列表。

```json
{
  "req_explore_messages": [
    {
      "role": "user",
      "content": "用户消息内容"
    },
    {
      "role": "assistant",
      "content": "助手回复内容"
    }
  ]
}
```

#### Message 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `role` | string | 消息角色（"user" 或 "assistant"） |
| `content` | string | 消息内容 |

### 8. clarification_results 字段

澄清评分结果列表。

```json
{
  "clarification_results": [
    {
      "req_id": "REQ-001",
      "score": 1,
      "reason": "评分说明，包含理由和证据关键词，不超过30字",
      "evidence": "引用的基准证据信息（可选）"
    }
  ]
}
```

#### ClarificationResult 字段说明

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `req_id` | string | 需求ID |
| `score` | int | 评分值，范围 -2 到 +2 |
| `reason` | string | 评分说明，包含理由和证据关键词，不超过30字 |
| `evidence` | string \| null | 引用的基准证据信息（已合并到 reason 中，保留字段以兼容） |

### 9. gen_versions 字段

已生成的版本集合（序列化为列表）。

```json
{
  "gen_versions": ["v1", "v2", "v3"]
}
```

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `gen_versions` | array[string] | 已生成的版本标识列表 |

## 使用示例

### 查看 checkpoint 基本信息

```python
import json

with open("checkpoint_explore_iter1.json", "r", encoding="utf-8") as f:
    checkpoint = json.load(f)

print(f"节点: {checkpoint['node_name']}")
print(f"迭代: {checkpoint['iteration']}")
print(f"时间: {checkpoint['timestamp']}")
print(f"需求数量: {len(checkpoint['state']['requirements']['requirements'])}")
```

### 查看需求列表

```python
requirements = checkpoint['state']['requirements']['requirements']
for req in requirements:
    print(f"{req['id']}: {req['text']} (评分: {req['score']})")
```

### 查看评分历史

```python
score_history = checkpoint['state']['score_history']
for req_id, records in score_history.items():
    print(f"{req_id} 的评分历史:")
    for record in records:
        print(f"  迭代 {record['iteration']}: 评分 {record['score']}, 理由: {record['reason']}")
```

### 查看时间统计

```python
timer_manager = checkpoint['state']['timer_manager']
print(f"总开始时间: {timer_manager['total_start_time']}")
for name, timer in timer_manager['timers'].items():
    print(f"{name}: 累计时间 {timer['elapsed_time']}秒, 调用次数 {timer['call_count']}")
```

## 注意事项

1. **字段可选性**: 并非所有字段都会出现在每个 checkpoint 中，只有已设置的字段才会被保存。

2. **数据类型**: 
   - 时间戳使用 Unix 时间戳（浮点数）
   - 集合类型（如 `gen_versions`）会被序列化为列表

3. **评分范围**: 所有评分字段的值范围都是 -2 到 +2，其中：
   - -2: 完全不相关
   - -1: 不太相关
   - 0: 中性/不确定
   - +1: 相关
   - +2: 高度相关

4. **文件大小**: checkpoint 文件可能很大（几MB），因为包含了完整的对话历史、需求列表等数据。

5. **恢复状态**: 可以使用 `CheckpointManager.load_checkpoint()` 方法从 checkpoint 文件恢复工作流状态。

