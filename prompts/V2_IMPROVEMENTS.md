# 提示词版本 2 改进说明

## 创建的文件

### 英文版本 (v2_en/)
- `req_explore.md` - 需求挖掘提示词（增强版）
- `req_clarify.md` - 需求澄清提示词（增强版）
- `doc_generate.md` - 文档生成提示词（增强版）
- `req_parse.md` - 需求解析提示词（与v1相同）
- `README.md` - 版本说明文档

### 中文版本 (v2_zh/)
- `req_explore.md` - 需求挖掘提示词（增强版）
- `req_clarify.md` - 需求澄清提示词（增强版）
- `doc_generate.md` - 文档生成提示词（增强版）
- `req_parse.md` - 需求解析提示词（与v1相同）
- `README.md` - 版本说明文档

## 主要改进内容

### 1. req_explore.md（需求挖掘阶段）

**新增内容**：明确要求关注四个关键维度

#### 英文版本新增：
```markdown
**Critical Dimensions to Focus On When Supplementing New Requirements:**

1. **Business Process Completeness**:
   - Complete operational workflows and step-by-step procedures
   - User-system interaction sequences
   - Business process state transitions
   - Preconditions and postconditions for operations
   - Sequential operations and their dependencies
   - Workflow branching and decision points

2. **Exception Handling Coverage**:
   - Various exception scenarios and their handling mechanisms
   - Error recovery strategies and fallback procedures
   - Boundary condition handling
   - System failure behaviors and recovery
   - Input validation and error messages
   - Timeout and retry mechanisms

3. **Data and State Integrity**:
   - Data models and data structures
   - State transition rules and state machines
   - Data constraints and validation rules
   - Data persistence requirements
   - Data consistency guarantees
   - Data lifecycle management

4. **Consistency and Conflict Detection**:
   - Consistency between requirements
   - Avoidance of conflicts and contradictions
   - Logical consistency assurance
   - Cross-requirement validation
   - Requirement traceability
```

#### 中文版本新增：
```markdown
**补充新需求时必须特别关注的关键维度：**

1. **业务流程完整性**：
   - 完整的操作流程和步骤程序
   - 用户与系统的交互序列
   - 业务流程的状态转换
   - 操作的前置条件和后置条件
   - 顺序操作及其依赖关系
   - 工作流分支和决策点

2. **异常处理覆盖度**：
   - 各种异常场景及其处理机制
   - 错误恢复策略和回退程序
   - 边界条件处理
   - 系统故障行为和恢复
   - 输入验证和错误消息
   - 超时和重试机制

3. **数据与状态完整性**：
   - 数据模型和数据结构
   - 状态转换规则和状态机
   - 数据约束和验证规则
   - 数据持久化要求
   - 数据一致性保证
   - 数据生命周期管理

4. **一致性/冲突检测**：
   - 需求之间的一致性
   - 避免冲突和矛盾
   - 逻辑一致性保证
   - 跨需求验证
   - 需求可追溯性
```

### 2. req_clarify.md（需求澄清阶段）

**新增内容**：额外评估标准

#### 英文版本新增：
```markdown
**Additional Evaluation Criteria:**

When scoring requirements, in addition to considering compliance with the baseline SRS, you should also evaluate:

1. **Consistency Check**:
   - Whether there are conflicts between requirements
   - Whether requirement descriptions are logically consistent
   - Whether requirements contradict existing requirements
   - Cross-requirement validation

2. **Completeness Check**:
   - Whether business processes are covered
   - Whether exception handling is included
   - Whether data states are described
   - Whether boundary conditions are addressed

Requirements that demonstrate good consistency and completeness should receive higher scores, even if they are slightly different from the baseline SRS in wording.
```

#### 中文版本新增：
```markdown
**额外评估标准：**

在评分时，除了考虑与基准SRS的符合度，还应评估：

1. **一致性检查**：
   - 需求之间是否存在冲突
   - 需求描述是否逻辑一致
   - 是否与已存在的需求矛盾
   - 跨需求验证

2. **完整性检查**：
   - 是否覆盖了业务流程
   - 是否包含了异常处理
   - 是否描述了数据状态
   - 是否处理了边界条件

对于表现出一致性和完整性的需求，即使与基准SRS在表述上略有不同，也应给予较高评分。
```

