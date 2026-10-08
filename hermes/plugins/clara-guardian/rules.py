"""Guardian rules. Pure functions so they can be unit-tested without Hermes.

decide(tool_name, args) -> None (allow) | ("block", reason) | ("approve", reason)
Blocks are for things Clara must never do; approvals go to the user's phone.
"""
import os, re, shlex

# Clara runs as her own Linux user ("clara"), in her own home: her own computer.
HOME = "/var/lib/clara"
CLARA = HOME
WORKSPACE = os.path.join(HOME, "workspace")
STATE = "/srv/clara-state"                       # takeover switch: written by the Bridge, read-only to Clara
PROTECTED = [os.path.join(HOME, "hermes-home"), STATE, "/home",   # her own config/Guardian, the switch, the user's home
             os.path.join(HOME, ".browser-profile"),                 # persistent Chrome logins
             os.path.join(HOME, ".agent-browser", "auth"), os.path.join(HOME, ".agent-browser", ".encryption-key")]
FREE_WRITE = [HOME + "/", "/tmp/"]               # her own files: no approval needed (protected paths are checked first)

def _cmd_rules():
    r = lambda p: re.compile(p, re.I)
    return [
        (r(r"(^|[;&|`(]\s*|\bthen\s+|\bdo\s+)(sudo|su|doas|pkexec|run0)\b"), "run a command as administrator (sudo)"),
        (r(r"\b(apt|apt-get|aptitude|dpkg|snap|flatpak|dnf|yum|pacman|zypper)\b.*\b(install|remove|purge|upgrade|dist-upgrade|-i|--install)\b"), "install or remove system software"),
        (r(r"\b(pip3?|uv\s+pip|pipx|npm|pnpm|yarn|cargo|gem|go)\s+(install|i|add|uninstall|remove)\b"), "install or remove a software package"),
        (r(r"\b(curl|wget)\b[^|;&]*\s(-o|-O|--output)\b"), "download a file from the internet"),
        (r(r"\b(rm|rmdir|shred|unlink|trash|trash-put|gio\s+trash)\b"), "delete files"),
        (r(r"\bfind\b.*\s-delete\b"), "delete files"),
        (r(r"\b(mv)\b"), "move or rename files"),
        (r(r"\b(sendmail|mail|mailx|mutt|msmtp|neomutt|swaks)\b"), "send an email"),
        (r(r"\b(ssh|scp|sftp|rsync)\b.*[@:]"), "connect to or copy to another computer"),
        (r(r"\bgit\s+(push|remote\s+add)\b"), "publish code to a remote repository"),
        (r(r"\b(systemctl|service)\s+(start|stop|restart|enable|disable|mask)\b"), "change a system service"),
        (r(r"\bcrontab\b"), "change your system's scheduled tasks"),
        (r(r"\b(shutdown|reboot|poweroff|halt|systemctl\s+(suspend|hibernate))\b"), "shut down or restart the computer"),
        (r(r"\b(kill|pkill|killall|xkill)\b"), "stop running programs"),
        (r(r"\b(chmod|chown|chgrp|setfacl)\b"), "change file permissions"),
        (r(r"\b(nmcli|iptables|nft|ufw)\b"), "change network or firewall settings"),
        (r(r"\bdocker\s+(run|rm|rmi|stop|kill|exec|system\s+prune|volume\s+rm)\b"), "manage Docker containers"),
    ]
CMD_RULES = _cmd_rules()
PY_RULES = [
    (re.compile(r"\b(smtplib|imaplib|yagmail)\b"), "send or read email from code"),
    (re.compile(r"\b(os\.remove|os\.unlink|os\.rmdir|shutil\.rmtree|Path\([^)]*\)\.unlink|\.unlink\(|send2trash)"), "delete files from code"),
    (re.compile(r"\b(subprocess|os\.system|os\.popen|pexpect|pty\.spawn)\b"), "run shell commands from code"),
    (re.compile(r"\b(requests|httpx|urllib\.request|aiohttp)\b.*\.(post|put|patch|delete)\b", re.S), "send data to a website from code"),
    (re.compile(r"\b(paramiko|fabric|ftplib)\b"), "connect to another computer from code"),
]

def _norm(p):
    return os.path.realpath(os.path.expanduser(str(p or "")))

def _in(path, roots):
    p = _norm(path)
    return any(p == _norm(r).rstrip("/") or p.startswith(_norm(r).rstrip("/") + "/") for r in roots)

def _mentions_protected(text):
    t = str(text or "")
    return any(p in t or p.replace(HOME, "~") in t for p in PROTECTED)

INFRA = re.compile(r"llama-server|llama\.cpp|hermes|uvicorn|app:app|clara|searxng|bonsai|laya", re.I)
KILLERS = re.compile(r"\b(kill|pkill|killall|xkill|docker\s+(stop|kill|rm|restart))\b", re.I)


def _proc_cmdline(pid):
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace")
    except (OSError, ValueError):
        return ""


def _kills_infra(cmd):
    """True if a kill-style command targets Clara's own model, agent, Bridge, or search (by PID or by name)."""
    if not KILLERS.search(cmd):
        return False
    if INFRA.search(cmd):
        return True
    for pid in re.findall(r"(?<![\w/.-])(\d{2,7})(?![\w/.-])", cmd):
        if INFRA.search(_proc_cmdline(pid)):
            return True
    return False


VAULT_BYPASS = re.compile(r"agent-browser|\.agent-browser", re.I)
VAULT_BLOCK = "Clara's browser and password vault can only be used through her browser tools, never directly."


