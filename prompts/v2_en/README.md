# Prompt Version 2 (English)

## Overview

Version 2 prompts are enhanced versions designed to improve performance in key evaluation dimensions:
- Business Process Completeness
- Exception Handling Coverage
- Data and State Integrity
- Consistency and Conflict Detection

## Key Improvements

### req_explore.md
- Added explicit focus on four critical dimensions when supplementing new requirements
- Emphasized business process workflows, exception handling, data models, and consistency checks
- Provides detailed guidance on what to include in each dimension

### req_clarify.md
- Added additional evaluation criteria for consistency and completeness
- Requirements with good consistency and completeness receive higher scores
- Enhanced scoring rationale to consider cross-requirement validation

### doc_generate.md
- Added required document structure sections:
  - Business Process Description
  - Exception Handling Section
  - Data Model Section
  - Consistency Assurance
- Ensures comprehensive coverage of all critical dimensions

### req_parse.md
- No changes from v1 (maintains compatibility)

## Usage

Set the prompt version when running the system:
```bash
python main.py input.txt --prompt-version v2
```

Or set the environment variable:
```bash
export PROMPT_VERSION=v2
python main.py input.txt
```

## Expected Improvements

With v2 prompts, you should see:
- Better coverage of business processes
- More comprehensive exception handling
- Improved data and state descriptions
- Enhanced consistency between requirements
- Higher scores in BUSINESS_FLOW, EXCEPTION, DATA_STATE, and CONSISTENCY_RULE dimensions

