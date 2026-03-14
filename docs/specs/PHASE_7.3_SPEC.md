# Requirements Document: Phase 7.3 - Human Feedback Loop

## Introduction

Phase 7.3 implements human-in-the-loop feedback to guide paper discovery. This milestone enables:

1. **Feedback collection** - Researchers can rate papers and provide structured reasons
2. **Preference learning** - System learns from feedback to personalize recommendations
3. **Semantic similarity search** - "Find more like this" using paper embeddings
4. **Exploration-exploitation balance** - Thompson Sampling prevents filter bubbles

This phase transforms the pipeline from passive discovery to active research assistance that adapts to user preferences.

## Alignment with Product Vision

This feature represents the evolution from automated discovery to intelligent research partnership:

- **Personalization**: Recommendations improve based on researcher feedback
- **Efficiency**: Higher-quality papers surface first, reducing review time
- **Research direction**: Feedback shapes future discovery queries
- **Knowledge capture**: Explicit reasons ("I like this because...") become searchable

## Dependencies

- **Phase 7.1 (Required)**: Foundation infrastructure
- **Phase 7.2 (Required)**: Multi-source discovery and citation networks
- **Phase 3.5 (Complete)**: RegistryService for paper identity
- **External**: SPECTER2 model (allenai/specter2) for embeddings

## Requirements

### Requirement 1: Paper Feedback Collection

**User Story:** As a researcher, I want to rate papers and explain why I find them valuable, so that the system can learn my preferences and find more relevant papers.

#### Acceptance Criteria

1. WHEN a paper is displayed THEN the system SHALL provide feedback options: thumbs_up, thumbs_down, neutral
2. WHEN user provides feedback THEN the system SHALL allow optional structured reasons (methodology, findings, applications, writing_quality)
3. WHEN user clicks "Find more like this" THEN the system SHALL accept free-text explanation of what they liked
4. WHEN feedback is submitted THEN the system SHALL store: paper_id, rating, reasons, timestamp, user_id (optional)
5. IF feedback storage fails THEN the system SHALL retry and log error (non-blocking)
6. WHEN viewing paper history THEN the system SHALL display previous feedback for that paper

### Requirement 2: Feedback Storage and Retrieval

**User Story:** As a system operator, I want feedback stored persistently and queryable, so that preference learning can use historical data.

#### Acceptance Criteria

1. WHEN feedback is stored THEN the system SHALL persist to `data/feedback.json` with atomic writes
2. WHEN storing feedback THEN the system SHALL include: paper_id, topic_slug, rating, reasons, free_text, timestamp
3. WHEN querying feedback THEN the system SHALL support filters: by_topic, by_rating, by_date_range
4. IF feedback file is corrupted THEN the system SHALL create backup and start fresh
5. WHEN exporting feedback THEN the system SHALL support CSV and JSON formats
6. WHEN feedback count exceeds 10,000 entries THEN the system SHALL archive older entries to separate file

### Requirement 3: SPECTER2 Paper Embeddings

**User Story:** As a researcher, I want the system to understand paper similarity semantically, so that "find more like this" returns genuinely related papers.

#### Acceptance Criteria

1. WHEN a paper is registered THEN the system SHALL compute SPECTER2 embedding from title + abstract
2. WHEN computing embeddings THEN the system SHALL use `allenai/specter2` model via sentence-transformers
3. WHEN embeddings are computed THEN the system SHALL cache them in vector database (FAISS or Chroma)
4. IF embedding computation fails THEN the system SHALL log error and skip (paper still discoverable)
5. WHEN searching by similarity THEN the system SHALL return top-k papers by cosine similarity
6. WHEN embedding model is unavailable THEN the system SHALL fall back to TF-IDF similarity

### Requirement 4: "Find More Like This" Functionality

**User Story:** As a researcher, I want to click "find more like this" on a paper and get semantically similar papers, so that I can explore related research efficiently.

#### Acceptance Criteria

1. WHEN user clicks "find more like this" on a paper THEN the system SHALL search for similar papers using embeddings
2. WHEN searching for similar papers THEN the system SHALL search across: registry (historical), current topic, all providers
3. IF user provides reasons ("I like this because X") THEN the system SHALL weight similarity by those aspects
4. WHEN similar papers are found THEN the system SHALL return top-20 ranked by similarity score
5. IF similar search returns papers already in registry THEN the system SHALL mark them as "previously discovered"
6. WHEN similar papers are displayed THEN the system SHALL show similarity score and matching aspects

### Requirement 5: Preference Learning with Contextual Bandits

**User Story:** As a researcher, I want the system to learn from my feedback over time, so that paper rankings automatically improve without explicit configuration.

#### Acceptance Criteria

1. WHEN sufficient feedback exists (at least 20 ratings per topic) THEN the system SHALL train preference model
2. WHEN training preference model THEN the system SHALL use contextual bandits (Vowpal Wabbit or similar)
3. WHEN ranking papers THEN the system SHALL blend: base_score (citations, recency) + preference_score
4. IF no feedback exists for a topic THEN the system SHALL use exploration mode (diverse recommendations)
5. WHEN exploration-exploitation is active THEN the system SHALL use Thompson Sampling
6. WHEN preference model is updated THEN the system SHALL log: feedback_count, model_accuracy, feature_weights

### Requirement 6: Query Refinement from Feedback

**User Story:** As a researcher, I want the system to refine my search queries based on feedback, so that future discoveries better match my interests.

#### Acceptance Criteria

