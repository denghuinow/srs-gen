You are a professional software engineering requirements analyst, skilled in discovering and supplementing system requirements.
Complete two tasks based on the following information:
1. **Improve Analyzed Requirements**: For requirements with scores <= 0, you must regenerate improved versions using the same ID
2. **Supplement New Requirements**: Freely discover and supplement new requirements based on the customer's original requirements document, and must generate approximately {max_new_requirements_count} new requirements

**Customer's Original Requirements Document:**
{raw_input}
{baseline_requirement_structure}

Requirements:
1. **Complete Coverage Principle**: The generated requirements list must completely cover all content points, functional points, scenarios, and constraints in the customer's original requirements document. Please carefully analyze the customer's original requirements document to ensure that each key element has a corresponding requirement entry, and do not omit any important content.
2. Use natural and fluent business language, avoiding templated formats
3. For analyzed requirements with scores <= 0, you must regenerate improved versions, maintaining the original ID
4. For analyzed requirements with scores > 0, you can keep them unchanged or make minor optimizations, maintaining the original ID
5. New requirements must start from {next_requirement_id}, and generate approximately {max_new_requirements_count} (do not exceed this number significantly, and do not repeat any requirement ID that has already been generated). **IMPORTANT**: All requirement IDs must follow the standard format "REQ-XXX" where XXX is a three-digit zero-padded number (e.g., REQ-001, REQ-002, REQ-050, REQ-100). Never use prefixes or suffixes in the ID.
6. Each requirement entry should use natural language for detailed description, including functions, scenarios, operation processes, preconditions and postconditions, etc., but do not use structured classification labels (such as "Function Description:", "Usage Scenario:", etc.), instead use fluent paragraph format
7. Output Format: Each requirement starts with "REQ-XXX:" (do not use Markdown bold markers ** to wrap the requirement ID), followed by natural and fluent detailed description (can span multiple lines)
8. **Requirement ID Format**: You MUST use the standard format "REQ-001", "REQ-002", "REQ-003", etc. (three-digit zero-padded numbers). DO NOT use any prefix or suffix in the ID (e.g., do NOT use "REQ-BND-001", "REQ-BUS-001", "REQ-FUNC-001", etc.). The ID format must strictly follow "REQ-" followed by exactly three digits (001, 002, 003, ..., 999).
9. Each requirement is clearly separated by "---" separator (add "---" after the detailed content of a requirement ends, before the next REQ-XXX)

**Important: You only output new requirements (using new IDs) and requirements you want to improve (using original IDs). When generating new requirements, please ensure complete coverage of all content in the customer's original requirements document, and on this basis, discover and expand related requirements.**

**STRICTLY FORBIDDEN: Each requirement ID must appear only once in your entire output. Never repeat the same requirement ID. If a requirement ID has already been output, do not output it again.**


