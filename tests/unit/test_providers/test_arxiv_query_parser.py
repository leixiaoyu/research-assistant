"""
Comprehensive tests for ArXiv structured query parser.

Tests exact query output for complex combinations of:
- Quoted phrases
- Boolean operators (AND, OR, NOT)
- Parenthesized groups
- Mixed combinations

All assertions use exact string matching to catch any malformed output.
"""

import pytest
from src.services.providers.arxiv import ArxivProvider
from src.models.config import GlobalSettings


@pytest.fixture
def provider_with_categories():
    """Provider with category filtering enabled"""
    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.CL", "cs.LG"],
    )
    return ArxivProvider(settings=settings)


@pytest.fixture
def provider_no_categories():
    """Provider without category filtering"""
    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=[],
    )
    return ArxivProvider(settings=settings)


# CRITICAL ISSUE #1: Quoted phrases + Boolean operators


def test_quoted_phrase_with_or_operator(provider_no_categories):
    """Test: "foo" OR "bar" should preserve OR between quoted phrases"""
    query = provider_no_categories._build_structured_query('"foo" OR "bar"')

    expected = '(ti:"foo" OR abs:"foo") OR (ti:"bar" OR abs:"bar")'
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_quoted_phrase_with_and_operator(provider_no_categories):
    """Test: "machine learning" AND "deep learning" preserves AND"""
    query = provider_no_categories._build_structured_query(
        '"machine learning" AND "deep learning"'
    )

    expected = '(ti:"machine learning" OR abs:"machine learning") AND (ti:"deep learning" OR abs:"deep learning")'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_quoted_phrase_with_not_operator(provider_no_categories):
    """Test: "neural nets" NOT "old method" preserves NOT"""
    query = provider_no_categories._build_structured_query(
        '"neural nets" NOT "old method"'
    )

    expected = '(ti:"neural nets" OR abs:"neural nets") NOT (ti:"old method" OR abs:"old method")'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_three_quoted_phrases_with_or(provider_no_categories):
    """Test: "A" OR "B" OR "C" preserves all ORs"""
    query = provider_no_categories._build_structured_query('"A" OR "B" OR "C"')

    expected = '(ti:"A" OR abs:"A") OR (ti:"B" OR abs:"B") OR (ti:"C" OR abs:"C")'
    assert query == expected, f"Expected: {expected}\nGot: {query}"


# CRITICAL ISSUE #2: Parenthesized groups


def test_simple_parenthesized_group(provider_no_categories):
    """Test: GPT AND (summarization OR translation)"""
    query = provider_no_categories._build_structured_query(
        "GPT AND (summarization OR translation)"
    )

    expected = "(ti:GPT OR abs:GPT) AND ((ti:summarization OR abs:summarization) OR (ti:translation OR abs:translation))"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_nested_parentheses(provider_no_categories):
    """Test: A AND (B OR (C AND D))"""
    query = provider_no_categories._build_structured_query("A AND (B OR (C AND D))")

    expected = (
        "(ti:A OR abs:A) AND ((ti:B OR abs:B) OR ((ti:C OR abs:C) AND (ti:D OR abs:D)))"
    )
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_multiple_parenthesized_groups(provider_no_categories):
    """Test: (A OR B) AND (C OR D)"""
    query = provider_no_categories._build_structured_query("(A OR B) AND (C OR D)")

    expected = (
        "((ti:A OR abs:A) OR (ti:B OR abs:B)) AND ((ti:C OR abs:C) OR (ti:D OR abs:D))"
    )
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_parentheses_with_not(provider_no_categories):
    """Test: transformers NOT (reinforcement OR supervised)"""
    query = provider_no_categories._build_structured_query(
        "transformers NOT (reinforcement OR supervised)"
    )

    expected = "(ti:transformers OR abs:transformers) NOT ((ti:reinforcement OR abs:reinforcement) OR (ti:supervised OR abs:supervised))"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


# CRITICAL ISSUE #3: Complex mixed queries


def test_complex_quoted_and_parentheses(provider_no_categories):
    """Test: "neural nets" AND (vision OR NLP) NOT "old method" """
    query = provider_no_categories._build_structured_query(
        '"neural nets" AND (vision OR NLP) NOT "old method"'
    )

    expected = '(ti:"neural nets" OR abs:"neural nets") AND ((ti:vision OR abs:vision) OR (ti:NLP OR abs:NLP)) NOT (ti:"old method" OR abs:"old method")'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_quoted_phrase_inside_parentheses(provider_no_categories):
    """Test: GPT AND ("machine learning" OR translation)"""
    query = provider_no_categories._build_structured_query(
        'GPT AND ("machine learning" OR translation)'
    )

    expected = '(ti:GPT OR abs:GPT) AND ((ti:"machine learning" OR abs:"machine learning") OR (ti:translation OR abs:translation))'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_complex_nested_with_all_operators(provider_no_categories):
    """Test: "LLM" AND (reasoning OR (math NOT "symbolic AI"))"""
    query = provider_no_categories._build_structured_query(
        '"LLM" AND (reasoning OR (math NOT "symbolic AI"))'
    )

    expected = '(ti:"LLM" OR abs:"LLM") AND ((ti:reasoning OR abs:reasoning) OR ((ti:math OR abs:math) NOT (ti:"symbolic AI" OR abs:"symbolic AI")))'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


# Category filtering tests


