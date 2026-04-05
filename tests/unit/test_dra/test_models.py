"""Unit tests for Phase 8 DRA data models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.models.dra import (
    AgentLimits,
    ChunkType,
    ContextualTip,
    CorpusChunk,
    CorpusConfig,
    DRASettings,
    FindResult,
    ResearchResult,
    SearchConfig,
    SearchResult,
    ToolCall,
    ToolCallType,
    TrajectoryInsights,
    TrajectoryRecord,
    Turn,
)


class TestChunkType:
    """Tests for ChunkType enum."""

    def test_all_section_types_defined(self):
        """Verify all expected section types exist."""
        expected = [
            "abstract",
            "introduction",
            "methods",
            "results",
            "discussion",
            "conclusion",
            "references",
            "other",
        ]
        actual = [ct.value for ct in ChunkType]
        assert sorted(actual) == sorted(expected)

    def test_chunk_type_string_values(self):
        """Verify ChunkType is a string enum."""
        assert ChunkType.ABSTRACT == "abstract"
        assert ChunkType.METHODS == "methods"
        assert isinstance(ChunkType.ABSTRACT, str)


class TestCorpusChunk:
    """Tests for CorpusChunk model."""

    def test_valid_chunk_creation(self):
        """Test creating a valid corpus chunk."""
        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            section_type=ChunkType.ABSTRACT,
            title="Test Paper",
            content="This is the abstract content.",
            token_count=10,
        )
        assert chunk.chunk_id == "paper1:0"
        assert chunk.paper_id == "paper1"
        assert chunk.section_type == ChunkType.ABSTRACT
        assert chunk.title == "Test Paper"
        assert chunk.content == "This is the abstract content."
        assert chunk.token_count == 10
        assert chunk.embedding is None
        assert chunk.metadata == {}
        assert chunk.checksum is None

    def test_chunk_with_embedding(self):
        """Test chunk with embedding vector."""
        embedding = [0.1, 0.2, 0.3]
        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            title="Test",
            content="Content",
            token_count=5,
            embedding=embedding,
        )
        assert chunk.embedding == embedding

    def test_chunk_with_metadata(self):
        """Test chunk with metadata."""
        metadata = {"doi": "10.1234/test", "arxiv_id": "2301.00001"}
        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            title="Test",
            content="Content",
            token_count=5,
            metadata=metadata,
        )
        assert chunk.metadata == metadata

    def test_chunk_with_checksum(self):
        """Test chunk with checksum."""
        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            title="Test",
            content="Content",
            token_count=5,
            checksum="abc123",
        )
        assert chunk.checksum == "abc123"

    def test_chunk_empty_content_rejected(self):
        """Test that empty content is rejected."""
        with pytest.raises(ValidationError):
            CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="Test",
                content="",
                token_count=0,
            )

    def test_chunk_negative_token_count_rejected(self):
        """Test that negative token count is rejected."""
        with pytest.raises(ValidationError):
            CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="Test",
                content="Content",
                token_count=-1,
            )

    def test_chunk_title_max_length(self):
        """Test title max length validation."""
        with pytest.raises(ValidationError):
            CorpusChunk(
                chunk_id="paper1:0",
                paper_id="paper1",
                title="x" * 501,  # Exceeds max 500
                content="Content",
                token_count=5,
            )

    def test_chunk_default_section_type(self):
        """Test default section type is OTHER."""
        chunk = CorpusChunk(
            chunk_id="paper1:0",
            paper_id="paper1",
            title="Test",
            content="Content",
            token_count=5,
        )
        assert chunk.section_type == ChunkType.OTHER


class TestSearchResult:
    """Tests for SearchResult model."""

    def test_valid_search_result(self):
        """Test creating a valid search result."""
        result = SearchResult(
            chunk_id="paper1:0",
            paper_id="paper1",
            paper_title="Test Paper",
            section_type=ChunkType.METHODS,
            snippet="This is a snippet...",
            relevance_score=0.85,
        )
        assert result.chunk_id == "paper1:0"
        assert result.relevance_score == 0.85

    def test_relevance_score_rounded(self):
        """Test relevance score is rounded to 4 decimals."""
        result = SearchResult(
            chunk_id="paper1:0",
            paper_id="paper1",
            paper_title="Test",
            section_type=ChunkType.OTHER,
            snippet="Snippet",
            relevance_score=0.123456789,
        )
        assert result.relevance_score == 0.1235

    def test_relevance_score_bounds(self):
        """Test relevance score must be between 0 and 1."""
        with pytest.raises(ValidationError):
            SearchResult(
                chunk_id="paper1:0",
                paper_id="paper1",
                paper_title="Test",
                section_type=ChunkType.OTHER,
                snippet="Snippet",
                relevance_score=1.5,
            )

        with pytest.raises(ValidationError):
            SearchResult(
                chunk_id="paper1:0",
                paper_id="paper1",
                paper_title="Test",
                section_type=ChunkType.OTHER,
                snippet="Snippet",
                relevance_score=-0.1,
            )

    def test_snippet_max_length(self):
        """Test snippet max length validation."""
        with pytest.raises(ValidationError):
            SearchResult(
                chunk_id="paper1:0",
                paper_id="paper1",
                paper_title="Test",
                section_type=ChunkType.OTHER,
                snippet="x" * 1001,  # Exceeds max 1000
                relevance_score=0.5,
            )


class TestFindResult:
    """Tests for FindResult model."""

    def test_valid_find_result(self):
        """Test creating a valid find result."""
        result = FindResult(
            matched_text="neural network",
            context="We propose a novel neural network architecture...",
            position=150,
            section=ChunkType.METHODS,
        )
        assert result.matched_text == "neural network"
        assert result.position == 150
        assert result.section == ChunkType.METHODS

    def test_find_result_no_section(self):
        """Test find result without section."""
        result = FindResult(
            matched_text="test",
            context="This is a test context.",
            position=0,
        )
        assert result.section is None

    def test_find_result_negative_position_rejected(self):
        """Test negative position is rejected."""
        with pytest.raises(ValidationError):
            FindResult(
                matched_text="test",
                context="Context",
                position=-1,
            )


class TestToolCall:
    """Tests for ToolCall model."""

    def test_valid_tool_call(self):
        """Test creating a valid tool call."""
        call = ToolCall(
            tool=ToolCallType.SEARCH,
            arguments={"query": "machine learning"},
        )
        assert call.tool == ToolCallType.SEARCH
        assert call.arguments == {"query": "machine learning"}
        assert isinstance(call.timestamp, datetime)

    def test_all_tool_types(self):
        """Test all tool types can be created."""
        for tool_type in ToolCallType:
            call = ToolCall(tool=tool_type, arguments={})
            assert call.tool == tool_type


class TestTurn:
    """Tests for Turn model."""

    def test_valid_turn(self):
        """Test creating a valid turn."""
        turn = Turn(
            turn_number=1,
            reasoning="I need to search for relevant papers.",
            action=ToolCall(
                tool=ToolCallType.SEARCH,
                arguments={"query": "transformer architecture"},
            ),
            observation="Found 5 relevant papers...",
            observation_tokens=100,
        )
        assert turn.turn_number == 1
        assert turn.action.tool == ToolCallType.SEARCH
        assert turn.observation_tokens == 100

    def test_turn_number_minimum(self):
        """Test turn number must be >= 1."""
        with pytest.raises(ValidationError):
            Turn(
                turn_number=0,
                reasoning="Test",
                action=ToolCall(tool=ToolCallType.SEARCH, arguments={}),
                observation="Test",
                observation_tokens=0,
            )


class TestResearchResult:
    """Tests for ResearchResult model."""

    def test_valid_research_result(self):
        """Test creating a valid research result."""
        result = ResearchResult(
            question="What are the latest advances in NLP?",
            answer="Recent advances include...",
            total_turns=5,
        )
        assert result.question == "What are the latest advances in NLP?"
        assert result.answer == "Recent advances include..."
        assert result.total_turns == 5
        assert result.trajectory == []
        assert result.papers_consulted == []
        assert result.exhausted is False

    def test_research_result_no_answer(self):
        """Test research result without answer."""
        result = ResearchResult(
            question="Test question",
            total_turns=10,
            exhausted=True,
        )
        assert result.answer is None
        assert result.exhausted is True

    def test_research_result_with_trajectory(self):
        """Test research result with trajectory."""
        turns = [
            Turn(
                turn_number=1,
                reasoning="Search first",
                action=ToolCall(tool=ToolCallType.SEARCH, arguments={}),
                observation="Results",
                observation_tokens=50,
            ),
        ]
        result = ResearchResult(
            question="Test",
            trajectory=turns,
            total_turns=1,
        )
        assert len(result.trajectory) == 1


class TestTrajectoryInsights:
    """Tests for TrajectoryInsights model."""

    def test_default_values(self):
        """Test default values."""
        insights = TrajectoryInsights()
        assert insights.effective_query_patterns == []
        assert insights.successful_sequences == []
        assert insights.failure_modes == {}
        assert insights.average_turns_to_success == 0.0
        assert insights.paper_consultation_patterns == {}

    def test_with_data(self):
        """Test with populated data."""
        insights = TrajectoryInsights(
            effective_query_patterns=["specific keywords", "author names"],
            failure_modes={"no_results": 3, "timeout": 1},
            average_turns_to_success=15.5,
        )
        assert len(insights.effective_query_patterns) == 2
        assert insights.failure_modes["no_results"] == 3


class TestContextualTip:
    """Tests for ContextualTip model."""

    def test_valid_tip(self):
        """Test creating a valid contextual tip."""
        tip = ContextualTip(
            context="When searching for recent papers",
            strategy="Use date filters and sort by relevance",
            confidence=0.85,
            examples=["traj_001", "traj_005"],
        )
        assert tip.confidence == 0.85
        assert len(tip.examples) == 2

    def test_confidence_rounded(self):
        """Test confidence is rounded to 4 decimals."""
        tip = ContextualTip(
            context="Test",
            strategy="Test strategy",
            confidence=0.123456789,
        )
        assert tip.confidence == 0.1235

    def test_confidence_bounds(self):
        """Test confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            ContextualTip(
                context="Test",
                strategy="Test",
                confidence=1.5,
            )


