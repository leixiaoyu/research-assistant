# Provider Selection Guide

This guide explains how the multi-provider intelligence system selects the optimal provider for your research queries.

---

## Available Providers

### ArXiv

**Best for:** AI, machine learning, physics, mathematics, computer science pre-prints

| Capability | Value |
|------------|-------|
| **Coverage** | ~2.4M papers (focused domains) |
| **PDF Access** | 100% (all open access) |
| **Citation Data** | Not available |
| **API Key Required** | No |
| **Rate Limit** | 3 requests/second |

**Strengths:**
- Guaranteed PDF access for all papers
- Fast queries (no authentication overhead)
- Excellent for cutting-edge AI/ML research
- Pre-print access (before peer review)

**Domains:**
- Physics (hep-th, hep-ph, quant-ph, cond-mat, astro-ph)
- Mathematics
- Computer Science (cs.ai, cs.lg, cs.cl, cs.cv)
- Statistics (stat.ml)
- Quantitative Biology (q-bio)
- Quantitative Finance (q-fin)
- Economics (econ)

### Semantic Scholar

**Best for:** Cross-disciplinary research, citation-based filtering, broad coverage

| Capability | Value |
|------------|-------|
| **Coverage** | 200M+ papers (all disciplines) |
| **PDF Access** | ~60% (varies by source) |
| **Citation Data** | Full citation counts |
| **API Key Required** | Yes |
| **Rate Limit** | 100 requests/minute |

**Strengths:**
- Massive coverage across all academic fields
- Citation data for quality filtering
- Cross-disciplinary research enabled
- Semantic search capabilities

**Domains:**
- All academic disciplines
- Medicine, Biology, Chemistry
- Psychology, Sociology
- Humanities, History, Philosophy
- And more...

---

## Automatic Provider Selection

When `auto_select_provider: true` (default), the system automatically selects the optimal provider using this priority order:

### Priority 1: Citation Requirements

If your query includes `min_citations`, Semantic Scholar is automatically selected because ArXiv doesn't provide citation data.

```yaml
- query: "reinforcement learning robotics"
  min_citations: 10  # Automatically uses Semantic Scholar
```

### Priority 2: ArXiv-Specific Terms

Queries containing these terms prefer ArXiv:

- `arxiv`, `preprint`
- ArXiv categories: `cs.ai`, `cs.lg`, `cs.cl`, `cs.cv`, `stat.ml`
- Physics terms: `physics`, `quant-ph`, `hep-th`, `hep-ph`, `cond-mat`, `astro-ph`
- Other categories: `math.`, `q-bio`, `q-fin`, `eess`, `econ`

```yaml
- query: "cs.ai attention mechanisms"  # Uses ArXiv
- query: "physics simulation quantum"  # Uses ArXiv
```

### Priority 3: Cross-Disciplinary Terms

Queries containing these terms prefer Semantic Scholar:

- Medical: `medicine`, `medical`, `clinical`, `biomedical`, `health`
- Life Sciences: `biology`, `chemistry`, `neuroscience`
- Social Sciences: `psychology`, `sociology`, `cognitive`, `behavioral`, `social`
- Other: `economics`, `business`, `law`, `education`, `humanities`, `history`, `philosophy`, `political`, `environmental`, `climate`

```yaml
- query: "neuroscience AND deep learning"  # Uses Semantic Scholar
- query: "clinical trial machine learning"  # Uses Semantic Scholar
```

### Priority 4: Preference Order

If no specific terms are detected, the system uses the configured preference order:

```yaml
settings:
  provider_selection:
    preference_order:
      - arxiv           # Default first choice
      - semantic_scholar
```

---

## Manual Provider Selection

You can override automatic selection by specifying the provider explicitly:

```yaml
research_topics:
  - query: "attention mechanisms in transformers"
    provider: arxiv
    auto_select_provider: false  # Disable automatic selection

  - query: "neural networks"
    provider: semantic_scholar
    auto_select_provider: false
```

---

## Benchmark Mode

To compare both providers for the same query, enable benchmark mode:

```yaml
research_topics:
  - query: "graph neural networks"
    benchmark: true  # Queries both providers
```

**Benchmark mode will:**
1. Query ALL available providers concurrently
2. Deduplicate results by DOI or paper ID
3. Log comparison metrics:
   - Query time per provider
   - Result count per provider
   - Overlap (papers found by both)
   - Unique papers per provider
4. Return the combined, deduplicated results

You can also enable benchmark mode globally:

```yaml
settings:
  provider_selection:
    benchmark_mode: true  # All queries use benchmark mode
```

---

## Fallback Strategy