# Her browser is browser_use. Starting another Chrome from the terminal (2026-10-07: a headless Chrome with a remote
# debugging port, to "restart the browser" mid sign-up) can't fix it, and a debug port would let scripts read pages.
SIDE_BROWSER = re.compile(r"(\b|/)(google-chrome|chrome|chromium(-browser)?|chromedriver|playwright|puppeteer)\b|--remote-debugging|--headless", re.I)
SIDE_BROWSER_BLOCK = ("Don't start, restart or debug a browser yourself: your browser is browser_use, and it reopens on its own. "
                      "If browser_use keeps failing, stop and tell the user what you see.")


# Human checks are for humans: never script around them, ask the user to take over instead.
CAPTCHA = re.compile(r"captcha|recaptcha|hcaptcha|turnstile|cf-chl|g-recaptcha|i'?m not a robot|arkose|funcaptcha", re.I)
CAPTCHA_BLOCK = ("Don't try to get around a CAPTCHA or human check. Call ask_user_for_browser_help with what you need "
                 "(e.g. 'There's a CAPTCHA on the sign-in page'); the user takes over from their phone and hands it back.")


def decide(tool_name, args):
    args = args or {}
    if tool_name == "terminal":
        cmd = str(args.get("command", ""))
        if _mentions_protected(cmd):
            return ("block", "Clara may not touch her own configuration, Guardian, or the Bridge.")
        if VAULT_BYPASS.search(cmd):
            return ("block", VAULT_BLOCK)
        if SIDE_BROWSER.search(cmd):
            return ("block", SIDE_BROWSER_BLOCK)
        if _kills_infra(cmd):
            return ("block", "Clara may not stop her own model, agent, Bridge, or search service; that would take Clara offline.")
        for rx, what in CMD_RULES:
            if rx.search(cmd):
                if what in ("delete files", "move or rename files") and _only_workspace_paths(cmd):
                    continue
                return ("approve", f"Clara wants to {what}: {cmd[:300]}")
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = []
        read_only = {"pwd", "ls", "cat", "head", "tail", "wc", "stat", "file", "du", "df", "whoami", "date"}
        if not tokens or tokens[0] not in read_only or any(c in cmd for c in (";", "|", "&", ">", "<", "$", "`", "\n")):
            return ("approve", "Clara wants to execute a command that can run code or change external state: " + cmd[:300])
        return None
    if tool_name in ("write_file", "patch"):
        path = args.get("path") or args.get("file_path") or ""
        if _in(path, PROTECTED):
            return ("block", "Clara may not modify her own configuration, Guardian, or the Bridge.")
        if path and not _in(path, FREE_WRITE):
            return ("approve", f"Clara wants to change a file outside her workspace: {path}")
        return None
    if tool_name == "execute_code":
        code = str(args.get("code", ""))
        if _mentions_protected(code):
            return ("block", "Clara may not touch her own configuration, Guardian, or the Bridge.")
        if VAULT_BYPASS.search(code):
            return ("block", VAULT_BLOCK)
        if SIDE_BROWSER.search(code):
            return ("block", SIDE_BROWSER_BLOCK)
        for rx, what in PY_RULES:
            if rx.search(code):
                return ("approve", f"Clara wants to {what}.")
        return ("approve", "Clara wants to execute code; its external effects require approval.")
    # Page JavaScript can read what's typed into fields, including passwords the vault filled in.
    if tool_name in ("browser_console", "browser_cdp", "execute_code", "terminal") and CAPTCHA.search(
            str(args.get("expression") or args.get("code") or args.get("command") or args.get("params") or "")):
        return ("block", CAPTCHA_BLOCK)
    if tool_name == "browser_console" and str(args.get("expression") or "").strip():
        return ("block", "Use browser_use; arbitrary page scripts bypass browser control and field protections.")
    if tool_name == "browser_cdp":
        return ("block", "Use browser_use; direct DevTools access bypasses browser control and field protections.")
    if tool_name == "browser_type" and re.search(r"\b(?:\d[ -]?){13,19}\b", str(args.get("text", ""))):
        return ("block", "Clara never types card numbers. Use the payment vault instead.")
    # sign_in needs no Guardian prompt: the phone itself asks (fingerprint/PIN) before releasing a login.
    if tool_name.startswith("browser") and tool_name not in ("browser_use", "browser_snapshot", "browser_vision", "browser_console", "browser_cdp"):
        return ("block", "Use browser_use so target, approval and takeover checks cover every browser action.")
    if tool_name == "skill_manage" and _mentions_protected(args):
        return ("block", "Clara may not touch her own configuration, Guardian, or the Bridge.")
    return None

def _only_workspace_paths(cmd):
    """True if a delete/move stays inside Clara's own home or /tmp: every absolute path is there, nothing climbs out
    with '..' or '~' tricks, and relative paths are only allowed after a cd into her home (or with the default cwd, her workspace)."""
    if any(c in cmd for c in ("$", "`")):
        return False
    try:
        parts = shlex.split(cmd.replace("&&", " ; ").replace("||", " ; ").replace(";", " ; ").replace("|", " ; "))
    except ValueError:
        return False
    cwd_ok = True                       # Hermes runs commands in her workspace by default
    for i, tok in enumerate(parts):
        if tok == "cd" and i + 1 < len(parts):
            cwd_ok = _in(parts[i + 1], FREE_WRITE)
        if ".." in tok.split("/") or tok.startswith("~"):
            return False
        if tok.startswith("/") and not _in(tok, FREE_WRITE):
            return False
        if "*" in tok and not tok.startswith("/") and not cwd_ok:
            return False
    return cwd_ok