1. WHEN positive feedback accumulates (at least 5 thumbs_up for a topic) THEN the system SHALL analyze common themes
2. WHEN analyzing feedback themes THEN the system SHALL extract keywords from liked paper titles/abstracts
3. IF common themes are detected THEN the system SHALL suggest query refinements to user
4. WHEN user approves refinement THEN the system SHALL update topic query in research_config.yaml
5. IF user rejects refinement THEN the system SHALL log rejection and not suggest again for 30 days
6. WHEN query is refined THEN the system SHALL reset topic discovery timestamp (trigger fresh search)

### Requirement 7: Feedback UI (CLI and Web)

**User Story:** As a researcher, I want a simple interface to provide feedback on papers, so that I can quickly rate papers without disrupting my workflow.

#### Acceptance Criteria

1. WHEN using CLI THEN the system SHALL provide `python -m src.cli feedback` command for interactive rating
2. WHEN using CLI feedback THEN the system SHALL display paper title, abstract preview, and rating options
3. IF web UI is enabled THEN the system SHALL provide Gradio interface for feedback collection
4. WHEN displaying papers for feedback THEN the system SHALL show: title, authors, venue, abstract, PDF link
5. IF batch feedback mode is enabled THEN the system SHALL allow rating multiple papers in sequence
6. WHEN feedback session ends THEN the system SHALL summarize: papers_rated, thumbs_up, thumbs_down, skipped

### Requirement 8: Feedback Analytics and Insights

**User Story:** As a researcher, I want to see analytics about my feedback patterns, so that I can understand my research interests better.

#### Acceptance Criteria

1. WHEN user requests analytics THEN the system SHALL generate feedback summary report
2. WHEN generating summary THEN the system SHALL include: total_ratings, rating_distribution, top_liked_topics, common_reasons
3. WHEN analyzing preferences THEN the system SHALL cluster liked papers and label clusters
4. IF trends are detected THEN the system SHALL highlight emerging interests vs. established interests
5. WHEN exporting analytics THEN the system SHALL generate markdown report compatible with Obsidian
6. WHEN visualizing preferences THEN the system SHALL generate embedding space plot (UMAP) of liked vs. disliked papers

## Non-Functional Requirements

### Code Architecture and Modularity

- **Single Responsibility Principle**: `FeedbackService` handles storage, `PreferenceModel` handles learning
- **Modular Design**: Embedding computation in `EmbeddingService`, separate from feedback
- **Dependency Management**: SPECTER2 is optional dependency (graceful degradation without it)
- **Clear Interfaces**: `FeedbackCollector` protocol for CLI/Web/API implementations
- **Backward Compatibility**: Feedback features are opt-in, pipeline works without them

### Performance

- FAISS index should support incremental updates (no full rebuild)
- Preference model should handle sparse feedback gracefully
- Note: Latency is not a priority metric - quality of recommendations and depth of research discovery are prioritized

### Security

- User feedback stored locally (no cloud sync without explicit opt-in)
- No PII collected in feedback (paper_id only, no user tracking by default)
- Feedback export requires explicit user action
- Embedding model runs locally (no API calls for embeddings)

### Reliability

- Feedback loss should be prevented with write-ahead logging
- Embedding cache should survive process restarts
- Preference model should gracefully handle sparse feedback
- System should work offline after initial model download

### Usability

- Feedback should require minimal effort (one-click rating)
- "Find more like this" should be discoverable in all interfaces
- Analytics should be understandable by non-technical users
- Gradio UI should be mobile-friendly for on-the-go review

## Configuration Schema

```yaml
# research_config.yaml additions
settings:
  human_feedback:
    enabled: true
    storage_path: data/feedback.json
    archive_threshold: 10000

  embeddings:
    enabled: true
    model: allenai/specter2
    cache_dir: .cache/embeddings
    vector_db: faiss  # or chroma
    fallback: tfidf

  preference_learning:
    enabled: true
    algorithm: contextual_bandit  # or simple_average
    min_feedback_for_training: 20
    exploration_rate: 0.1  # Thompson Sampling epsilon
    update_frequency: daily

  feedback_ui:
    cli_enabled: true
    gradio_enabled: false
    gradio_port: 7860
```

## Integration with Existing Skills and Tools

Based on Phase 7 research findings, this milestone should integrate with:

| Tool | Integration Point | Purpose |
|------|-------------------|---------|
| **Deep Research Skills** | Feedback collection | Human-in-the-loop checkpoints |
| **PaperQA2** | Similar paper search | Enhanced semantic matching |
| **Obsidian** | Analytics export | Knowledge management integration |
| **Zotero MCP** | Paper metadata | Enrich feedback context |

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Feedback collection rate | At least 30% of viewed papers rated | `papers_rated / papers_displayed` |
| Preference model accuracy | At least 70% prediction of thumbs_up | Cross-validation on held-out feedback |
| "Find more like this" relevance | At least 80% of results rated positively | Follow-up ratings on similar papers |
| Query refinement adoption | At least 50% of suggestions accepted | `accepted_refinements / suggested` |
| Deep research improvement | 3x more relevant papers discovered after feedback | Compare pre/post feedback discovery quality |
| Research direction accuracy | At least 70% of feedback-guided discoveries rated positively | User ratings on feedback-influenced results |

## Out of Scope (Future Phases)

- Multi-user feedback aggregation (collaborative filtering)
- Real-time paper streaming with live feedback
- Integration with external annotation tools (Hypothesis, Zotero notes)
- Voice-based feedback collection
- Automatic paper summarization based on feedback themes
