from sophia.llm.types import StopReason
from sophia.llm.openai_provider import (
    OpenAIProvider,
    _max_tokens_param_for_model,
    _parse_tool_arguments,
)


def test_parse_tool_arguments_json_object() -> None:
    parsed = _parse_tool_arguments('{"series_id":"CPIAUCSL","days":30}')
    assert parsed == {"series_id": "CPIAUCSL", "days": 30}


def test_parse_tool_arguments_non_json_returns_raw_wrapper() -> None:
    parsed = _parse_tool_arguments("{not-json")
    assert parsed == {"_raw_arguments": "{not-json"}


def test_openai_parse_response_with_tool_calls() -> None:
    raw = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_latest_value",
                                "arguments": '{"series_id":"UNRATE"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 21, "completion_tokens": 7},
    }

    completion = OpenAIProvider._parse_response(raw)

    assert completion.stop_reason == StopReason.TOOL_USE
    assert completion.usage.input_tokens == 21
    assert completion.usage.output_tokens == 7
    assert len(completion.message.tool_calls) == 1
    assert completion.message.tool_calls[0].name == "get_latest_value"
    assert completion.message.tool_calls[0].input == {"series_id": "UNRATE"}


def test_openai_parse_response_with_null_tool_calls() -> None:
    raw = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "ok",
                    "tool_calls": None,
                },
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 2},
    }

    completion = OpenAIProvider._parse_response(raw)

    assert completion.stop_reason == StopReason.END_TURN
    assert completion.message.content == "ok"
    assert completion.message.tool_calls == []


def test_openai_parse_response_with_inline_tool_call_tags() -> None:
    raw = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": (
                        "Let me try a more targeted search for recent trade policy and tariff "
                        "research:<|tool_calls_section_begin|><|tool_call_begin|>"
                        'functions.search_research:3<|tool_call_argument_begin|>{"limit": 10.0, '
                        '"query": "trade war tariffs economic impact"}<|tool_call_end|>'
                        "<|tool_calls_section_end|>"
                    ),
                    "tool_calls": None,
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 33},
    }

    completion = OpenAIProvider._parse_response(raw)

    assert completion.stop_reason == StopReason.TOOL_USE
    assert completion.message.content == (
        "Let me try a more targeted search for recent trade policy and tariff research:"
    )
    assert len(completion.message.tool_calls) == 1
    assert completion.message.tool_calls[0].id == "tool_call_3"
    assert completion.message.tool_calls[0].name == "search_research"
    assert completion.message.tool_calls[0].input == {
        "limit": 10.0,
        "query": "trade war tariffs economic impact",
    }


def test_openai_parse_response_coerces_list_content_to_text() -> None:
    raw = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "first line"},
                        {"type": "text", "text": "second line"},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 2},
    }

    completion = OpenAIProvider._parse_response(raw)

    assert completion.stop_reason == StopReason.END_TURN
    assert completion.message.content == "first line\nsecond line"
    assert completion.message.tool_calls == []


def test_max_tokens_param_for_gpt5_models() -> None:
    assert _max_tokens_param_for_model("gpt-5.2") == "max_completion_tokens"
    assert _max_tokens_param_for_model("GPT-5") == "max_completion_tokens"


def test_max_tokens_param_for_non_gpt5_models() -> None:
    assert _max_tokens_param_for_model("gpt-4o-mini") == "max_tokens"
    assert _max_tokens_param_for_model("llama3.3-70b") == "max_tokens"
