#!/usr/bin/env bash

# ================================================================
#  toggle_ollama.sh
#  Mac/Linux equivalent of toggle_ollama.bat
#
#  VS Code extension mode (default):
#    ./toggle_ollama.sh            Switch TO Ollama. Ctrl+C to switch back.
#    ./toggle_ollama.sh off        Force cleanup if process was killed.
#
#  Claude CLI / terminal mode:
#    ./toggle_ollama.sh cli-on     Switch TO Ollama (proxy starts in background)
#    ./toggle_ollama.sh cli-off    Switch BACK      (proxy stops)
#
#  Utilities:
#    ./toggle_ollama.sh model NAME   Set fallback model
#    ./toggle_ollama.sh install      Install Ollama only
#    ./toggle_ollama.sh status       Show current state
# ================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.json"
PROXY_PORT=3399
PROXY_URL="http://localhost:$PROXY_PORT"
OLLAMA_URL="http://localhost:11434"
ENV_MARKER="# claude-override"

# ================================================================
#  Commands
# ================================================================

cmd_run() {
    fn_read_config

    echo
    echo "[1/3] Checking Python..."
    if ! command -v python3 >/dev/null 2>&1; then
        echo "  ERROR: python3 not found. Install from https://python.org"
        exit 1
    fi
    echo "  OK."

    echo "[2/3] Checking Ollama..."
    fn_ensure_ollama
    fn_ensure_ollama_running
    ollama pull "$CFG_MODEL"

    echo "[3/3] Activating..."
    fn_set_env_var

    echo
    echo "  ============================================================"
    echo "   OLLAMA ACTIVE  --  model: $CFG_MODEL"
    echo
    echo "   Open a new terminal and restart VS Code to activate."
    echo
    echo "   Ctrl+C to stop and return to your normal Claude."
    echo "  ============================================================"
    echo

    # Clean up automatically on Ctrl+C
    trap 'echo; echo "  Switching back..."; fn_remove_env_var; echo "  Done. Restart VS Code."; exit 0' INT TERM

    # Run proxy in foreground — blocks until Ctrl+C or crash
    python3 "$SCRIPT_DIR/proxy.py"

    # Reached only on proxy crash
    fn_remove_env_var
    echo "  Proxy stopped. ANTHROPIC_BASE_URL cleared."
}

cmd_off() {
    # Force cleanup — for when the process was killed
    echo
    fn_remove_env_var
    fn_stop_proxy
    echo "  Done. Restart VS Code to return to your normal Claude."
    echo
}

cmd_cli_on() {
    fn_read_config

    echo
    echo "[1/2] Checking Ollama..."
    if ! command -v python3 >/dev/null 2>&1; then
        echo "  ERROR: python3 not found."
        exit 1
    fi
    fn_ensure_ollama
    fn_ensure_ollama_running
    ollama pull "$CFG_MODEL"

    echo "[2/2] Starting proxy..."
    python3 "$SCRIPT_DIR/proxy.py" >/dev/null 2>&1 &
    sleep 2

    if fn_is_proxy_up; then
        echo "  Proxy running  [model: $CFG_MODEL]"
    else
        echo "  WARNING: Proxy may not have started."
    fi

    echo
    echo "  ============================================================"
    echo "   PROXY RUNNING  --  model: $CFG_MODEL"
    echo
    echo "   Paste this into your working terminal to switch to Ollama:"
    echo
    echo "     export ANTHROPIC_BASE_URL=\"$PROXY_URL\""
    echo
    echo "   Then use  claude  as normal."
    echo "  ============================================================"
    echo
}

cmd_cli_off() {
    echo
    fn_stop_proxy

    echo
    echo "  ============================================================"
    echo "   PROXY STOPPED"
    echo
    echo "   Paste this into your working terminal to switch back:"
    echo
    echo "     unset ANTHROPIC_BASE_URL"
    echo
    echo "   No restart needed. Next  claude  command uses Anthropic."
    echo "  ============================================================"
    echo
}

cmd_status() {
    fn_read_config

    echo
    echo "  ================= Status ================="
    if fn_is_proxy_up; then
        echo "  Routing:  OLLAMA  [active]"
        echo "  Proxy  :  Running on port $PROXY_PORT"
    else
        echo "  Routing:  CLAUDE  [normal]"
        echo "  Proxy  :  Stopped"
    fi
    if command -v ollama >/dev/null 2>&1; then
        echo "  Ollama :  Installed"
    else
        echo "  Ollama :  Not installed"
    fi
    echo "  Model  :  $CFG_MODEL  (fallback)"
    echo "  =========================================="
    echo
}

cmd_model() {
    local new_model="${1:-}"
    if [ -z "$new_model" ]; then
        echo "  ERROR: Provide a model name.  e.g.  ./toggle_ollama.sh model qwen2.5-coder:7b"
        exit 1
    fi
    fn_write_config "$new_model"
    echo "  Fallback model set to: $new_model"
}

cmd_install() {
    fn_ensure_ollama
}

