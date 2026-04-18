"""Conftest for DRA tests - mocks optional ML dependencies.

The DRA search engine uses optional dependencies (transformers, faiss, rank_bm25)
that may not be installed in CI environments. This conftest creates mock modules
in sys.modules before tests import the search_engine module.
"""

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest


def _create_mock_transformers():
    """Create mock transformers module."""
    mock_transformers = MagicMock()

    # Mock AutoModel
    mock_model_instance = MagicMock()
    mock_model_instance.config.hidden_size = 768
    mock_model_instance.eval.return_value = None
    mock_transformers.AutoModel.from_pretrained.return_value = mock_model_instance

    # Mock AutoTokenizer
    mock_tokenizer_instance = MagicMock()
    mock_tokenizer_instance.return_value = {
        "input_ids": MagicMock(),
        "attention_mask": MagicMock(),
    }
    mock_transformers.AutoTokenizer.from_pretrained.return_value = (
        mock_tokenizer_instance
    )

    return mock_transformers


def _create_mock_faiss():
    """Create mock faiss module."""
    mock_faiss = MagicMock()

    # Mock IndexFlatIP
    mock_index = MagicMock()
    mock_index.add = MagicMock()
    mock_index.search = MagicMock(
        return_value=(np.array([[0.9, 0.8]]), np.array([[0, 1]]))
    )
    mock_faiss.IndexFlatIP.return_value = mock_index

    # Mock normalize_L2 - modifies array in place
    mock_faiss.normalize_L2 = MagicMock()

    # Mock read_index and write_index
    mock_faiss.read_index = MagicMock(return_value=mock_index)
    mock_faiss.write_index = MagicMock()

    return mock_faiss


def _create_mock_rank_bm25():
    """Create mock rank_bm25 module."""
    mock_rank_bm25 = MagicMock()

    # Mock BM25Okapi
    mock_bm25_instance = MagicMock()
    mock_bm25_instance.get_scores = MagicMock(return_value=np.array([0.5, 0.8, 0.3]))
    mock_rank_bm25.BM25Okapi.return_value = mock_bm25_instance

    return mock_rank_bm25


def _create_mock_torch():
    """Create mock torch module."""
    mock_torch = MagicMock()

    # Mock no_grad context manager
    mock_torch.no_grad.return_value.__enter__ = MagicMock()
    mock_torch.no_grad.return_value.__exit__ = MagicMock()

    # Mock tensor outputs
    mock_output = MagicMock()
    mock_output.last_hidden_state = MagicMock()
    mock_output.last_hidden_state.__getitem__ = MagicMock(
        return_value=MagicMock(numpy=MagicMock(return_value=np.random.rand(1, 768)))
    )

    return mock_torch


def _is_module_importable(module_name: str) -> bool:
    """Check if a module can be imported without side effects."""
    try:
        import importlib.util

        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except (ImportError, ModuleNotFoundError):
        return False


# Check which modules need mocking (only mock if not actually available)
_NEED_MOCK_TRANSFORMERS = not _is_module_importable("transformers")
_NEED_MOCK_FAISS = not _is_module_importable("faiss")
_NEED_MOCK_RANK_BM25 = not _is_module_importable("rank_bm25")
_NEED_MOCK_TORCH = not _is_module_importable("torch")


@pytest.fixture(autouse=True)
def mock_ml_dependencies(monkeypatch):
    """Auto-use fixture to mock ML dependencies for DRA tests.

    Only mocks modules that are not actually installed.
    """
    if _NEED_MOCK_TRANSFORMERS:
        monkeypatch.setitem(sys.modules, "transformers", _create_mock_transformers())

    if _NEED_MOCK_FAISS:
        monkeypatch.setitem(sys.modules, "faiss", _create_mock_faiss())

    if _NEED_MOCK_RANK_BM25:
        monkeypatch.setitem(sys.modules, "rank_bm25", _create_mock_rank_bm25())

    if _NEED_MOCK_TORCH:
        monkeypatch.setitem(sys.modules, "torch", _create_mock_torch())

    yield
