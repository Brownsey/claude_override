@echo off
setlocal EnableDelayedExpansion

:: ================================================================
::  toggle_ollama.bat
::
::  VS Code extension mode (default):
::    toggle_ollama          Run to switch TO Ollama. Close window to switch back.
::    toggle_ollama off      Force cleanup if you closed the window with X.
::
::  Claude CLI / terminal mode:
::    toggle_ollama cli-on   Start proxy + show command to paste in your terminal
::    toggle_ollama cli-off  Stop proxy  + show command to paste in your terminal
::
::  Utilities:
::    toggle_ollama model NAME   Set fallback model
::    toggle_ollama install      Install Ollama only
::    toggle_ollama status       Show current state
:: ================================================================

set "SCRIPT_DIR=%~dp0"
set "CONFIG_FILE=!SCRIPT_DIR!config.json"
set "PROXY_PORT=3399"
set "PROXY_URL=http://localhost:!PROXY_PORT!"
set "OLLAMA_URL=http://localhost:11434"
set "OLLAMA_INSTALLER=https://ollama.com/download/OllamaSetup.exe"

set "CMD=%~1"
if "!CMD!"=="" goto :cmd_run

if /i "!CMD!"=="cli-on"  goto :cmd_cli_on
if /i "!CMD!"=="cli-off" goto :cmd_cli_off
if /i "!CMD!"=="off"     goto :cmd_off
if /i "!CMD!"=="status"  goto :cmd_status
if /i "!CMD!"=="model"   goto :cmd_model
if /i "!CMD!"=="install" goto :cmd_install
if /i "!CMD!"=="help"    goto :cmd_help
if /i "!CMD!"=="-h"      goto :cmd_help
if /i "!CMD!"=="/?"      goto :cmd_help

echo Unknown command: !CMD!
goto :cmd_help

:: ----------------------------------------------------------------
::  VS CODE EXTENSION MODE
::  Run this file -> Ollama active. Close this window -> back to normal.
:: ----------------------------------------------------------------
:cmd_run
call :fn_read_config

echo.
echo [1/3] Checking Python...
where python >nul 2>&1
if !errorlevel! neq 0 (
    echo   ERROR: Python not found. Install from https://python.org
    exit /b 1
)
echo   OK.

echo [2/3] Checking Ollama...
call :fn_ensure_ollama || exit /b 1
call :fn_ensure_ollama_running
ollama pull !CFG_MODEL!

echo [3/3] Activating...
setx ANTHROPIC_BASE_URL "!PROXY_URL!" >nul 2>&1

echo.
echo  ============================================================
echo   OLLAMA ACTIVE  --  model: !CFG_MODEL!
echo.
echo   Restart VS Code now to activate.
echo.
echo   CLOSE THIS WINDOW to switch back to your normal Claude.
echo   (Ctrl+C then press N if using keyboard)
echo  ============================================================
echo.

:: Proxy runs here — blocks until window is closed / Ctrl+C
python "!SCRIPT_DIR!proxy.py"

:: Auto-cleanup after proxy stops
echo.
echo  Switching back...
reg delete "HKCU\Environment" /v "ANTHROPIC_BASE_URL" /f >nul 2>&1
echo  Done. Restart VS Code to return to your normal Claude.
echo.
pause
exit /b 0

:: ----------------------------------------------------------------
:cmd_off
:: Force cleanup — for when the window was killed with X
echo.
reg delete "HKCU\Environment" /v "ANTHROPIC_BASE_URL" /f >nul 2>&1
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":3399 " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
    echo  Stopped proxy ^(PID %%p^).
)
echo  Done. Restart VS Code to return to your normal Claude.
echo.
exit /b 0

:: ----------------------------------------------------------------
::  CLI / TERMINAL MODE
::  Proxy runs in background. You paste one line in your terminal to switch.
:: ----------------------------------------------------------------
:cmd_cli_on
call :fn_read_config

echo.
echo [1/2] Checking Ollama...
where python >nul 2>&1
if !errorlevel! neq 0 (
    echo   ERROR: Python not found. Install from https://python.org
    exit /b 1
)
call :fn_ensure_ollama || exit /b 1
call :fn_ensure_ollama_running
ollama pull !CFG_MODEL!

echo [2/2] Starting proxy...
start "OllamaProxy" /min python "!SCRIPT_DIR!proxy.py"
timeout /t 2 /nobreak >nul
call :fn_check_proxy

echo.
echo  ============================================================
echo   PROXY RUNNING  --  model: !CFG_MODEL!
echo.
echo   Now paste this into your working terminal to switch to Ollama:
echo.
echo     cmd        ^>  set ANTHROPIC_BASE_URL=!PROXY_URL!
echo     PowerShell ^>  $env:ANTHROPIC_BASE_URL = "!PROXY_URL!"
echo.
echo   Then use  claude  as normal.
echo  ============================================================
echo.
exit /b 0