cmd_help() {
    echo
    echo "  toggle_ollama.sh  --  Local Ollama fallback for Claude Code"
    echo
    echo "  VS CODE EXTENSION MODE  (default)"
    echo "    ./toggle_ollama.sh          Switch TO Ollama  (keep terminal open)"
    echo "    ./toggle_ollama.sh off      Force cleanup     (if process was killed)"
    echo
    echo "  CLI / TERMINAL MODE"
    echo "    ./toggle_ollama.sh cli-on   Switch TO Ollama  (proxy in background)"
    echo "    ./toggle_ollama.sh cli-off  Switch BACK       (proxy stops)"
    echo
    echo "  UTILITIES"
    echo "    ./toggle_ollama.sh status       Show current state"
    echo "    ./toggle_ollama.sh model NAME   Set fallback model"
    echo "    ./toggle_ollama.sh install      Install Ollama without starting"
    echo
    echo "  MODELS"
    echo "    llama3.2            ~2 GB   fast, default"
    echo "    qwen2.5-coder:7b    ~4 GB   best for coding"
    echo "    llama3.1:8b         ~5 GB   higher quality"
    echo "    mistral             ~4 GB   balanced"
    echo
}

# ================================================================
#  Helper functions
# ================================================================

fn_read_config() {
    CFG_MODEL="llama3.2"
    if [ -f "$CONFIG_FILE" ]; then
        local result
        result=$(python3 -c "import json,sys; c=json.load(open(sys.argv[1])); print(c.get('model','llama3.2'))" "$CONFIG_FILE" 2>/dev/null)
        [ -n "$result" ] && CFG_MODEL="$result"
    fi
}

fn_write_config() {
    cat > "$CONFIG_FILE" <<EOF
{
  "model": "$1",
  "mode": "ollama"
}
EOF
}

fn_get_shell_rc() {
    local shell_name
    shell_name=$(basename "${SHELL:-bash}")
    case "$shell_name" in
        zsh)  echo "$HOME/.zshrc" ;;
        bash)
            if [ "$(uname)" = "Darwin" ]; then
                echo "$HOME/.bash_profile"
            else
                echo "$HOME/.bashrc"
            fi
            ;;
        *)    echo "$HOME/.profile" ;;
    esac
}

fn_set_env_var() {
    local rc_file
    rc_file=$(fn_get_shell_rc)
    fn_remove_env_var  # remove any existing entry first
    printf '\nexport ANTHROPIC_BASE_URL="%s"  %s\n' "$PROXY_URL" "$ENV_MARKER" >> "$rc_file"
    echo "  Added ANTHROPIC_BASE_URL to $rc_file"
}

fn_remove_env_var() {
    local rc_file
    rc_file=$(fn_get_shell_rc)
    if [ -f "$rc_file" ] && grep -q "$ENV_MARKER" "$rc_file" 2>/dev/null; then
        grep -v "$ENV_MARKER" "$rc_file" > "${rc_file}.tmp" && mv "${rc_file}.tmp" "$rc_file"
        echo "  Removed ANTHROPIC_BASE_URL from $rc_file"
    fi
}

fn_is_proxy_up() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -i ":$PROXY_PORT" 2>/dev/null | grep -q LISTEN
    else
        netstat -tlnp 2>/dev/null | grep -q ":$PROXY_PORT "
    fi
}

fn_stop_proxy() {
    local pids
    if command -v lsof >/dev/null 2>&1; then
        pids=$(lsof -ti ":$PROXY_PORT" 2>/dev/null || true)
    else
        pids=$(netstat -tlnp 2>/dev/null | awk -v p=":$PROXY_PORT " '$0~p {split($7,a,"/"); print a[1]}' || true)
    fi

    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null || true
        echo "  Stopped proxy."
    else
        echo "  No proxy running on port $PROXY_PORT."
    fi
}

fn_ensure_ollama() {
    if command -v ollama >/dev/null 2>&1; then
        echo "  Ollama installed."
        return 0
    fi

    echo "  Ollama not found. Installing..."
    local os
    os=$(uname -s)

    if [ "$os" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            brew install ollama
        else
            echo "  Homebrew not found."
            echo "  Install Ollama from https://ollama.com/download or install Homebrew first."
            exit 1
        fi
    elif [ "$os" = "Linux" ]; then
        curl -fsSL https://ollama.com/install.sh | sh
    else
        echo "  ERROR: Unsupported OS: $os. Install from https://ollama.com"
        exit 1
    fi

    if ! command -v ollama >/dev/null 2>&1; then
        echo "  NOTE: ollama may not be on PATH yet. Open a new terminal and re-run."
        exit 1
    fi
    echo "  Ollama installed."
}

fn_ensure_ollama_running() {
    if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
        echo "  Ollama service running."
        return 0
    fi
    echo "  Starting Ollama service..."
    ollama serve >/dev/null 2>&1 &
    sleep 3
    if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
        echo "  Ollama service started."
    else
        echo "  WARNING: Ollama may still be initialising."
    fi
}

# ================================================================
#  Dispatch
# ================================================================

case "${1:-}" in
    "")             cmd_run ;;
    cli-on)         cmd_cli_on ;;
    cli-off)        cmd_cli_off ;;
    off)            cmd_off ;;
    status)         cmd_status ;;
    model)          cmd_model "${2:-}" ;;
    install)        cmd_install ;;
    help|-h|--help) cmd_help ;;
    *)
        echo "Unknown command: ${1:-}"
        cmd_help
        exit 1
        ;;
esac