class TestTrajectoryRecord:
    """Tests for TrajectoryRecord model."""

    def test_valid_record(self):
        """Test creating a valid trajectory record."""
        record = TrajectoryRecord(
            trajectory_id="traj_001",
            question="What is attention?",
            quality_score=0.9,
        )
        assert record.trajectory_id == "traj_001"
        assert record.quality_score == 0.9
        assert record.turns == []
        assert isinstance(record.created_at, datetime)

    def test_quality_score_rounded(self):
        """Test quality score is rounded."""
        record = TrajectoryRecord(
            trajectory_id="traj_001",
            question="Test",
            quality_score=0.123456789,
        )
        assert record.quality_score == 0.1235

    def test_quality_score_bounds(self):
        """Test quality score bounds."""
        with pytest.raises(ValidationError):
            TrajectoryRecord(
                trajectory_id="traj_001",
                question="Test",
                quality_score=1.5,
            )


class TestAgentLimits:
    """Tests for AgentLimits model."""

    def test_default_values(self):
        """Test default limit values."""
        limits = AgentLimits()
        assert limits.max_turns == 50
        assert limits.max_context_tokens == 128_000
        assert limits.max_session_duration_seconds == 600
        assert limits.max_open_documents == 20

    def test_custom_values(self):
        """Test custom limit values."""
        limits = AgentLimits(
            max_turns=100,
            max_context_tokens=200_000,
            max_session_duration_seconds=1200,
            max_open_documents=50,
        )
        assert limits.max_turns == 100
        assert limits.max_context_tokens == 200_000

    def test_limit_bounds(self):
        """Test limit bounds validation."""
        with pytest.raises(ValidationError):
            AgentLimits(max_turns=0)

        with pytest.raises(ValidationError):
            AgentLimits(max_turns=201)

        with pytest.raises(ValidationError):
            AgentLimits(max_context_tokens=500)


