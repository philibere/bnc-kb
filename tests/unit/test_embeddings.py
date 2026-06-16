from bnc_kb.embeddings import embed_query, to_vector_literal


def test_embed_query_is_deterministic_and_1024d():
    a = embed_query("hello world")
    b = embed_query("hello world")
    assert a == b  # fake embedder: same text -> same vector
    assert len(a) == 1024


def test_embed_query_differs_by_text():
    assert embed_query("alpha") != embed_query("beta")


def test_vector_literal_format():
    lit = to_vector_literal([1.0, 2.5])
    assert lit.startswith("[")
    assert lit.endswith("]")
    assert "1.00000000" in lit
