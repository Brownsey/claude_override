#!/usr/bin/env python3
"""
Anthropic API -> Ollama proxy
Translates Claude Code's Anthropic API calls to local Ollama,
allowing seamless switching when Anthropic rate limits are hit.
"""

import json
import os
import uuid
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

PROXY_PORT = 3399
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"model": "llama3.2", "mode": "ollama"}


def translate_request(body):
    """Translate Anthropic Messages API request to Ollama /api/chat format."""
    config = load_config()
    messages = []

    # Anthropic has a top-level 'system' field; OpenAI/Ollama puts it in messages
    if "system" in body:
        system = body["system"]
        if isinstance(system, str):
            messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            text = "\n".join(
                b.get("text", "") for b in system if b.get("type") == "text"
            )
            messages.append({"role": "system", "content": text})

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            parts = []
            for block in content:
                btype = block.get("type", "")
                if btype == "text":
                    parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    tool_content = block.get("content", "")
                    if isinstance(tool_content, list):
                        tool_content = " ".join(
                            b.get("text", "") for b in tool_content
                            if b.get("type") == "text"
                        )
                    parts.append(f"[Tool Result]: {tool_content}")
                elif btype == "tool_use":
                    parts.append(
                        f"[Tool Call: {block.get('name', '')}] "
                        f"{json.dumps(block.get('input', {}))}"
                    )
            messages.append({"role": role, "content": "\n".join(parts)})

    ollama_req = {
        "model": config.get("model", "llama3.2"),
        "messages": messages,
        "stream": body.get("stream", False),
        "options": {},
    }

    if "max_tokens" in body:
        ollama_req["options"]["num_predict"] = body["max_tokens"]
    if "temperature" in body:
        ollama_req["options"]["temperature"] = body["temperature"]

    return ollama_req


def build_sse_event(event_type, data):
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode()


class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[proxy] {fmt % args}", flush=True)

    def send_json_error(self, status, message):
        body = json.dumps({
            "type": "error",
            "error": {"type": "api_error", "message": message}
        }).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"ok","mode":"ollama"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/v1/messages":
            self.handle_messages()
        else:
            self.send_error(404, f"Unknown path: {self.path}")

    def handle_messages(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self.send_json_error(400, "Invalid JSON body")
            return

        request_model = body.get("model", "claude-sonnet-4-6")
        is_streaming = body.get("stream", False)
        ollama_req = translate_request(body)

        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/chat",
                data=json.dumps(ollama_req).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=300) as resp:
                if is_streaming:
                    self._stream_response(resp, request_model)
                else:
                    self._sync_response(resp, request_model)

        except urllib.error.URLError as exc:
            msg = (
                f"Cannot connect to Ollama at {OLLAMA_BASE}. "
                f"Is Ollama running? ({exc})"
            )
            print(f"[proxy] ERROR: {msg}", flush=True)
            self.send_json_error(503, msg)

    def _stream_response(self, resp, request_model):
        """Stream Ollama NDJSON -> Anthropic SSE."""
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # message_start
        self.wfile.write(build_sse_event("message_start", {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": request_model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }))
        # content_block_start
        self.wfile.write(build_sse_event("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }))
        self.wfile.write(build_sse_event("ping", {"type": "ping"}))
        self.wfile.flush()

        output_tokens = 0
        input_tokens = 0

        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            delta = chunk.get("message", {}).get("content", "")
            if delta:
                output_tokens += 1
                self.wfile.write(build_sse_event("content_block_delta", {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": delta},
                }))
                self.wfile.flush()

            if chunk.get("done", False):
                input_tokens = chunk.get("prompt_eval_count", 0)
                output_tokens = chunk.get("eval_count", output_tokens)
                break

        # content_block_stop
        self.wfile.write(build_sse_event("content_block_stop", {
            "type": "content_block_stop", "index": 0
        }))
        # message_delta
        self.wfile.write(build_sse_event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        }))
        # message_stop
        self.wfile.write(build_sse_event("message_stop", {"type": "message_stop"}))
        self.wfile.flush()

    def _sync_response(self, resp, request_model):
        """Non-streaming: translate Ollama response -> Anthropic response."""
        raw = resp.read()
        try:
            ollama_resp = json.loads(raw)
        except json.JSONDecodeError:
            self.send_json_error(500, "Invalid JSON from Ollama")
            return

        content_text = ollama_resp.get("message", {}).get("content", "")
        anthropic_resp = {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": content_text}],
            "model": request_model,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": ollama_resp.get("prompt_eval_count", 0),
                "output_tokens": ollama_resp.get("eval_count", 0),
            },
        }
        body = json.dumps(anthropic_resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    config = load_config()
    model = config.get("model", "llama3.2")
    print(f"[proxy] Anthropic -> Ollama proxy  port={PROXY_PORT}  model={model}")
    print(f"[proxy] Ollama endpoint: {OLLAMA_BASE}")
    print(f"[proxy] Set ANTHROPIC_BASE_URL=http://localhost:{PROXY_PORT} in Claude Code")
    print(f"[proxy] Press Ctrl+C to stop\n", flush=True)
    server = HTTPServer(("127.0.0.1", PROXY_PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[proxy] Stopped")