class TestCorpusConfig:
    """Tests for CorpusConfig model."""

    def test_default_values(self):
        """Test default config values."""
        config = CorpusConfig()
        assert config.embedding_model == "allenai/specter2"
        assert config.embedding_model_path is None
        assert config.chunk_max_tokens == 512
        assert config.chunk_overlap_tokens == 64
        assert config.embedding_batch_size == 32
        assert config.corpus_dir == "./data/dra/corpus"

    def test_custom_values(self):
        """Test custom config values."""
        config = CorpusConfig(
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_model_path="/models/local",
            chunk_max_tokens=1024,
            corpus_dir="/custom/corpus",
        )
        assert config.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
        assert config.embedding_model_path == "/models/local"
        assert config.chunk_max_tokens == 1024

    def test_chunk_token_bounds(self):
        """Test chunk token bounds."""
        with pytest.raises(ValidationError):
            CorpusConfig(chunk_max_tokens=32)  # Below min 64

        with pytest.raises(ValidationError):
            CorpusConfig(chunk_max_tokens=4096)  # Above max 2048


class TestSearchConfig:
    """Tests for SearchConfig model."""

    def test_default_values(self):
        """Test default search config values."""
        config = SearchConfig()
        assert config.dense_weight == 0.7
        assert config.sparse_weight == 0.3
        assert config.default_top_k == 10
        assert config.max_top_k == 50

    def test_weights_must_sum_to_one(self):
        """Test that weights must sum to 1.0."""
        # Valid: sum is 1.0
        config = SearchConfig(dense_weight=0.6, sparse_weight=0.4)
        assert config.dense_weight + config.sparse_weight == 1.0

        # Invalid: sum is not 1.0
        with pytest.raises(ValidationError):
            SearchConfig(dense_weight=0.5, sparse_weight=0.3)

    def test_top_k_bounds(self):
        """Test top_k bounds."""
        with pytest.raises(ValidationError):
            SearchConfig(default_top_k=0)

        with pytest.raises(ValidationError):
            SearchConfig(max_top_k=501)


class TestDRASettings:
    """Tests for DRASettings model."""

    def test_default_nested_configs(self):
        """Test default nested configurations."""
        settings = DRASettings()
        assert isinstance(settings.corpus, CorpusConfig)
        assert isinstance(settings.search, SearchConfig)
        assert isinstance(settings.agent, AgentLimits)

    def test_custom_nested_configs(self):
        """Test custom nested configurations."""
        settings = DRASettings(
            corpus=CorpusConfig(chunk_max_tokens=1024),
            agent=AgentLimits(max_turns=100),
        )
        assert settings.corpus.chunk_max_tokens == 1024
        assert settings.agent.max_turns == 100
        # Search should use defaults
        assert settings.search.dense_weight == 0.7
