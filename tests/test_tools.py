from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from vtool_llama.tools import (
    StreamPostProcessor,
    ToolExecutionManager,
    get_active_internal_tools,
    parse_text_tool_calls,
    strip_text_tool_calls,
)


def test_parse_text_tool_calls_supports_official_format():
    text = (
        'hola <tool_call>{"name":"store_long_term_memory",'
        '"arguments":{"content":"El usuario se llama LiuniK","category":"identity"}}</tool_call>'
    )

    calls = parse_text_tool_calls(text)

    assert calls[0][0] == "store_long_term_memory"
    assert calls[0][1]["content"] == "El usuario se llama LiuniK"
    assert calls[0][1]["category"] == "identity"


def test_parse_text_tool_calls_ignores_legacy_formats():
    text = '{{store_long_term_memory{content:"dato", category:"identity"}}}'

    assert parse_text_tool_calls(text) == []


def test_strip_text_tool_calls_hides_internal_markup():
    text = 'ok <tool_call>{"name":"store_long_term_memory","arguments":{"content":"dato","category":"identity"}}</tool_call> listo'

    assert strip_text_tool_calls(text) == "ok  listo"


def test_tool_manager_executes_internal_structured_memory_call():
    add_memory = MagicMock()
    manager = ToolExecutionManager(add_memory_fn=add_memory)
    tool_calls = [{
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "store_long_term_memory",
            "arguments": '{"content":"El usuario se llama LiuniK","category":"identity","priority":0.95}',
        },
    }]

    result = manager.handle_structured_calls(tool_calls, scene_prompt="", user_tools=None)

    assert result["internal_found"] is True
    assert result["memory_saved"] is True
    add_memory.assert_called_once()
    assert add_memory.call_args.kwargs["tags"] == ["identity"]
    assert add_memory.call_args.kwargs["always_include"] is True


def test_tool_manager_returns_only_valid_external_calls():
    manager = ToolExecutionManager(add_memory_fn=MagicMock())
    user_tools = [{"type": "function", "function": {"name": "weather"}}]
    tool_calls = [
        {"function": {"name": "weather", "arguments": "{}"}},
        {"function": {"name": "fake_tool", "arguments": "{}"}},
    ]

    result = manager.handle_structured_calls(tool_calls, scene_prompt="", user_tools=user_tools)

    assert len(result["external_calls"]) == 1
    assert result["external_calls"][0]["function"]["name"] == "weather"


def test_get_active_internal_tools_is_triggered_by_memory_prompt():
    config = SimpleNamespace(always_enable_internal_tools=False)

    assert get_active_internal_tools("hola normal", config) == []
    active = get_active_internal_tools("recuerda que mi nombre es LiuniK", config)
    assert [tool["function"]["name"] for tool in active] == ["store_long_term_memory"]


def test_get_active_internal_tools_can_be_forced_by_config():
    config = SimpleNamespace(always_enable_internal_tools=True)

    active = get_active_internal_tools("hola normal", config)

    assert [tool["function"]["name"] for tool in active] == ["store_long_term_memory"]


def test_stream_processor_hides_tool_call_and_can_defer_execution():
    callback = MagicMock()
    processor = StreamPostProcessor(on_tool_executed=None)
    chunks = [
        {"content": "hola "},
        {"content": '<tool_call>{"name":"store_long_term_memory","arguments":{"content":"dato","category":"identity"}}</tool_call>'},
        {"content": " listo"},
    ]

    events = []
    for chunk in chunks:
        events.extend(processor.feed(chunk))
    events.extend(processor.flush())

    assert "".join(e["content"] for e in events if e["type"] == "text") == "hola  listo"
    assert processor.pending_tool_patterns == [
        '<tool_call>{"name":"store_long_term_memory","arguments":{"content":"dato","category":"identity"}}</tool_call>'
    ]
    callback.assert_not_called()


def test_stream_processor_executes_when_callback_enabled():
    callback = MagicMock()
    processor = StreamPostProcessor(on_tool_executed=callback)

    list(processor.feed({"content": '<tool_call>{"name":"store_long_term_memory","arguments":{"content":"dato","category":"identity"}}</tool_call>'}))

    callback.assert_called_once()
    assert callback.call_args.args[0] == "store_long_term_memory"