### 3. doc_generate.md（文档生成阶段）

**新增内容**：必需的文档结构

#### 英文版本新增：
```markdown
**Required Document Structure:**

The generated SRS document must include the following sections to ensure comprehensive coverage:

1. **Business Process Description**:
   - Detailed operational workflows
   - User interaction sequences
   - State transition diagrams (if applicable)
   - Step-by-step procedures
   - Preconditions and postconditions

2. **Exception Handling Section**:
   - Various exception scenarios and their handling
   - Error recovery mechanisms
   - Boundary condition handling
   - System failure behaviors
   - Input validation and error messages
   - Timeout and retry mechanisms

3. **Data Model Section**:
   - Data structure definitions
   - State transition rules
   - Data constraints and validation rules
   - Data persistence requirements
   - Data consistency guarantees

4. **Consistency Assurance**:
   - Consistency between requirements
   - Conflict avoidance descriptions
   - Logical consistency statements
   - Cross-requirement validation
```

#### 中文版本新增：
```markdown
**必需的文档结构：**

生成的SRS文档必须包含以下章节，确保全面覆盖：

1. **业务流程描述**：
   - 详细的操作流程
   - 用户交互序列
   - 状态转换图（如适用）
   - 步骤程序
   - 前置条件和后置条件

2. **异常处理章节**：
   - 各种异常场景及其处理
   - 错误恢复机制
   - 边界条件处理
   - 系统故障行为
   - 输入验证和错误消息
   - 超时和重试机制

3. **数据模型章节**：
   - 数据结构定义
   - 状态转换规则
   - 数据约束和验证规则
   - 数据持久化要求
   - 数据一致性保证

4. **一致性保证**：
   - 需求之间的一致性
   - 避免冲突的描述
   - 逻辑一致性说明
   - 跨需求验证
```

## 使用方法

### 方法1：通过命令行参数
```bash
python main.py input.txt --prompt-version v2
```

### 方法2：通过环境变量
```bash
export PROMPT_VERSION=v2
python main.py input.txt
```

### 方法3：在代码中设置
```python
from src.config import Config
Config.PROMPT_VERSION = "v2"
```

## 预期效果

使用 v2 提示词后，预期能够：

1. **提升业务流程完整性**：
   - 更完整的工作流程描述
   - 更详细的用户交互序列
   - 更清晰的状态转换

2. **提升异常处理覆盖度**：
   - 更全面的异常场景覆盖
   - 更详细的错误处理机制
   - 更完善的边界条件处理

3. **提升数据与状态完整性**：
   - 更完整的数据模型描述
   - 更清晰的状态转换规则
   - 更详细的数据约束

4. **提升一致性/冲突检测**：
   - 更好的需求一致性
   - 更少的冲突和矛盾
   - 更强的逻辑一致性

## 验证建议

1. **小规模测试**：选择几个文档，使用 v2 提示词重新生成
2. **评估对比**：对比 v1 和 v2 的评估结果
3. **维度分析**：特别关注 BUSINESS_FLOW、EXCEPTION、DATA_STATE、CONSISTENCY_RULE 维度的得分变化
4. **逐步推广**：如果效果良好，逐步应用到所有文档

## 注意事项

1. v2 提示词会生成更详细的需求和文档，可能会增加生成时间
2. 需要确保评估系统能够正确识别这些新增的内容
3. 建议在正式使用前进行充分测试

## 版本对比

| 特性 | v1 | v2 |
|------|----|----|
| 业务流程强调 | ❌ | ✅ |
| 异常处理强调 | ❌ | ✅ |
| 数据状态强调 | ❌ | ✅ |
| 一致性检查 | ❌ | ✅ |
| 文档结构要求 | 基础 | 增强 |

