from sophia.llm.types import StopReason
from sophia.llm.openai_provider import OpenAIProvider, _parse_tool_arguments


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
