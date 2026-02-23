from sophia.llm.groq_provider import _normalize_groq_base_url


def test_normalize_groq_base_url_strips_openai_suffix() -> None:
    assert _normalize_groq_base_url("https://api.groq.com/openai/v1") == "https://api.groq.com"
    assert _normalize_groq_base_url("https://api.groq.com/openai/v1/") == "https://api.groq.com"


def test_normalize_groq_base_url_keeps_root() -> None:
    assert _normalize_groq_base_url("https://api.groq.com") == "https://api.groq.com"
