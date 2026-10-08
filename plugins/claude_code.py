"""
Claude Code bridge — lets the assistant hand a real piece of work to Claude Code.

The Live model is quick at talking and at the small tools; it is not the thing
to write a program, refactor a project or work through a folder of files. This
plugin passes such a task to the Claude Code CLI (`claude -p`, headless mode),
runs it in the background in a working folder, and has the assistant report back
out loud when it finishes. The full answer also goes to the content panel.

Requirements: Claude Code installed and logged in once in a terminal
(`claude` → /login). Settings live under ⚙ → plugin settings → Claude Code.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

try:
    from memory.config_manager import get_plugin_config
except Exception:                                    # pragma: no cover
    def get_plugin_config(_ns):                      # type: ignore
        return {}

_NS = "claude_code"
_WIN = platform.system() == "Windows"
_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _WIN else {}

_running: dict[int, dict] = {}       # task id -> {"task", "cwd", "start"}
_last: dict = {}                     # last finished task, for "status"
_lock = threading.Lock()
_next_id = 0


PLUGIN = {
    "name": "claude_code",
    "description": (
        "Delegate a substantial task to Claude Code, an expert AI coding agent "
        "that works directly on this computer's files. Use it when the user asks "
        "to involve Claude ('pede pro Claude', 'usa o Claude', 'Claude Code'), or "
        "for work beyond the quick tools: writing or fixing a program or script, "
        "changing or analysing a project/codebase, multi-step work across many "
        "files, or a detailed technical analysis of local files. Runs in the "
        "background and can take minutes — after calling it, tell the user in one "
        "short sentence that Claude is working on it; the result is announced "
        "automatically when it finishes. Do NOT use it for simple single actions "
        "that a dedicated tool already does (create one folder, open an app, "
        "volume, weather, a web search). action='status' reports running tasks."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {
                "type": "STRING",
                "description": "Complete, self-contained instructions for Claude, "
                               "in the user's words plus every detail they gave "
                               "(file names, folders, expected result).",
            },
            "working_dir": {
                "type": "STRING",
                "description": "Folder to work in: an absolute path, or desktop | "
                               "documents | downloads | home. Empty = the "
                               "configured default folder.",
            },
            "continue_previous": {
                "type": "BOOLEAN",
                "description": "True when this is a follow-up to the previous "
                               "Claude task (keeps Claude's context).",
            },
            "action": {
                "type": "STRING",
                "description": "run (default) | status",
            },
        },
        "required": [],
    },
}


def _find_claude(cfg: dict) -> str | None:
    custom = str(cfg.get("claude_path") or "").strip().strip('"')
    if custom and Path(custom).exists():
        return custom
    for name in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(name)
        if p:
            return p
    home = Path.home()
    for cand in (home / ".local" / "bin" / "claude.exe",
                 home / ".local" / "bin" / "claude",
                 Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
                 home / ".claude" / "local" / "claude"):
        if cand.exists():
            return str(cand)
    return None


def _test(values: dict):
    exe = _find_claude(values)
    if not exe:
        return False, "Claude Code não encontrado. Instale e faça /login no terminal."
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           timeout=30, **_HIDE)
        return True, f"OK — {(r.stdout or r.stderr).strip()[:60]}"
    except Exception as e:
        return False, f"Falhou: {e}"


PLUGIN_SETTINGS = {
    "namespace": _NS,
    "title": "Claude Code",
    "fields": [
        {"key": "default_dir", "label": "Pasta padrão de trabalho",
         "type": "text", "placeholder": "desktop  (ou um caminho completo)"},
        {"key": "permission_mode", "label": "Permissões do Claude",
         "type": "choice", "default": "acceptEdits",
         "options": ["acceptEdits", "bypassPermissions", "default"]},
        {"key": "model", "label": "Modelo (vazio = padrão da conta)",
         "type": "text", "placeholder": "ex.: opus, sonnet"},
        {"key": "timeout_min", "label": "Tempo máximo (minutos)",
         "type": "text", "default": "20"},
        {"key": "claude_path", "label": "Caminho do executável (opcional)",
         "type": "text", "placeholder": "detectado automaticamente"},
    ],
    "action": {"label": "TESTAR CLAUDE CODE", "run": _test},
}


def _resolve_dir(raw: str, cfg: dict) -> Path:
    raw = (raw or "").strip().strip('"') or str(cfg.get("default_dir") or "desktop")
    try:
        from core.known_folders import user_folder
        if raw.lower() in ("desktop", "documents", "downloads", "pictures",
                           "music", "videos"):
            return user_folder(raw.lower())
    except Exception:
        pass
    if raw.lower() == "home":
        return Path.home()
    p = Path(raw).expanduser()
    return p if p.is_absolute() else Path.home() / p


def _log(player, text: str) -> None:
    try:
        if player:
            player.write_log(text)
    except Exception:
        pass


def _say(player, text: str) -> None:
    try:
        fn = getattr(player, "request_say", None)
        if callable(fn):
            fn(text)
    except Exception:
        pass


def _worker(tid: int, exe: str, task: str, cwd: Path, cfg: dict,
            cont: bool, player) -> None:
    global _last
    cmd = [exe, "-p", "--output-format", "json",
           "--permission-mode", str(cfg.get("permission_mode") or "acceptEdits")]
    if cont:
        cmd.append("--continue")
    model = str(cfg.get("model") or "").strip()
    if model:
        cmd += ["--model", model]
    prompt = (
        f"{task}\n\n"
        "(Request relayed by voice from the user through their desktop assistant. "
        "Work autonomously; nobody can answer questions mid-task. Finish with a "
        "short summary in Brazilian Portuguese of what you did and where any "
        "files are.)"
    )
    try:
        timeout = max(1.0, float(str(cfg.get("timeout_min") or "20"))) * 60
    except ValueError:
        timeout = 1200
    t0 = time.time()
    ok, text, cost = False, "", None
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(cwd),
                           timeout=timeout, **_HIDE)
        out = (r.stdout or "").strip()
        try:
            data = json.loads(out.splitlines()[-1] if out else "{}")
            text = str(data.get("result") or "").strip()
            ok = not data.get("is_error") and r.returncode == 0
            cost = data.get("total_cost_usd")
        except Exception:
            text = out or (r.stderr or "").strip()
            ok = r.returncode == 0
        if not text:
            text = (r.stderr or "").strip() or f"exit code {r.returncode}"
    except subprocess.TimeoutExpired:
        text = f"Tempo esgotado após {int(timeout // 60)} minutos."
    except Exception as e:
        text = f"Erro ao executar o Claude Code: {e}"

    dur = int(time.time() - t0)
    with _lock:
        _running.pop(tid, None)
        _last = {"task": task, "ok": ok, "result": text, "secs": dur}

    title = "Claude Code — concluído" if ok else "Claude Code — falhou"
    try:
        if player and hasattr(player, "show_content"):
            extra = f"\n\n({dur}s" + (f", US$ {cost:.3f}" if isinstance(cost, (int, float)) else "") + ")"
            player.show_content(title, text + extra)
    except Exception:
        pass
    _log(player, f"{'SYS' if ok else 'ERR'}: Claude Code {'concluiu' if ok else 'falhou'} em {dur}s.")
    _say(player,
         "[TOOL RESULT — Claude Code finished a background task you delegated"
         f"{'' if ok else ' (it FAILED)'}]\n"
         f"Task: {task[:300]}\n"
         f"Claude's report:\n{text[:3000]}\n\n"
         "Tell the user in one or two short sentences, in Brazilian Portuguese, "
         "what was done (or why it failed). The full report is on screen. "
         "Call no tools.")


def run(parameters: dict, player=None, session_memory=None) -> str:
    global _next_id
    cfg = get_plugin_config(_NS)
    action = str(parameters.get("action") or "run").strip().lower()

    if action == "status":
        with _lock:
            if _running:
                lines = [f"- {v['task'][:80]} ({int(time.time() - v['start'])}s, em {v['cwd']})"
                         for v in _running.values()]
                return "Claude Code tasks running:\n" + "\n".join(lines)
            if _last:
                return (f"No task running. Last task "
                        f"{'succeeded' if _last['ok'] else 'failed'}: {_last['result'][:600]}")
        return "No Claude Code task has run in this session."

    task = str(parameters.get("task") or "").strip()
    if not task:
        return "No task given — ask the user what Claude should do."

    exe = _find_claude(cfg)
    if not exe:
        return ("Claude Code is not installed on this computer (or not found). "
                "Tell the user to install it and log in once in a terminal, "
                "then try again.")

    cwd = _resolve_dir(str(parameters.get("working_dir") or ""), cfg)
    try:
        cwd.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"Could not use the folder {cwd}: {e}"

    with _lock:
        _next_id += 1
        tid = _next_id
        _running[tid] = {"task": task, "cwd": str(cwd), "start": time.time()}
    _log(player, f"SYS: Claude Code iniciou uma tarefa em {cwd}.")
    threading.Thread(target=_worker, daemon=True,
                     args=(tid, exe, task, cwd, cfg,
                           bool(parameters.get("continue_previous")), player)).start()
    return (f"Claude Code started working in the background (folder: {cwd}). "
            "Tell the user briefly that Claude is on it; its result will be "
            "announced automatically when it finishes. Do not wait for it.")
