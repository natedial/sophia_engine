from sophia.llm.groq_provider import (
    _build_emergency_payload,
    _build_slim_payload,
    _normalize_groq_base_url,
)


def test_normalize_groq_base_url_strips_openai_suffix() -> None:
    assert _normalize_groq_base_url("https://api.groq.com/openai/v1") == "https://api.groq.com"
    assert _normalize_groq_base_url("https://api.groq.com/openai/v1/") == "https://api.groq.com"


def test_normalize_groq_base_url_keeps_root() -> None:
    assert _normalize_groq_base_url("https://api.groq.com") == "https://api.groq.com"


def test_build_slim_payload_drops_tools_and_caps_tokens() -> None:
    payload = {
        "model": "openai/gpt-oss-20b",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function"}],
        "tool_choice": "auto",
    }
    slim = _build_slim_payload(payload)

    assert "tools" not in slim
    assert "tool_choice" not in slim
    assert slim["max_tokens"] == 512
    assert slim["model"] == payload["model"]


def test_build_emergency_payload_trims_to_system_and_latest_user() -> None:
    payload = {
        "model": "openai/gpt-oss-20b",
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": "S" * 2000},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "latest user question"},
        ],
        "tools": [{"type": "function"}],
        "tool_choice": "auto",
    }

    emergency = _build_emergency_payload(payload)

    assert "tools" not in emergency
    assert "tool_choice" not in emergency
    assert emergency["max_tokens"] == 256
    assert len(emergency["messages"]) == 2
    assert emergency["messages"][0]["role"] == "system"
    assert len(emergency["messages"][0]["content"]) == 1200
    assert emergency["messages"][1] == {"role": "user", "content": "latest user question"}
