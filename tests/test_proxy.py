"""
Tests for proxy.py — covers all routes and translation logic.

Runs a real HTTPServer on port 3401 and mocks urllib.request.urlopen
so no live Ollama instance is needed.
"""

import http.client as _http_client
import json
import os
import sys
import threading
import time
import urllib.error
from http.server import HTTPServer
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proxy

TEST_PORT = 3401


# ================================================================
#  Shared helpers
# ================================================================

class FakeOllamaResponse:
    """
    Simulates the response object returned by urllib.request.urlopen.
    Supports both sync (read()) and streaming (iteration) modes,
    and works as a context manager.
    """

    def __init__(self, data=b"", chunks=None):
        self._data = data
        self._chunks = chunks or []

    def read(self):
        return self._data

    def __iter__(self):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http(method, path, body=None, raw_body=None):
    """
    Make an HTTP request to the test server using http.client directly.
    Using http.client instead of urllib avoids colliding with the
    patch("proxy.urllib.request.urlopen") used in tests.
    Returns (status, content_type, body_bytes).
    """
    if raw_body is not None:
        data = raw_body
    elif body is not None:
        data = json.dumps(body).encode()
    else:
        data = None
    headers = {"Content-Type": "application/json"} if data else {}
    conn = _http_client.HTTPConnection("127.0.0.1", TEST_PORT, timeout=10)
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    status = resp.status
    ct = resp.getheader("Content-Type", "")
    response_body = resp.read()
    conn.close()
    return status, ct, response_body


