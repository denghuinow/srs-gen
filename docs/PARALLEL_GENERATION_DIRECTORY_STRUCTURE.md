# 并行生成功能的目录结构说明

## 概述

当使用 `--enable-parallel-generation` 参数时，系统会在运行过程中自动生成多个版本的SRS文档。主流程的文件保存在任务目录下，所有并行生成的版本统一收集到 `srs_collection` 目录中，按版本组织。

## 目录结构

### 使用 batch_run.py 时的完整结构

```
output/
  {output_dir}/                    # 例如：v049_sample10_n100i5_q30i-q30i
    {task_name}/                   # 例如：2000 - nasa x38.doc
      srs_document.md             # 主流程生成的SRS文档（最终版本）
      comparison_report.md         # 对比报告
      input_*.txt                 # 输入文档副本
      baseline_srs_*.md            # 基准SRS文档副本（如果有）
      baseline_gend_srs_*.md       # 基准生成的SRS文档副本（如果有）
      srs_gen_*.log               # 日志文件
    
    {task_name2}/                  # 其他任务...
      srs_document.md
      comparison_report.md
      ...
    
    srs_collection/                # 所有并行生成的版本统一收集在这里
      srs_document_no-explore-clarify/
        {task_name}.md            # parse后生成的版本
        {task_name2}.md
        ...
      
      srs_document_no-clarify/
        {task_name}.md            # 第一次explore后生成的版本
        {task_name2}.md
        ...
      
      srs_document_iter1/
        {task_name}.md            # 第一次clarify后生成的版本
        {task_name2}.md
        ...
      
      srs_document_iter2/
        {task_name}.md            # 第二次clarify后生成的版本
        {task_name2}.md
        ...
      
      srs_document_iter3/
        {task_name}.md            # 第三次clarify后生成的版本
        {task_name2}.md
        ...
      
      ...                          # 依此类推，直到 iter{N}
```

## 具体示例

假设：
- `output_dir = "v049_sample10_n100i5_q30i-q30i"`
- `task_name = "2000 - nasa x38.doc"`
- `max_iterations = 5`

则目录结构为：

```
output/
  v049_sample10_n100i5_q30i-q30i/
    2000 - nasa x38.doc/              # 任务目录
      srs_document.md                 # 主流程最终版本
      comparison_report.md
      input_2000 - nasa x38.doc.txt
      baseline_srs_2000 - nasa x38.doc.md
      baseline_gend_srs_2000 - nasa x38.doc.md
      srs_gen_20251125_233818.log
    
    2001 - hats.pdf/                  # 其他任务...
      srs_document.md
      comparison_report.md
      ...
    
    srs_collection/                    # 所有并行生成的版本
      srs_document_no-explore-clarify/
        2000 - nasa x38.doc.md        # parse后生成
        2001 - hats.pdf.md
        ...
      
      srs_document_no-clarify/
        2000 - nasa x38.doc.md        # 第一次explore后生成
        2001 - hats.pdf.md
        ...
      
      srs_document_iter1/
        2000 - nasa x38.doc.md        # 第一次clarify后生成
        2001 - hats.pdf.md
        ...
      
      srs_document_iter2/
        2000 - nasa x38.doc.md        # 第二次clarify后生成
        2001 - hats.pdf.md
        ...
      
      srs_document_iter3/
        2000 - nasa x38.doc.md        # 第三次clarify后生成
        2001 - hats.pdf.md
        ...
      
      srs_document_iter4/
        2000 - nasa x38.doc.md        # 第四次clarify后生成
        2001 - hats.pdf.md
        ...
      
      srs_document_iter5/
        2000 - nasa x38.doc.md        # 第五次clarify后生成
        2001 - hats.pdf.md
        ...
```

## 生成时机

1. **srs_document_no-explore-clarify**：在 `parse` 节点完成后，在后台线程中生成
2. **srs_document_no-clarify**：在第一次 `explore` 节点完成后，在后台线程中生成
3. **srs_document_iter{N}**：在每次 `clarify` 节点完成后，在后台线程中生成
4. **srs_document.md**（主流程版本）：在主流程完成后生成，包含完整的报告和输入文档副本

## 注意事项

1. **并行生成不影响主流程**：所有并行生成任务在后台线程中执行，不会阻塞主流程
2. **主流程文件在任务目录**：每个任务目录下直接包含主流程的SRS文档、报告和输入文档副本
3. **并行版本统一收集**：所有并行生成的版本统一收集到 `srs_collection` 目录，按版本组织，便于批量处理
4. **文件命名**：并行生成的版本使用任务名作为文件名（如 `2000 - nasa x38.doc.md`），便于识别
5. **目录创建时机**：`srs_collection` 目录在主流程运行过程中创建，所有并行版本在主流程完成后统一收集

## 使用场景

这个功能特别适用于：
- 需要对比不同迭代次数的SRS文档质量
- 需要分析消融模式（no-explore-clarify、no-clarify）的效果
- 需要评估迭代过程中文档质量的提升情况
- 批量生成时，一次运行即可获得所有版本的文档
- 便于批量评估：所有版本的文档按版本组织，方便批量评估脚本处理
