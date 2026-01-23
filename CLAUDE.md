# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Automated Research Ingestion & Synthesis Pipeline (ARISP)** automates the discovery, extraction, and synthesis of cutting-edge AI research papers based on user-defined research topics. The pipeline runs on-demand or scheduled, fetches PDFs, converts them to Markdown, extracts code and prompts using an LLM, and outputs Obsidian-ready markdown briefs for engineering teams.

**Key Features:**
- **Configurable Topics:** Research topics are read from `research_config.yaml` (user-editable)
- **Flexible Timeframes:** Query papers from any time period (48 hours, 1 year, since 2008, etc.)
- **Intelligent Cataloging:** Detects duplicate/overlapping topics and appends to existing research folders
- **Daily Variation:** Topics can change each day via config updates

## Tech Stack
* **Language:** Python 3.10+
* **PDF Parser:** `marker-pdf` (preserves code syntax during PDF-to-MD conversion)
* **APIs:** Semantic Scholar API (discovery), Gemini 1.5 Pro or Claude 3.5 Sonnet (extraction)
* **Environment:** `pip` + `venv` / `dotenv` for secrets

## Development Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.template .env
# Then edit .env and add your API keys
```

## Configuration Files

### `.env` (API Keys - DO NOT commit)
```bash
SEMANTIC_SCHOLAR_API_KEY=your_key_here
LLM_API_KEY=your_gemini_or_anthropic_key
```

### `research_config.yaml` (User-editable research parameters)
```yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    timeframe:
      type: "recent"  # or "since_year", "date_range"
      value: "48h"    # or year: 2008, or start/end dates
  - query: "reinforcement learning AND robotics"
    timeframe:
      type: "since_year"
      value: 2020

# Global settings
max_papers_per_topic: 50
output_base_dir: "./output"
enable_duplicate_detection: true
```

**Timeframe Options:**
- `recent`: Last N hours/days (e.g., "48h", "7d")
- `since_year`: All papers from specified year onwards (e.g., 2008)
- `date_range`: Custom start and end dates

## Common Development Commands

```bash
# Run the full pipeline (reads from research_config.yaml)
python main.py

# Run with custom config file
python main.py --config custom_research.yaml

# Test configuration loading
python config_manager.py --validate research_config.yaml

# Run individual modules (for testing/debugging)
python search.py --topic "reinforcement learning" --timeframe since_year:2020
python pdf_processor.py --pdf-url "https://example.com/paper.pdf"
python llm_extractor.py --markdown-file "./temp_md/paper.md"

# View catalog
python config_manager.py --show-catalog

# Run tests (when implemented)
pytest tests/

# Format code
black .

