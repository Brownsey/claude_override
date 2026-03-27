# Claude Code — Ollama Fallback

Normally you use Claude Opus. When you hit rate limits or the API goes down, one command routes Claude Code through a local Ollama model instead. One command routes it back.

There is one bat file: `toggle_ollama.bat`. How you use it depends on whether you use the VS Code extension or the `claude` CLI.

---

## File Structure

```
claude_override/
├── toggle_ollama.bat   ← Windows
├── toggle_ollama.sh    ← Mac / Linux
├── proxy.py            ← HTTP proxy server (managed automatically)
├── config.json         ← stores your chosen Ollama fallback model
└── README.md
```

**`toggle_ollama.bat`** (Windows) / **`toggle_ollama.sh`** (Mac/Linux) — handles everything: installing Ollama, pulling models, starting/stopping the proxy, and setting/clearing `ANTHROPIC_BASE_URL`.

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

| | Windows | Mac | Linux |
|---|---|---|---|
| Script | `toggle_ollama.bat` | `toggle_ollama.sh` | `toggle_ollama.sh` |
| Python 3.8+ | Must be on PATH | Must be on PATH | Must be on PATH |
| Ollama | Auto-installed | Auto via Homebrew | Auto via install script |
| Free disk | ~2–10 GB | ~2–10 GB | ~2–10 GB |

Mac users without Homebrew: install it from [brew.sh](https://brew.sh) or download Ollama manually from [ollama.com/download](https://ollama.com/download).

---

## Usage

Run the script for your OS — everything else is the same.

```bash
# Mac / Linux — make executable once, then run directly
chmod +x toggle_ollama.sh
./toggle_ollama.sh

# Windows
toggle_ollama
```

---

## VS Code Extension Mode

This is the default. The bat file window being open = Ollama active. Closing it = back to normal.

### Switch TO Ollama

```bash
./toggle_ollama.sh     # Mac/Linux
toggle_ollama          # Windows
```

- First run: downloads and installs Ollama, pulls the model (~2 GB for llama3.2)
- Subsequent runs: starts in seconds
- Sets `ANTHROPIC_BASE_URL` persistently via `setx`
- Proxy runs in this window — request logs appear here while active

**Restart VS Code after running** to activate the routing.

### Switch BACK to normal Claude

Press `Ctrl+C` in the terminal running the script.

- **Mac/Linux** — cleanup runs automatically via trap. Done.
- **Windows** — press **N** at the `Terminate batch job (Y/N)?` prompt. Cleanup runs automatically.

`ANTHROPIC_BASE_URL` is removed. **Restart VS Code** to return to your normal Claude.

> If the process was force-killed instead, run:
> ```bash
> ./toggle_ollama.sh off   # Mac/Linux
> toggle_ollama off        # Windows
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

Use `toggle_ollama` on Windows or `./toggle_ollama.sh` on Mac/Linux.

**VS Code extension mode:**
```
toggle_ollama              Switch TO Ollama  (keep window open while active)
toggle_ollama off          Force cleanup     (only if process was killed)
```

**CLI / terminal mode:**
```
toggle_ollama cli-on       Switch TO Ollama  (proxy starts in background)
toggle_ollama cli-off      Switch BACK       (proxy stops)
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
