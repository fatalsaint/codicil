"""codic.harness — named, promptable sessions behind one interface.

HERDR FIRST: the herdr backend is the reference implementation (SPEC 9.2
"harness addressing: Herdr pane names"). tmux is a degraded second (no agent
lifecycle states). `none` keeps board/check/tickets usable with no harness.

Every backend addresses agents by NAME only (R2). Pane ids are internal
bookkeeping, never an addressing surface.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def validate_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise SystemExit(
            f"'{name}' is not a valid agent name. Names match [a-z][a-z0-9_-]{{0,31}} and are "
            "the only legal addressing (R2/I6): never pane ids like w1:p1, never pids.")
    return name


def _run(argv: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _json_out(cp: subprocess.CompletedProcess):
    try:
        return json.loads(cp.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


class Backend:
    name = "base"
    interactive = False

    def __init__(self, f):
        self.f = f

    def available(self) -> bool:
        return False

    def list_agents(self) -> dict:
        return {}

    def resolve(self, name: str) -> bool:
        return name in self.list_agents()

    def start(self, name: str, cmd: list[str], mode: str, cwd: str, kind: str = "", env: dict | None = None) -> dict:
        raise SystemExit(f"backend '{self.name}' cannot launch agents; set harness.backend to herdr or tmux")

    def prompt(self, name: str, text: str, wait: bool, timeout_ms: int) -> str:
        raise SystemExit(f"backend '{self.name}' cannot prompt agents")

    def read(self, name: str, lines: int) -> str:
        raise SystemExit(f"backend '{self.name}' cannot read agents")

    def stop(self, name: str, roster_entry: dict) -> None:
        raise SystemExit(f"backend '{self.name}' cannot stop agents")


class HerdrBackend(Backend):
    name = "herdr"
    interactive = True

    def available(self) -> bool:
        return shutil.which("herdr") is not None

    def _prefix(self) -> list[str]:
        argv = ["herdr"]
        sess = self.f.cfg["harness"].get("herdr_session") or ""
        if sess:
            argv += ["--session", sess]
        return argv

    def _call(self, argv: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        cp = _run(self._prefix() + argv, timeout=timeout)
        if cp.returncode != 0:
            raise SystemExit(f"{' '.join(argv)} failed: {(cp.stderr or cp.stdout).strip()}")
        return cp

    def list_agents(self) -> dict:
        cp = _run(self._prefix() + ["agent", "list"], timeout=30)
        if cp.returncode != 0:
            return {}
        data = _json_out(cp)
        out = {}
        agents = data.get("result", {}).get("agents", data) if isinstance(data, dict) else data
        if isinstance(agents, list):
            for a in agents:
                if isinstance(a, dict) and "name" in a:
                    out[a["name"]] = {"state": a.get("state", a.get("status", "unknown")),
                                      "pane": a.get("pane_id", "")}
        return out

    def _create_pane(self, mode: str, cwd: str, label: str, env: dict | None = None) -> str:
        """Create the host pane per launch_mode; return its pane id."""
        envargs = []
        for k, v in (env or {}).items():
            envargs += ["--env", f"{k}={v}"]
        if mode == "pane":
            direction = self.f.cfg["harness"].get("split_direction", "right")
            argv = ["pane", "split", "--current", "--direction", direction,
                    "--cwd", cwd, "--no-focus"] + envargs
            cp = self._call(argv)
            data = _json_out(cp) or {}
            return data.get("result", {}).get("pane", {}).get("pane_id", "")
        if mode == "tab":
            cp = self._call(["tab", "create", "--cwd", cwd, "--label", label, "--no-focus"] + envargs)
            data = _json_out(cp) or {}
            return data.get("result", {}).get("root_pane", {}).get("pane_id", "")
        # workspace
        cp = self._call(["workspace", "create", "--cwd", cwd, "--label", label, "--no-focus"] + envargs)
        data = _json_out(cp) or {}
        return data.get("result", {}).get("root_pane", {}).get("pane_id", "")

    def start(self, name: str, cmd: list[str], mode: str, cwd: str, kind: str = "", env: dict | None = None) -> dict:
        validate_name(name)
        if self.resolve(name):
            raise SystemExit(f"agent name {name!r} is already live; pick another slot")
        pane = self._create_pane(mode, cwd, name, env)
        if not pane:
            raise SystemExit("herdr returned no pane id; is the server running? (herdr status)")
        if kind:
            self._call(["agent", "start", name, "--kind", kind, "--pane", pane,
                        "--timeout", "60000", "--", *cmd], timeout=120)
        else:
            # unrecognized kind: run it as a plain command; no lifecycle states
            self._call(["pane", "run", pane, " ".join(_shq(x) for x in cmd)])
        return {"target": pane, "kind": kind or "(plain command)"}

    def prompt(self, name: str, text: str, wait: bool, timeout_ms: int) -> str:
        validate_name(name)
        argv = ["agent", "prompt", name, text]
        if wait:
            argv += ["--wait", "--timeout", str(timeout_ms)]
        cp = self._call(argv, timeout=max(30, timeout_ms // 1000 + 30))
        return cp.stdout.strip()

    def read(self, name: str, lines: int) -> str:
        validate_name(name)
        cp = self._call(["agent", "read", name, "--source", "recent-unwrapped", "--lines", str(lines)])
        data = _json_out(cp)
        if isinstance(data, dict):
            return data.get("result", {}).get("text", cp.stdout.strip())
        return cp.stdout.strip()

    def stop(self, name: str, roster_entry: dict) -> None:
        pane = roster_entry.get("target", "")
        if pane:
            self._call(["pane", "close", pane])


class TmuxBackend(Backend):
    name = "tmux"
    interactive = True

    def available(self) -> bool:
        return shutil.which("tmux") is not None

    @property
    def session(self) -> str:
        return self.f.cfg["harness"].get("tmux_session", "codic")

    def _ensure_session(self) -> None:
        if _run(["tmux", "has-session", "-t", f"={self.session}"]).returncode != 0:
            _run(["tmux", "new-session", "-d", "-s", self.session, "-c", str(self.f.repo)])

    def list_agents(self) -> dict:
        cp = _run(["tmux", "list-panes", "-a", "-F",
                   "#{pane_id}\t#{@codic_name}\t#{@codic_state}\t#{pane_current_command}"])
        out = {}
        for line in cp.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1]:
                out[parts[1]] = {"state": parts[2] or "unknown", "pane": parts[0]}
        return out

    def start(self, name: str, cmd: list[str], mode: str, cwd: str, kind: str = "", env: dict | None = None) -> dict:
        validate_name(name)
        if self.resolve(name):
            raise SystemExit(f"agent name {name!r} is already live; pick another slot")
        self._ensure_session()
        if env:
            cmd = ["env"] + [f"{k}={v}" for k, v in env.items()] + cmd
        shell_cmd = " ".join(_shq(x) for x in cmd)
        if mode == "pane":
            argv = ["tmux", "split-window", "-h" if self.f.cfg["harness"].get("split_direction", "right") == "right" else "-v",
                    "-d", "-P", "-F", "#{pane_id}", "-c", cwd, "-t", self.session, shell_cmd]
        elif mode == "tab":
            argv = ["tmux", "new-window", "-d", "-P", "-F", "#{pane_id}", "-c", cwd, "-n", name, shell_cmd]
        else:  # workspace
            argv = ["tmux", "new-window", "-d", "-P", "-F", "#{pane_id}", "-c", cwd, "-n", f"{self.session}:{name}", shell_cmd]
        cp = _run(argv)
        if cp.returncode != 0:
            raise SystemExit(f"tmux launch failed: {cp.stderr.strip()}")
        pane = cp.stdout.strip().splitlines()[-1]
        _run(["tmux", "set-option", "-p", "-t", pane, "@codic_name", name])
        _run(["tmux", "set-option", "-p", "-t", pane, "@codic_state", "working"])
        return {"target": pane, "kind": "tmux"}

    def _target(self, name: str) -> str:
        agents = self.list_agents()
        if name not in agents:
            raise SystemExit(f"no tmux pane is running agent {name!r}")
        return agents[name]["pane"]

    def prompt(self, name: str, text: str, wait: bool, timeout_ms: int) -> str:
        validate_name(name)
        pane = self._target(name)
        _run(["tmux", "set-option", "-p", "-t", pane, "@codic_state", "working"])
        _run(["tmux", "send-keys", "-t", pane, "-l", text])
        _run(["tmux", "send-keys", "-t", pane, "Enter"])
        return f"sent to {name} (tmux has no lifecycle states; read with `codic read {name}`)"

    def read(self, name: str, lines: int) -> str:
        pane = self._target(name)
        cp = _run(["tmux", "capture-pane", "-p", "-S", f"-{lines}", "-t", pane])
        return cp.stdout

    def stop(self, name: str, roster_entry: dict) -> None:
        pane = roster_entry.get("target") or self._target(name)
        _run(["tmux", "kill-pane", "-t", pane])


class NoneBackend(Backend):
    name = "none"

    def available(self) -> bool:
        return True


def get(f) -> Backend:
    b = f.backend_name()
    if b == "herdr":
        be = HerdrBackend(f)
        if not be.available():
            print("WARN herdr not in PATH; falling back to the 'none' backend for this command")
            return NoneBackend(f)
        return be
    if b == "tmux":
        be = TmuxBackend(f)
        if not be.available():
            print("WARN tmux not in PATH; falling back to the 'none' backend for this command")
            return NoneBackend(f)
        return be
    return NoneBackend(f)


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'" if any(c in s for c in " \t\"'\\$`;&|<>()") else s