# Type checking
mypy .
```

## Architecture

The pipeline consists of five main modules:

1. **`config_manager.py`** - Configuration and catalog management
   - Reads and validates `research_config.yaml`
   - Manages output directory structure: `./output/{topic_slug}/`
   - Detects duplicate/overlapping topics using topic normalization and hashing
   - Determines whether to create new folder or append to existing
   - Maintains a catalog index (e.g., `catalog.json`) tracking all research runs

2. **`search.py`** - Semantic Scholar integration
   - Reads topics from config manager
   - Builds queries with configurable timeframes
   - Returns list with `title`, `abstract`, `url`, `openAccessPdf`, `publicationDate`

3. **`pdf_processor.py`** - PDF download and conversion
   - Downloads PDFs from `openAccessPdf` links
   - Runs `marker_single {pdf_path} --output_dir ./temp_md/`
   - Extracts resulting markdown

4. **`llm_extractor.py`** - Code and prompt extraction
   - Feeds markdown to LLM (1M+ token context)
   - Extracts: `tot_system_prompt`, `tot_user_prompt_template`, `python_code_snippet`, `engineering_summary`
   - Returns valid JSON

5. **`main.py`** - Pipeline orchestration
   - Loads config via `config_manager`
   - Processes each topic in `research_config.yaml`
   - For each topic, determines output location (new or existing)
   - Generates markdown: `./output/{topic_slug}/YYYY-MM-DD_Research.md`
   - Updates catalog index

## Coding Standards
* **Modularity:** Separate concerns across the five main modules
* **Error Handling:** Implement robust try/except blocks and exponential backoff for API rate limits
* **Logging:** Use Python's `logging` module, not `print()` for system events
* **Type Hints:** Required for all function signatures

## Key Implementation Details

### Configuration Management (`config_manager.py`)
- **Topic Normalization:** Convert query strings to slugs for folder names (e.g., `"Tree of Thoughts AND machine translation"` → `tot-machine-translation`)
- **Duplicate Detection:** Use normalized topic strings or hash to match existing research
- **Catalog Structure:** Maintain `catalog.json` with:
  ```json
  {
    "tot-machine-translation": {
      "query": "Tree of Thoughts AND machine translation",
      "folder": "tot-machine-translation",
      "runs": [
        {"date": "2025-01-23", "papers_found": 15, "timeframe": "48h"},
        {"date": "2025-01-25", "papers_found": 8, "timeframe": "48h"}
      ]
    }
  }
  ```
- **Appending Logic:** If topic exists in catalog, append to existing folder; otherwise create new

### Semantic Scholar API (`search.py`)
- **Query:** Read from `research_config.yaml` (e.g., `"Tree of Thoughts AND machine translation"`)
- **Timeframe Handling:**
  - For `recent`: Convert to date range (e.g., "48h" → last 2 days)
  - For `since_year`: Filter `publicationDateOrYear >= 2008`
  - For `date_range`: Use exact start/end dates
- **Output format:** List of dicts with `title`, `abstract`, `url`, `openAccessPdf`, `publicationDate`

### PDF Conversion (`pdf_processor.py`)
- **Tool:** `marker_single {pdf_path} --output_dir ./temp_md/`
- Use `subprocess` module for better error handling than `os.system`
- Handle cases where PDFs are not open access or conversion fails

### LLM Extraction (`llm_extractor.py`)
- **Required output fields:** `tot_system_prompt`, `tot_user_prompt_template`, `python_code_snippet`, `engineering_summary`
- Must return valid JSON
- Handle LLM API rate limits and long documents (1M+ tokens)

### Output Format (`main.py`)
- **Directory Structure:**
  ```
  ./output/
    ├── catalog.json                    # Master index of all research
    ├── tot-machine-translation/        # Topic-based folders
    │   ├── 2025-01-23_Research.md
    │   ├── 2025-01-25_Research.md
    │   └── papers/                     # Downloaded PDFs
    └── rl-robotics/
        ├── 2025-01-24_Research.md
        └── papers/
  ```
- **Markdown Format:** Obsidian-compatible with YAML frontmatter
  ```markdown
  ---
  topic: "Tree of Thoughts AND machine translation"
  date: 2025-01-23
  papers_processed: 15
  timeframe: "48h"
  ---

  # Research Brief: ToT in Machine Translation

  ## Papers Found
  ...

  ## Extracted Prompts & Code
  ...

  ## Engineering Summary
  ...
  ```
- **Appending Behavior:** When topic is rerun, create new dated file in same folder, don't overwrite

## Dependencies (requirements.txt)
```
requests
python-dotenv
google-generativeai  # or anthropic
marker-pdf
pyyaml              # for config file parsing
```

## Output Directory Management

**Critical Behaviors:**
1. **Topic Slug Generation:** Normalize queries to filesystem-safe folder names
2. **Duplicate Detection:** Before creating new folder, check if normalized topic exists in `catalog.json`
3. **Appending:** When re-running same topic, add new dated markdown file to existing folder
4. **Catalog Updates:** After each run, update `catalog.json` with run metadata
5. **Paper Deduplication:** Within a topic folder, track paper DOIs/IDs to avoid re-processing same papers