:: ----------------------------------------------------------------
:cmd_cli_off
echo.
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":3399 " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
    echo  Stopped proxy ^(PID %%p^).
)
echo.
echo  ============================================================
echo   PROXY STOPPED
echo.
echo   Now paste this into your working terminal to switch back:
echo.
echo     cmd        ^>  set ANTHROPIC_BASE_URL=
echo     PowerShell ^>  Remove-Item Env:ANTHROPIC_BASE_URL
echo.
echo   No restart needed. Next  claude  command uses Anthropic.
echo  ============================================================
echo.
exit /b 0

:: ----------------------------------------------------------------
:cmd_status
call :fn_read_config
call :fn_get_reg_url
call :fn_check_proxy

echo.
echo  ================= Status =================
if "!REG_URL!"=="!PROXY_URL!" (
    echo   Routing:  OLLAMA  [active]
) else if defined REG_URL (
    echo   Routing:  CUSTOM  [!REG_URL!]
) else (
    echo   Routing:  CLAUDE  [normal]
)
if "!PROXY_UP!"=="1" (
    echo   Proxy  :  Running on port !PROXY_PORT!
) else (
    echo   Proxy  :  Stopped
)
where ollama >nul 2>&1
if !errorlevel! equ 0 (
    echo   Ollama :  Installed
) else (
    echo   Ollama :  Not installed
)
echo   Model  :  !CFG_MODEL!  ^(fallback^)
echo  ==========================================
echo.
exit /b 0

:: ----------------------------------------------------------------
:cmd_model
set "NEW_MODEL=%~2"
if "!NEW_MODEL!"=="" (
    echo  ERROR: Provide a model name.  e.g.  toggle_ollama model qwen2.5-coder:7b
    exit /b 1
)
call :fn_write_config "!NEW_MODEL!"
echo  Fallback model set to: !NEW_MODEL!
exit /b 0

:: ----------------------------------------------------------------
:cmd_install
call :fn_ensure_ollama
exit /b

:: ----------------------------------------------------------------
:cmd_help
echo.
echo  toggle_ollama  --  Local Ollama fallback for Claude Code
echo.
echo  VS CODE EXTENSION MODE  ^(default^)
echo    toggle_ollama        Switch TO Ollama  ^(keep window open^)
echo    toggle_ollama off    Force cleanup     ^(only if closed with X^)
echo.
echo  CLI / TERMINAL MODE
echo    toggle_ollama cli-on    Switch TO Ollama  ^(proxy starts in background^)
echo    toggle_ollama cli-off   Switch BACK       ^(proxy stops^)
echo.
echo  UTILITIES
echo    toggle_ollama status       Show current state
echo    toggle_ollama model NAME   Set fallback model
echo    toggle_ollama install      Install Ollama without starting
echo.
exit /b 0

:: ================================================================
::  Subroutines
:: ================================================================

:fn_read_config
set "CFG_MODEL=llama3.2"
if not exist "!CONFIG_FILE!" exit /b 0
python -c "import json,sys; c=json.load(open(sys.argv[1])); print(c.get('model','llama3.2'))" "!CONFIG_FILE!" > "!TEMP!\cc_model.tmp" 2>nul
if exist "!TEMP!\cc_model.tmp" (
    set /p CFG_MODEL= < "!TEMP!\cc_model.tmp"
    del "!TEMP!\cc_model.tmp" >nul 2>&1
)
exit /b 0

:fn_write_config
set "WM=%~1"
(
    echo {
    echo   "model": "!WM!",
    echo   "mode": "ollama"
    echo }
) > "!CONFIG_FILE!"
exit /b 0

:fn_get_reg_url
set "REG_URL="
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v "ANTHROPIC_BASE_URL" 2^>nul') do set "REG_URL=%%b"
exit /b 0

:fn_check_proxy
set "PROXY_UP=0"
netstat -aon 2>nul | findstr ":3399 " | findstr "LISTENING" >nul 2>&1
if !errorlevel! equ 0 set "PROXY_UP=1"
exit /b 0

:fn_ensure_ollama
where ollama >nul 2>&1
if !errorlevel! equ 0 (
    echo   Ollama installed.
    exit /b 0
)
echo   Ollama not found. Downloading installer...
set "DL=!TEMP!\OllamaSetup.exe"
curl -L --progress-bar -o "!DL!" "!OLLAMA_INSTALLER!"
if !errorlevel! neq 0 (
    echo   ERROR: Download failed. Check internet connection.
    exit /b 1
)
echo   Running installer...
"!DL!"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v "PATH" 2^>nul') do set "PATH=!PATH!;%%b"
where ollama >nul 2>&1
if !errorlevel! neq 0 (
    echo   NOTE: Open a new terminal after install and re-run.
    exit /b 1
)
echo   Ollama installed.
exit /b 0

:fn_ensure_ollama_running
curl -sf "!OLLAMA_URL!/api/tags" >nul 2>&1
if !errorlevel! equ 0 (
    echo   Ollama service running.
    exit /b 0
)
echo   Starting Ollama service...
start "" ollama serve
timeout /t 3 /nobreak >nul
curl -sf "!OLLAMA_URL!/api/tags" >nul 2>&1
if !errorlevel! equ 0 (
    echo   Ollama service started.
) else (
    echo   WARNING: Ollama may still be initialising.
)
exit /b 0
