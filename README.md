# Claude Code — Ollama Fallback

Normally you use Claude Opus. When you hit rate limits or the API goes down, one command routes Claude Code through a local Ollama model instead. One command routes it back.

There is one bat file: `toggle_ollama.bat`. How you use it depends on whether you use the VS Code extension or the `claude` CLI.

---

## File Structure

```
claude_override/
├── toggle_ollama.bat   ← the only file you interact with
├── proxy.py            ← HTTP proxy server (managed automatically)
├── config.json         ← stores your chosen Ollama fallback model
└── README.md
```

**`toggle_ollama.bat`** — handles everything: installing Ollama, pulling models, starting/stopping the proxy, and setting/clearing `ANTHROPIC_BASE_URL`.

**`proxy.py`** — a stdlib-only Python server on port 3399. Translates Anthropic Messages API calls (including streaming SSE, system prompts, tool calls, tool results) into Ollama `/api/chat` format and streams responses back. Reads `config.json` on every request so you can change model without restarting.

**`config.json`** — stores your chosen fallback model. Updated by `toggle_ollama model <name>`.

---

## How It Works

Claude Code reads `ANTHROPIC_BASE_URL` to decide where to send API requests. When set to `http://localhost:3399`, every call goes to the local proxy instead of Anthropic.

```
Claude Code
    │  Anthropic Messages API
    ▼
proxy.py  :3399
    │  Ollama /api/chat
    ▼
Ollama  :11434
    │
    ▼
Local model  (llama3.2, qwen2.5-coder:7b, ...)
```

No Claude settings files are ever modified.

---

## Requirements

| | |
|---|---|
| Windows 10 / 11 | `setx`, `reg`, `netstat`, `curl` all built-in |
| Python 3.8+ | Must be on PATH — no pip installs needed |
| VS Code + Claude Code | Extension or CLI |
| ~2–10 GB free disk | Depends on model size |

---

## VS Code Extension Mode

This is the default. The bat file window being open = Ollama active. Closing it = back to normal.

### Switch TO Ollama

```bat
toggle_ollama
```

- First run: downloads and installs Ollama, pulls the model (~2 GB for llama3.2)
- Subsequent runs: starts in seconds
- Sets `ANTHROPIC_BASE_URL` persistently via `setx`
- Proxy runs in this window — request logs appear here while active

**Restart VS Code after running** to activate the routing.

### Switch BACK to normal Claude

Press `Ctrl+C` in the `toggle_ollama` window, then press **N** when prompted:

```
Terminate batch job (Y/N)? N
```

The cleanup runs automatically — `ANTHROPIC_BASE_URL` is removed. **Restart VS Code** to return to your normal Claude.

> If you closed the window with the X button instead, run this to clean up:
> ```bat
> toggle_ollama off
> ```

---

## CLI / Terminal Mode *(for later use)*

If you use the `claude` CLI from a terminal rather than the VS Code extension, switching is instant — no restarts ever needed.

The CLI is a fresh process each time you run `claude`, so it picks up env var changes immediately. Setting `ANTHROPIC_BASE_URL` with `set` (not `setx`) only affects that terminal session — nothing persists, nothing needs cleanup beyond unsetting it.

| | VS Code extension | CLI terminal |
|---|---|---|
| env var | persistent via `setx` | session-only via `set` |
| takes effect | after VS Code restart | immediately |
| to revert | Ctrl+C → N, restart VS Code | `set ANTHROPIC_BASE_URL=` |

### Switch TO Ollama

```bat
toggle_ollama cli-on
```

Starts the proxy in a background window. Prints the exact line to paste into your working terminal:

```
cmd        >  set ANTHROPIC_BASE_URL=http://localhost:3399
PowerShell >  $env:ANTHROPIC_BASE_URL = "http://localhost:3399"
```

Paste it, then use `claude` as normal — requests go to Ollama instantly.

### Switch BACK to normal Claude

```bat
toggle_ollama cli-off
```

Stops the proxy. Prints the exact line to paste into your working terminal:

```
cmd        >  set ANTHROPIC_BASE_URL=
PowerShell >  Remove-Item Env:ANTHROPIC_BASE_URL
```

Paste it — the next `claude` command uses Anthropic again immediately.

---

## All Commands

**VS Code extension mode:**
```
toggle_ollama          Switch TO Ollama  (window stays open while active)
toggle_ollama off      Force cleanup     (only if closed with X)
```

**CLI / terminal mode:**
```
toggle_ollama cli-on   Switch TO Ollama  (proxy starts in background)
toggle_ollama cli-off  Switch BACK       (proxy stops)
```

**Utilities:**
```
toggle_ollama status       Show current routing state
toggle_ollama model NAME   Change the Ollama fallback model
toggle_ollama install      Install Ollama without activating
```

---

## Changing the Fallback Model

```bat
toggle_ollama model qwen2.5-coder:7b
```

Takes effect the next time you run `toggle_ollama` or `toggle_ollama cli-on`.

| Model | Size | Best for |
|---|---|---|
| `llama3.2` | ~2 GB | Fast, default |
| `qwen2.5-coder:7b` | ~4 GB | Coding tasks — most Claude-like |
| `llama3.1:8b` | ~5 GB | Higher quality responses |
| `mistral` | ~4 GB | Good balance |
| `gemma2:2b` | ~2 GB | Very fast, low RAM |

---

## Troubleshooting

**Claude Code still uses Anthropic after switching**
Restart VS Code — `ANTHROPIC_BASE_URL` is only read at process launch (extension mode only).

**"Cannot connect to Ollama at localhost:11434"**
Ollama service stopped. Run `ollama serve` in a terminal, then re-run the toggle command.

**`ollama` not found after install**
The installer updated PATH but the current terminal hasn't refreshed. Open a new terminal and retry.

**Port 3399 already in use by something else**
Change `PROXY_PORT` at the top of both `proxy.py` and `toggle_ollama.bat` to any free port.

**Pressed Y at "Terminate batch job" by accident**
`ANTHROPIC_BASE_URL` wasn't cleaned up. Run `toggle_ollama off`, then restart VS Code.
