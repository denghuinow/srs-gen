"""IEEE 830标准SRS模板"""
from typing import List
from .requirement import Requirement


class SRSTemplate:
    """IEEE 830标准SRS文档模板"""
    
    @staticmethod
    def generate(requirements: List[Requirement], project_name: str = "项目") -> str:
        """生成IEEE 830格式的SRS文档"""
        
        # 分类需求
        functional_reqs = []
        non_functional_reqs = []
        
        for req in requirements:
            text_lower = req.text.lower()
            # 简单启发式分类：包含性能、安全、可用性等关键词的归为非功能性需求
            if any(keyword in text_lower for keyword in [
                "性能", "响应时间", "吞吐量", "并发", "安全", "加密", 
                "可用性", "可靠性", "可维护性", "可扩展性", "兼容性"
            ]):
                non_functional_reqs.append(req)
            else:
                functional_reqs.append(req)
        
        # 生成文档
        doc = f"""# 软件需求规格说明书 (SRS)

## 1. 引言

### 1.1 目的
本文档描述了{project_name}的软件需求规格说明。

### 1.2 范围
本文档定义了系统的功能性和非功能性需求。

### 1.3 定义、首字母缩写词和缩略语
（待补充）

### 1.4 参考资料
（待补充）

### 1.5 概述
本文档的其余部分按以下方式组织：
- 第2节：总体描述
- 第3节：系统特性
- 第4节：非功能性需求

## 2. 总体描述

### 2.1 产品概述
（待补充）

### 2.2 产品功能
系统应提供以下主要功能：
- 需求解析与挖掘
- 需求澄清与评分
- SRS文档生成

### 2.3 用户特征
（待补充）

### 2.4 约束
（待补充）

### 2.5 假设和依赖关系
（待补充）

## 3. 系统特性

### 3.1 功能需求

"""
        
        # 添加功能性需求
        for req in functional_reqs:
            doc += f"#### {req.id}\n"
            doc += f"{req.text}\n\n"
        
        # 添加非功能性需求
        if non_functional_reqs:
            doc += "## 4. 非功能性需求\n\n"
            for req in non_functional_reqs:
                doc += f"#### {req.id}\n"
                doc += f"{req.text}\n\n"
        
        return doc
