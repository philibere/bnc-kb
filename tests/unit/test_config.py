from bnc_kb.config import load_settings


def test_defaults_present():
    s = load_settings()
    assert s.embedding_dim == 1024
    assert s.api_key_admin
    assert s.database_url.startswith("postgresql://")