When a provider fails (timeout, rate limit, error), the system automatically falls back to another provider.

### Configuration

```yaml
settings:
  provider_selection:
    fallback_enabled: true           # Enable fallback (default)
    fallback_timeout_seconds: 30     # Timeout before fallback
    preference_order:
      - arxiv
      - semantic_scholar
```

### Fallback Behavior

1. **Timeout**: If primary provider doesn't respond within `fallback_timeout_seconds`
2. **Error**: If primary provider returns an error
3. **Rate Limit**: If primary provider returns 429 status

The system tries the next provider in `preference_order`.

### Disabling Fallback

```yaml
settings:
  provider_selection:
    fallback_enabled: false  # Errors will propagate
```

---

## Configuration Reference

### ResearchTopic Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | enum | `arxiv` | Default provider for explicit selection |
| `min_citations` | int | null | Minimum citations (requires Semantic Scholar) |
| `benchmark` | bool | false | Enable provider comparison for this topic |
| `auto_select_provider` | bool | true | Allow automatic provider selection |

### ProviderSelectionConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_select` | bool | true | Enable automatic provider selection |
| `fallback_enabled` | bool | true | Enable automatic fallback |
| `benchmark_mode` | bool | false | Query all providers (global) |
| `preference_order` | list | [arxiv, semantic_scholar] | Provider priority |
| `fallback_timeout_seconds` | float | 30.0 | Timeout before fallback |

---

## Example Configurations

### AI/ML Research (ArXiv-focused)

```yaml
research_topics:
  - query: "transformer attention mechanisms"
    timeframe:
      type: recent
      value: "7d"
    # Will auto-select ArXiv due to ML terms
```

### Cross-Disciplinary Research

```yaml
research_topics:
  - query: "neuroscience AND machine learning"
    timeframe:
      type: since_year
      value: 2020
    # Will auto-select Semantic Scholar
```

### Citation-Filtered Research

```yaml
research_topics:
  - query: "reinforcement learning"
    min_citations: 50
    timeframe:
      type: since_year
      value: 2018
    # Will use Semantic Scholar for citation filtering
```

### Provider Comparison

```yaml
research_topics:
  - query: "graph neural networks"
    benchmark: true
    timeframe:
      type: recent
      value: "30d"
    # Queries both, returns combined results
```

### Explicit Provider Selection

```yaml
research_topics:
  - query: "medicine AI applications"
    provider: semantic_scholar
    auto_select_provider: false
    timeframe:
      type: recent
      value: "7d"
    # Forces Semantic Scholar regardless of terms
```

---

## Troubleshooting

### "semantic_scholar_disabled: no_api_key"

**Solution:** Add your Semantic Scholar API key to `.env`:

```bash
SEMANTIC_SCHOLAR_API_KEY=your_key_here
```

### "min_citations requires Semantic Scholar"

**Solution:** Ensure `SEMANTIC_SCHOLAR_API_KEY` is configured, or remove `min_citations` from your query.

### "Rate limit exceeded"

**Solution:**
1. Enable fallback: `fallback_enabled: true`
2. Add delays between queries
3. Use caching to reduce API calls

### Provider selection seems wrong

**Debug:** Check logs for selection reasoning:
```
provider_arxiv_terms_selection: Query contains ArXiv-specific terms
provider_cross_disciplinary_selection: Query spans multiple disciplines
provider_preference_selection: Using preference order
```

---

## Best Practices

1. **Let auto-selection work**: The system is optimized for common cases
2. **Use benchmark mode sparingly**: It doubles API calls
3. **Enable fallback in production**: Improves reliability
4. **Use citation filtering strategically**: Great for finding impactful papers
5. **Explicit selection for edge cases**: When you know better than the algorithm

---

## API Reference

### ProviderSelector Class

```python
from src.utils.provider_selector import ProviderSelector

selector = ProviderSelector(
    preference_order=[ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR]
)

# Get recommendation with reasoning
provider, reason = selector.get_recommendation(topic, available_providers)
print(f"Selected {provider}: {reason}")

# Get provider capability
pdf_rate = selector.get_capability(ProviderType.ARXIV, "pdf_access_rate")
```

### DiscoveryService Methods

```python
from src.services.discovery_service import DiscoveryService

service = DiscoveryService(api_key="your_key")

# Basic search (uses auto-selection)
papers = await service.search(topic)

# Search with metrics
papers, metrics = await service.search_with_metrics(topic)
print(f"Found {metrics.result_count} papers in {metrics.query_time_ms}ms")

# Compare providers
comparison = await service.compare_providers(topic)
print(f"Fastest: {comparison.fastest_provider}")
print(f"Most results: {comparison.most_results_provider}")
```
