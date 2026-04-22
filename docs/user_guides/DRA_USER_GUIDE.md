# Deep Research Agent (DRA) User Guide

**Version:** 1.0
**Phase:** 8 (Complete)
**Last Updated:** 2026-04-21

---

## Table of Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Research Sessions](#research-sessions)
4. [Trajectory Management](#trajectory-management)
5. [Configuration](#configuration)
6. [Best Practices](#best-practices)
7. [Troubleshooting](#troubleshooting)
8. [API Reference](#api-reference)

---

## Overview

The Deep Research Agent (DRA) is an autonomous research system that enables multi-turn research sessions over your paper corpus. Unlike single-shot API queries, DRA iteratively searches, opens papers, and synthesizes findings using a ReAct (Reasoning + Acting) architecture.

### Key Features

- **Multi-Turn Research:** Execute complex research questions requiring multiple search-reason-search cycles
- **Offline Corpus:** Research against your local paper corpus without live API dependencies
- **Hybrid Search:** Combine semantic (SPECTER2) and keyword (BM25) retrieval for comprehensive results
- **Trajectory Learning:** Learn from past sessions to improve future research quality
- **Citation Validation:** Verify claims against actual paper content

### When to Use DRA

| Use Case | DRA | Standard Discovery |
|----------|-----|-------------------|
| Find recent papers on a topic | | ✓ |
| Compare two approaches across papers | ✓ | |
| Gather evidence for a specific claim | ✓ | |
| Synthesize findings across multiple papers | ✓ | |
| Quick paper discovery | | ✓ |
| Deep multi-hop reasoning | ✓ | |

---

## Getting Started

### Prerequisites

1. **Python 3.14+** installed
2. **ARISP** configured with API keys
3. **Papers in registry** (run discovery first)

### Quick Start

```bash
# 1. Build the corpus from your paper registry
python -m src.cli research status  # Check if corpus exists

# 2. Run a research session
python -m src.cli research "What are the key innovations in the Transformer architecture?"

# 3. View results
# Results are displayed in the terminal with citations
```

### First Research Session

```bash
# Start with a focused question
python -m src.cli research "How does self-attention compare to RNN-based sequence modeling?"

# Use verbose mode to see the reasoning process
python -m src.cli research "What evidence supports attention mechanism effectiveness?" --verbose

# Process multiple questions from a file
python -m src.cli research --question-file my_questions.txt --output results.md
```

---

## Research Sessions

### Basic Usage

```bash
# Single question
python -m src.cli research "Your research question here"

# With options
python -m src.cli research "Question" --max-turns 30 --verbose

# From file (one question per line)
python -m src.cli research --question-file questions.txt

# Save output to file
python -m src.cli research "Question" --output results.md
```

### Command Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--config` | `-c` | Path to research config YAML | `config/research_config.yaml` |
| `--max-turns` | `-t` | Maximum turns per session | 50 |
| `--output` | `-o` | Output file for results | stdout |
| `--verbose` | `-v` | Show detailed progress | False |
| `--question-file` | `-f` | File with questions (one per line) | None |

### Understanding Results

Research results include:

```markdown
# Question: How does attention work?

## Answer
Attention mechanisms compute weighted sums of values based on query-key
similarity [paper1: section 3]. The Transformer uses multi-head attention
to capture different aspects of relationships [paper2: methods].

## Session Metadata
- **Turns:** 8
- **Papers consulted:** 3
- **Exhausted:** False
- **Duration:** 23.4s
- **Tokens used:** 12,450

## Papers Consulted
- `arxiv:1706.03762`
- `arxiv:1810.04805`
- `arxiv:2005.14165`
```

### Check DRA Status

```bash
# Show corpus statistics and DRA readiness
python -m src.cli research status
```

Output:
```
Deep Research Agent Status
========================================
✓ Corpus directory: ./data/dra/corpus
  Papers: 2,547
  Chunks: 48,230
  Tokens: 15,234,000
  Last updated: 2026-04-19 10:30:00
```

---

## Trajectory Management

Trajectories record your research sessions for analysis and learning.

### List Trajectories

```bash
# List recent trajectories
python -m src.cli trajectories list

# Filter by quality
python -m src.cli trajectories list --min-quality 0.7

# Show detailed information
python -m src.cli trajectories list --details --limit 10
```

Example output:
```
Found 15 trajectories
============================================================

✓ 20260419_143022_a1b2c3d4
  Question: How does self-attention scale with sequence length?
  Quality: [████████░░] 0.82 | Turns: 12 | Papers: 4
  Created: 2026-04-19 14:30

✗ 20260419_120515_e5f6g7h8
  Question: What are the limitations of transformer models?
  Quality: [████░░░░░░] 0.45 | Turns: 25 | Papers: 2
  Created: 2026-04-19 12:05
```

### Analyze Patterns

```bash
# Analyze trajectory patterns
python -m src.cli trajectories analyze

# With higher quality threshold
python -m src.cli trajectories analyze --min-quality 0.7

# Save analysis to file
python -m src.cli trajectories analyze --output analysis.json

# Skip tip generation
python -m src.cli trajectories analyze --no-tips
```

Example output:
```
📊 Trajectory Analysis Results
==================================================

🔍 Effective Query Patterns:
  1. attention
  2. transformer
  3. mechanisms
  4. self-attention
  5. bert

🔗 Successful Action Sequences:
  1. search -> open -> find
  2. search -> search -> open
  3. open -> find -> search

📈 Statistics:
  Average turns to success: 8.5

📚 Paper Consultation Patterns:
  methods: 45 times
  results: 38 times
  abstract: 25 times

💡 Learning Tips Generated:

  Tip 1 (confidence: 85%):
    Context: When searching for papers
    Strategy: Use terms like: attention, transformer, mechanisms...
```

### Export Trajectories

```bash
# Export as JSONL (ShareGPT format for fine-tuning)
python -m src.cli trajectories export --output training_data.jsonl

# Export as JSON (full trajectory data)
python -m src.cli trajectories export --output data.json --format json

# Export as CSV (summary statistics)
python -m src.cli trajectories export --output stats.csv --format csv

# Filter exports
python -m src.cli trajectories export --output high_quality.jsonl --min-quality 0.8
python -m src.cli trajectories export --output all_data.jsonl --include-failed
```

### View Statistics

```bash
python -m src.cli trajectories stats
```

Example output:
```
📊 Trajectory Storage Statistics
==================================================

  Total trajectories: 127
  With answers: 98 (77%)
  Without answers: 29

  Average quality score: 0.68
  Average turns: 11.2
  Total tokens processed: 1,543,200

  Quality distribution:
    High (≥0.7): 45 (35%)
    Medium (0.4-0.7): 52 (41%)
    Low (<0.4): 30 (24%)

  Storage directory: ./data/dra/trajectories
  Storage size: 12.45 MB

  Oldest: 2026-03-15 09:22
  Newest: 2026-04-19 14:30
```

### Clear Trajectories

```bash
# Clear all (with confirmation)
python -m src.cli trajectories clear

# Force clear without confirmation
python -m src.cli trajectories clear --force

# Clear old trajectories only
python -m src.cli trajectories clear --older-than 30  # Days
```

---

## Configuration

### DRA Settings in research_config.yaml

```yaml
# Existing config sections...
research_topics:
  - query: "attention mechanisms"
    # ...

# DRA-specific settings (optional)
dra_settings:
  corpus:
    embedding_model: "allenai/specter2"
    chunk_max_tokens: 512
    chunk_overlap_tokens: 64
    embedding_batch_size: 32

  search:
    dense_weight: 0.7        # SPECTER2 weight
    sparse_weight: 0.3       # BM25 weight
    default_top_k: 10
    max_top_k: 50

  agent:
    max_turns: 50
    max_context_tokens: 128000
    max_session_duration_seconds: 600
    max_open_documents: 20
    llm_provider: "claude"
    llm_model: "claude-sonnet-4-20250514"

  trajectory_learning:
    enable_learning: true
    min_trajectories_for_analysis: 10
    learning_refresh_interval_hours: 24
    quality_threshold: 0.6

  # Custom storage directories (optional)
  corpus_dir: "./data/dra/corpus"
  trajectory_dir: "./data/dra/trajectories"
```

### Environment Variables

```bash
# Required for LLM access
export LLM_API_KEY="your_api_key"

# Optional: Override default directories
export DRA_CORPUS_DIR="./custom/corpus"
export DRA_TRAJECTORY_DIR="./custom/trajectories"
```

---

## Best Practices

### Writing Effective Questions

**Good Questions:**
- "How does the Transformer attention mechanism compare to LSTM gating?"
- "What evidence supports the effectiveness of pre-training for NLP tasks?"
- "What are the computational trade-offs between different attention variants?"

**Less Effective Questions:**
- "Tell me about transformers" (too vague)
- "What is machine learning?" (too broad)
- "Paper summary" (not a question)

### Maximizing Research Quality

1. **Be Specific:** Include technical terms and specific concepts
2. **Request Comparisons:** "Compare X to Y" questions yield structured answers
3. **Ask for Evidence:** "What evidence supports..." triggers citation gathering
4. **Use Follow-ups:** After initial research, refine with more specific questions

### Corpus Management

1. **Keep Corpus Fresh:** Run discovery regularly to add new papers
2. **Quality Over Quantity:** A focused corpus often yields better results
3. **Check Coverage:** Use `python -m src.cli research status` to verify corpus health

### Trajectory Learning

1. **Review Quality Scores:** High-quality trajectories improve future sessions
2. **Analyze Patterns:** Regular analysis reveals effective research strategies
3. **Export for Training:** Use high-quality trajectories for fine-tuning

---

## Troubleshooting

### Common Issues

#### "Corpus is empty"

```bash
# Check corpus status
python -m src.cli research status

# If empty, ensure papers are in registry
python -m src.cli catalog show

# Corpus is automatically built from registry papers
```

#### "No answer produced"

Possible causes:
- Question too vague or broad
- Corpus doesn't contain relevant papers
- Max turns exhausted without finding answer

Solutions:
- Make question more specific
- Increase `--max-turns`
- Check if relevant papers exist in corpus

#### "LLM service initialization failed"

```bash
# Check LLM configuration
cat config/research_config.yaml | grep -A 5 llm_settings

# Verify API key is set
echo $LLM_API_KEY

# Check API key in .env file
cat .env | grep LLM
```

#### "Trajectory storage not found"

```bash
# Create storage directory
mkdir -p ./data/dra/trajectories

# Or update config to use existing directory
```

### Performance Tips

1. **Reduce Max Turns:** Lower `--max-turns` for faster (but potentially shallower) results
2. **Use Specific Questions:** Focused questions complete faster
3. **Monitor Token Usage:** Check session metadata for token consumption
4. **Batch Processing:** Use `--question-file` for multiple questions

### Getting Help

```bash
# Show all DRA commands
python -m src.cli research --help
python -m src.cli trajectories --help

# Check ARISP version and dependencies
python -m src.cli health
```

---

## API Reference

### CLI Commands

#### `python -m src.cli research`

Execute deep research sessions.

```bash
python -m src.cli research [QUESTION] [OPTIONS]
```

| Argument/Option | Description |
|-----------------|-------------|
| `QUESTION` | Research question (optional if using --question-file) |
| `--question-file, -f` | File with questions (one per line) |
| `--config, -c` | Config file path |
| `--max-turns, -t` | Maximum turns (1-200) |
| `--output, -o` | Output file path |
| `--verbose, -v` | Show detailed progress |

#### `python -m src.cli research status`

Show DRA status and corpus statistics.

```bash
python -m src.cli research status [OPTIONS]
```

#### `python -m src.cli trajectories list`

List recorded trajectories.

```bash
python -m src.cli trajectories list [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--limit, -n` | Max trajectories to display |
| `--min-quality, -q` | Minimum quality score filter |
| `--details, -d` | Show detailed information |

#### `python -m src.cli trajectories analyze`

Analyze trajectory patterns.

```bash
python -m src.cli trajectories analyze [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--min-quality, -q` | Minimum quality for analysis |
| `--tips/--no-tips` | Generate learning tips |
| `--output, -o` | Output file (JSON) |

#### `python -m src.cli trajectories export`

Export trajectories.

```bash
python -m src.cli trajectories export --output FILE [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--output, -o` | Output file path (required) |
| `--format, -f` | Export format: jsonl, json, csv |
| `--min-quality, -q` | Minimum quality score |
| `--include-failed` | Include failed sessions |

#### `python -m src.cli trajectories stats`

Show storage statistics.

```bash
python -m src.cli trajectories stats [OPTIONS]
```

#### `python -m src.cli trajectories clear`

Clear trajectory storage.

```bash
python -m src.cli trajectories clear [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--force, -f` | Skip confirmation |
| `--older-than` | Only clear trajectories older than N days |

---

## Appendix

### Data Models

#### ResearchResult

```python
class ResearchResult(BaseModel):
    question: str
    answer: str | None
    trajectory: list[Turn]
    papers_consulted: list[str]
    total_turns: int
    exhausted: bool
    total_tokens: int
    duration_seconds: float
```

#### TrajectoryRecord

```python
class TrajectoryRecord(BaseModel):
    trajectory_id: str
    question: str
    answer: str | None
    turns: list[Turn]
    quality_score: float  # 0.0-1.0
    papers_opened: int
    unique_searches: int
    find_operations: int
    context_length_tokens: int
    created_at: datetime
```

### File Locations

| File/Directory | Purpose |
|----------------|---------|
| `./data/dra/corpus/` | Indexed paper corpus |
| `./data/dra/trajectories/` | Recorded research sessions |
| `./config/research_config.yaml` | DRA configuration |

### Quality Score Factors

Quality scores (0.0-1.0) are computed from:

| Factor | Weight | Criteria |
|--------|--------|----------|
| Answer Success | 0.4 | Produced answer without exhausting |
| Turn Efficiency | 0.2 | 3-30 turns (optimal range) |
| Paper Breadth | 0.2 | Consulted 2+ papers |
| Expert Alignment | 0.2 | Matches expert seed patterns |

---

*For more information, see the [Phase 8 DRA Specification](../specs/PHASE_8_DRA_SPEC.md).*