def parse_sse(body_bytes):
    """Parse SSE response body into a list of {type, data} dicts."""
    events = []
    for block in body_bytes.decode().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event["type"] = line[7:]
            elif line.startswith("data: "):
                event["data"] = json.loads(line[6:])
        if event:
            events.append(event)
    return events


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(scope="module")
def test_server():
    """Start a real HTTPServer on TEST_PORT for the duration of the module."""
    server = HTTPServer(("127.0.0.1", TEST_PORT), proxy.ProxyHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    time.sleep(0.1)  # give the server a moment to bind
    yield
    server.shutdown()
    server.server_close()


def sync_body(text="hi", input_tokens=5, output_tokens=3):
    """Build a fake Ollama sync response body."""
    return json.dumps({
        "message": {"content": text},
        "prompt_eval_count": input_tokens,
        "eval_count": output_tokens,
    }).encode()


def stream_chunks(tokens=("Hello", " world"), done_input=8, done_output=4):
    """Build fake Ollama NDJSON stream chunks."""
    chunks = [
        json.dumps({"message": {"content": t}, "done": False}).encode() + b"\n"
        for t in tokens
    ]
    chunks.append(
        json.dumps({
            "message": {"content": ""},
            "done": True,
            "prompt_eval_count": done_input,
            "eval_count": done_output,
        }).encode() + b"\n"
    )
    return chunks


# ================================================================
#  Unit: build_sse_event
# ================================================================

class TestBuildSseEvent:
    def test_starts_with_event_line(self):
        result = proxy.build_sse_event("ping", {"type": "ping"})
        assert result.startswith(b"event: ping\n")

    def test_data_line_is_valid_json(self):
        payload = {"type": "content_block_delta", "index": 0}
        result = proxy.build_sse_event("content_block_delta", payload)
        data_line = next(l for l in result.decode().split("\n") if l.startswith("data: "))
        assert json.loads(data_line[6:]) == payload

    def test_ends_with_double_newline(self):
        result = proxy.build_sse_event("message_stop", {"type": "message_stop"})
        assert result.endswith(b"\n\n")

    def test_returns_bytes(self):
        result = proxy.build_sse_event("ping", {})
        assert isinstance(result, bytes)


# ================================================================
#  Unit: load_config
# ================================================================

class TestLoadConfig:
    def test_default_when_file_missing(self, tmp_path):
        with patch("proxy.CONFIG_FILE", str(tmp_path / "no_file.json")):
            cfg = proxy.load_config()
        assert cfg["model"] == "llama3.2"
        assert cfg["mode"] == "ollama"

    def test_reads_model_from_file(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"model": "mistral", "mode": "ollama"}))
        with patch("proxy.CONFIG_FILE", str(cfg_path)):
            cfg = proxy.load_config()
        assert cfg["model"] == "mistral"

    def test_default_on_corrupt_json(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{ not valid json }")
        with patch("proxy.CONFIG_FILE", str(cfg_path)):
            cfg = proxy.load_config()
        assert cfg["model"] == "llama3.2"


# ================================================================
#  Unit: translate_request
# ================================================================

class TestTranslateRequest:

    @pytest.fixture(autouse=True)
    def mock_config(self):
        with patch("proxy.load_config", return_value={"model": "test-model"}):
            yield

    # -- model selection --

    def test_uses_model_from_config(self):
        result = proxy.translate_request({"messages": []})
        assert result["model"] == "test-model"

    # -- message content formats --

    def test_string_content_passed_through(self):
        body = {"messages": [{"role": "user", "content": "Hello"}]}
        result = proxy.translate_request(body)
        assert result["messages"][0] == {"role": "user", "content": "Hello"}

    def test_list_content_text_blocks_joined(self):
        body = {"messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": " world"},
            ],
        }]}
        result = proxy.translate_request(body)
        assert result["messages"][0]["content"] == "Hello\n world"

    def test_tool_result_with_list_content(self):
        body = {"messages": [{
            "role": "user",
            "content": [{"type": "tool_result", "content": [{"type": "text", "text": "42"}]}],
        }]}
        result = proxy.translate_request(body)
        assert "[Tool Result]: 42" in result["messages"][0]["content"]

    def test_tool_result_with_string_content(self):
        body = {"messages": [{
            "role": "user",
            "content": [{"type": "tool_result", "content": "the answer"}],
        }]}
        result = proxy.translate_request(body)
        assert "[Tool Result]: the answer" in result["messages"][0]["content"]

    def test_tool_use_block(self):
        body = {"messages": [{
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "bash", "input": {"cmd": "ls"}}],
        }]}
        result = proxy.translate_request(body)
        content = result["messages"][0]["content"]
        assert "[Tool Call: bash]" in content
        assert '"cmd": "ls"' in content

    # -- system prompt --

    def test_system_string_prepended_as_system_message(self):
        body = {"system": "You are helpful.", "messages": [{"role": "user", "content": "Hi"}]}
        result = proxy.translate_request(body)
        assert result["messages"][0] == {"role": "system", "content": "You are helpful."}
        assert result["messages"][1]["role"] == "user"

    def test_system_list_of_blocks(self):
        body = {
            "system": [
                {"type": "text", "text": "You are helpful."},
                {"type": "text", "text": " Be concise."},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = proxy.translate_request(body)
        system_msg = result["messages"][0]
        assert system_msg["role"] == "system"
        assert "You are helpful." in system_msg["content"]
        assert "Be concise." in system_msg["content"]

    def test_no_system_means_no_extra_message(self):
        body = {"messages": [{"role": "user", "content": "Hi"}]}
        result = proxy.translate_request(body)
        assert result["messages"][0]["role"] == "user"

    # -- options --

    def test_max_tokens_mapped_to_num_predict(self):
        result = proxy.translate_request({"messages": [], "max_tokens": 512})
        assert result["options"]["num_predict"] == 512

    def test_temperature_passed_through(self):
        result = proxy.translate_request({"messages": [], "temperature": 0.8})
        assert result["options"]["temperature"] == 0.8

    def test_no_options_when_not_provided(self):
        result = proxy.translate_request({"messages": []})
        assert result["options"] == {}

    # -- stream flag --

    def test_stream_true_preserved(self):
        result = proxy.translate_request({"messages": [], "stream": True})
        assert result["stream"] is True

    def test_stream_false_preserved(self):
        result = proxy.translate_request({"messages": [], "stream": False})
        assert result["stream"] is False

    # -- multi-turn --

    def test_multiple_messages_all_included(self):
        body = {"messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ]}
        result = proxy.translate_request(body)
        assert len(result["messages"]) == 3
        assert result["messages"][1]["role"] == "assistant"

    def test_unknown_block_type_is_ignored(self):
        body = {"messages": [{
            "role": "user",
            "content": [
                {"type": "unknown_type", "data": "ignored"},
                {"type": "text", "text": "Hello"},
            ],
        }]}
        result = proxy.translate_request(body)
        assert result["messages"][0]["content"] == "Hello"

    def test_empty_system_list_produces_empty_content(self):
        body = {"system": [], "messages": [{"role": "user", "content": "Hi"}]}
        result = proxy.translate_request(body)
        # Empty list: system message is added with empty content
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][0]["content"] == ""

    def test_system_list_skips_non_text_blocks(self):
        body = {
            "system": [
                {"type": "tool_result", "content": "ignored"},
                {"type": "text", "text": "Only this"},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = proxy.translate_request(body)
        assert result["messages"][0]["content"] == "Only this"


# ================================================================
#  Integration: GET /health
# ================================================================

class TestHealthEndpoint:
    def test_returns_200(self, test_server):
        status, _, _ = http("GET", "/health")
        assert status == 200

    def test_content_type_is_json(self, test_server):
        _, ct, _ = http("GET", "/health")
        assert "application/json" in ct

    def test_body_status_ok(self, test_server):
        _, _, body = http("GET", "/health")
        assert json.loads(body)["status"] == "ok"

    def test_body_mode_is_ollama(self, test_server):
        _, _, body = http("GET", "/health")
        assert json.loads(body)["mode"] == "ollama"


# ================================================================
#  Integration: unknown routes
# ================================================================

class TestUnknownRoutes:
    def test_unknown_get_returns_404(self, test_server):
        status, _, _ = http("GET", "/unknown")
        assert status == 404

    def test_unknown_post_returns_404(self, test_server):
        status, _, _ = http("POST", "/unknown", body={})
        assert status == 404

    def test_root_get_returns_404(self, test_server):
        status, _, _ = http("GET", "/")
        assert status == 404


# ================================================================
#  Integration: POST /v1/messages — error cases
# ================================================================

class TestMessagesErrors:
    def test_invalid_json_returns_400(self, test_server):
        status, _, body = http("POST", "/v1/messages", raw_body=b"not json {{{")
        assert status == 400
        assert json.loads(body)["type"] == "error"

    def test_ollama_unreachable_returns_503(self, test_server):
        with patch(
            "proxy.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            status, _, body = http("POST", "/v1/messages", body={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            })
        assert status == 503
        data = json.loads(body)
        assert data["type"] == "error"
        assert "Ollama" in data["error"]["message"]


# ================================================================
#  Integration: POST /v1/messages — sync (non-streaming)
# ================================================================

class TestSyncResponse:
    def _request(self, test_server, model="claude-sonnet-4-6", text="Hello from Ollama",
                 input_tok=10, output_tok=7):
        fake = FakeOllamaResponse(data=sync_body(text, input_tok, output_tok))
        with patch("proxy.urllib.request.urlopen", return_value=fake):
            status, ct, body = http("POST", "/v1/messages", body={
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 100,
                "stream": False,
            })
        return status, ct, json.loads(body)

    def test_returns_200(self, test_server):
        status, _, _ = self._request(test_server)
        assert status == 200

    def test_content_type_json(self, test_server):
        _, ct, _ = self._request(test_server)
        assert "application/json" in ct

    def test_type_is_message(self, test_server):
        _, _, data = self._request(test_server)
        assert data["type"] == "message"

    def test_role_is_assistant(self, test_server):
        _, _, data = self._request(test_server)
        assert data["role"] == "assistant"

    def test_content_text(self, test_server):
        _, _, data = self._request(test_server, text="Hello from Ollama")
        assert data["content"][0]["type"] == "text"
        assert data["content"][0]["text"] == "Hello from Ollama"

    def test_stop_reason_end_turn(self, test_server):
        _, _, data = self._request(test_server)
        assert data["stop_reason"] == "end_turn"

    def test_preserves_request_model(self, test_server):
        _, _, data = self._request(test_server, model="claude-opus-4-6")
        assert data["model"] == "claude-opus-4-6"

    def test_usage_input_tokens(self, test_server):
        _, _, data = self._request(test_server, input_tok=20, output_tok=15)
        assert data["usage"]["input_tokens"] == 20

    def test_usage_output_tokens(self, test_server):
        _, _, data = self._request(test_server, input_tok=20, output_tok=15)
        assert data["usage"]["output_tokens"] == 15

    def test_response_has_id(self, test_server):
        _, _, data = self._request(test_server)
        assert data["id"].startswith("msg_")

    def test_invalid_json_from_ollama_returns_500(self, test_server):
        fake = FakeOllamaResponse(data=b"not valid json {{")
        with patch("proxy.urllib.request.urlopen", return_value=fake):
            status, _, body = http("POST", "/v1/messages", body={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            })
        assert status == 500
        assert json.loads(body)["type"] == "error"


# ================================================================
#  Integration: POST /v1/messages — streaming (SSE)
# ================================================================

class TestStreamingResponse:
    def _request(self, test_server, tokens=("Hello", " world"), model="claude-sonnet-4-6"):
        fake = FakeOllamaResponse(chunks=stream_chunks(tokens))
        with patch("proxy.urllib.request.urlopen", return_value=fake):
            status, ct, body = http("POST", "/v1/messages", body={
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            })
        return status, ct, body

    def test_returns_200(self, test_server):
        status, _, _ = self._request(test_server)
        assert status == 200

    def test_content_type_event_stream(self, test_server):
        _, ct, _ = self._request(test_server)
        assert "text/event-stream" in ct

    def test_emits_message_start(self, test_server):
        _, _, body = self._request(test_server)
        types = [e["type"] for e in parse_sse(body)]
        assert "message_start" in types

    def test_emits_content_block_start(self, test_server):
        _, _, body = self._request(test_server)
        types = [e["type"] for e in parse_sse(body)]
        assert "content_block_start" in types

    def test_emits_ping(self, test_server):
        _, _, body = self._request(test_server)
        types = [e["type"] for e in parse_sse(body)]
        assert "ping" in types

    def test_emits_content_block_delta_per_token(self, test_server):
        _, _, body = self._request(test_server, tokens=("Hello", " world"))
        events = parse_sse(body)
        deltas = [e for e in events if e["type"] == "content_block_delta"]
        texts = [e["data"]["delta"]["text"] for e in deltas]
        assert "Hello" in texts
        assert " world" in texts

    def test_emits_content_block_stop(self, test_server):
        _, _, body = self._request(test_server)
        types = [e["type"] for e in parse_sse(body)]
        assert "content_block_stop" in types

    def test_emits_message_delta_with_stop_reason(self, test_server):
        _, _, body = self._request(test_server)
        events = parse_sse(body)
        msg_delta = next(e for e in events if e["type"] == "message_delta")
        assert msg_delta["data"]["delta"]["stop_reason"] == "end_turn"

    def test_emits_message_stop(self, test_server):
        _, _, body = self._request(test_server)
        types = [e["type"] for e in parse_sse(body)]
        assert "message_stop" in types

    def test_event_order(self, test_server):
        _, _, body = self._request(test_server)
        types = [e["type"] for e in parse_sse(body)]
        # Core sequence must appear in order
        sequence = ["message_start", "content_block_start", "content_block_stop",
                    "message_delta", "message_stop"]
        indices = [types.index(t) for t in sequence]
        assert indices == sorted(indices)

    def test_message_start_contains_model(self, test_server):
        _, _, body = self._request(test_server, model="claude-opus-4-6")
        events = parse_sse(body)
        start = next(e for e in events if e["type"] == "message_start")
        assert start["data"]["message"]["model"] == "claude-opus-4-6"

    def test_delta_type_is_text_delta(self, test_server):
        _, _, body = self._request(test_server, tokens=("Hi",))
        events = parse_sse(body)
        deltas = [e for e in events if e["type"] == "content_block_delta"]
        assert all(e["data"]["delta"]["type"] == "text_delta" for e in deltas)

    def test_usage_in_message_delta(self, test_server):
        fake = FakeOllamaResponse(chunks=stream_chunks(done_input=10, done_output=5))
        with patch("proxy.urllib.request.urlopen", return_value=fake):
            _, _, body = http("POST", "/v1/messages", body={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            })
        events = parse_sse(body)
        msg_delta = next(e for e in events if e["type"] == "message_delta")
        assert msg_delta["data"]["usage"]["output_tokens"] == 5

    def test_message_start_has_msg_id(self, test_server):
        _, _, body = self._request(test_server)
        events = parse_sse(body)
        start = next(e for e in events if e["type"] == "message_start")
        assert start["data"]["message"]["id"].startswith("msg_")

    def test_truncated_stream_still_emits_stop_events(self, test_server):
        # Stream ends without a done=True chunk — proxy should still close cleanly
        chunks = [
            json.dumps({"message": {"content": "Hello"}, "done": False}).encode() + b"\n",
        ]
        fake = FakeOllamaResponse(chunks=chunks)
        with patch("proxy.urllib.request.urlopen", return_value=fake):
            status, _, body = http("POST", "/v1/messages", body={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            })
        assert status == 200
        types = [e["type"] for e in parse_sse(body)]
        assert "message_stop" in types
        assert "content_block_stop" in types
