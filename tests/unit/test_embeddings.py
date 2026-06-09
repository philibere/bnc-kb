from bnc_kb.embeddings import StubEmbedder, chunk_text, to_vector_literal


def test_stub_is_deterministic_and_normalized():
    e = StubEmbedder(dim=1024)
    a = e.embed(["hello world"])[0]
    b = e.embed(["hello world"])[0]
    assert a == b
    assert len(a) == 1024
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_stub_differs_by_text():
    e = StubEmbedder(dim=64)
    assert e.embed(["alpha"])[0] != e.embed(["beta"])[0]


def test_chunk_text_overlap():
    words = " ".join(str(i) for i in range(500))
    chunks = chunk_text(words, size=200, overlap=40)
    assert len(chunks) >= 3
    assert chunk_text("", size=200, overlap=40) == []


def test_vector_literal_format():
    assert to_vector_literal([1.0, 2.5]).startswith("[")
    assert to_vector_literal([1.0, 2.5]).endswith("]")