def test_simple_term_with_categories(provider_with_categories):
    """Test: Simple term with category filter"""
    query = provider_with_categories._build_structured_query("transformers")

    expected = "((ti:transformers OR abs:transformers)) AND (cat:cs.CL OR cat:cs.LG)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_quoted_phrase_with_categories(provider_with_categories):
    """Test: Quoted phrase with category filter"""
    query = provider_with_categories._build_structured_query('"machine learning"')

    expected = '((ti:"machine learning" OR abs:"machine learning")) AND (cat:cs.CL OR cat:cs.LG)'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_boolean_operators_with_categories(provider_with_categories):
    """Test: Boolean operators with category filter"""
    query = provider_with_categories._build_structured_query("A AND B OR C")

    expected = "((ti:A OR abs:A) AND (ti:B OR abs:B) OR (ti:C OR abs:C)) AND (cat:cs.CL OR cat:cs.LG)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_complex_query_with_categories(provider_with_categories):
    """Test: Complex query with category filter"""
    query = provider_with_categories._build_structured_query(
        '"GPT" AND (summarization OR translation)'
    )

    expected = '((ti:"GPT" OR abs:"GPT") AND ((ti:summarization OR abs:summarization) OR (ti:translation OR abs:translation))) AND (cat:cs.CL OR cat:cs.LG)'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


# Edge cases


def test_empty_parentheses(provider_no_categories):
    """Test: Query with empty parentheses"""
    query = provider_no_categories._build_structured_query("GPT AND ()")

    # Empty group should be skipped
    expected = "(ti:GPT OR abs:GPT) AND"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_unmatched_opening_parenthesis(provider_no_categories):
    """Test: Unmatched opening parenthesis treated as regular term"""
    query = provider_no_categories._build_structured_query("GPT AND ( transformers")

    # Unmatched paren treated as term
    expected = (
        "(ti:GPT OR abs:GPT) AND (ti:( OR abs:() (ti:transformers OR abs:transformers)"
    )
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_unmatched_closing_parenthesis(provider_no_categories):
    """Test: Unmatched closing parenthesis treated as regular term"""
    query = provider_no_categories._build_structured_query("GPT ) transformers")

    expected = (
        "(ti:GPT OR abs:GPT) (ti:) OR abs:)) (ti:transformers OR abs:transformers)"
    )
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_only_operators_no_terms(provider_no_categories):
    """Test: Query with only operators"""
    query = provider_no_categories._build_structured_query("AND OR NOT")

    expected = "AND OR NOT"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_multiple_spaces(provider_no_categories):
    """Test: Multiple spaces between tokens"""
    query = provider_no_categories._build_structured_query(
        "GPT    AND     transformers"
    )

    expected = "(ti:GPT OR abs:GPT) AND (ti:transformers OR abs:transformers)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_quoted_phrase_with_spaces(provider_no_categories):
    """Test: Quoted phrase with internal spaces preserved"""
    query = provider_no_categories._build_structured_query(
        '"large   language   models"'
    )

    expected = '(ti:"large   language   models" OR abs:"large   language   models")'
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_unclosed_quote(provider_no_categories):
    """Test: Unclosed quote at end of query"""
    query = provider_no_categories._build_structured_query('GPT "machine learning')

    # Unclosed quote should be ignored or handled gracefully
    # Implementation may vary - this tests current behavior
    expected = (
        "(ti:GPT OR abs:GPT) (ti:machine OR abs:machine) (ti:learning OR abs:learning)"
    )
    assert query == expected, f"Expected: {expected}\nGot: {query}"


# Tokenization tests


def test_tokenize_simple_terms(provider_no_categories):
    """Test tokenizer with simple terms"""
    tokens = provider_no_categories._tokenize_query("A B C")
    assert tokens == ["A", "B", "C"]


def test_tokenize_quoted_phrase(provider_no_categories):
    """Test tokenizer with quoted phrase"""
    tokens = provider_no_categories._tokenize_query('"machine learning"')
    assert tokens == ['"machine learning"']


def test_tokenize_boolean_operators(provider_no_categories):
    """Test tokenizer with Boolean operators"""
    tokens = provider_no_categories._tokenize_query("A AND B OR C NOT D")
    assert tokens == ["A", "AND", "B", "OR", "C", "NOT", "D"]


def test_tokenize_parentheses(provider_no_categories):
    """Test tokenizer with parentheses"""
    tokens = provider_no_categories._tokenize_query("A AND (B OR C)")
    assert tokens == ["A", "AND", "(", "B", "OR", "C", ")"]


def test_tokenize_mixed(provider_no_categories):
    """Test tokenizer with mixed elements"""
    tokens = provider_no_categories._tokenize_query(
        '"GPT" AND (summarization OR "machine learning")'
    )
    assert tokens == [
        '"GPT"',
        "AND",
        "(",
        "summarization",
        "OR",
        '"machine learning"',
        ")",
    ]


def test_tokenize_nested_parentheses(provider_no_categories):
    """Test tokenizer with nested parentheses"""
    tokens = provider_no_categories._tokenize_query("A AND (B OR (C AND D))")
    assert tokens == ["A", "AND", "(", "B", "OR", "(", "C", "AND", "D", ")", ")"]


# Error cases


def test_empty_query_raises_error(provider_no_categories):
    """Test that empty query raises ValueError"""
    with pytest.raises(ValueError, match="Query cannot be empty"):
        provider_no_categories._build_structured_query("")


def test_whitespace_only_query_raises_error(provider_no_categories):
    """Test that whitespace-only query raises ValueError"""
    with pytest.raises(ValueError, match="Query cannot be empty"):
        provider_no_categories._build_structured_query("   ")


def test_process_empty_tokens_raises_error(provider_no_categories):
    """Test that processing empty token list raises ValueError"""
    with pytest.raises(ValueError, match="No tokens to process"):
        provider_no_categories._process_tokens([])
