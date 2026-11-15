"""codic.config — locate the .codic root, load codic.toml with defaults.

Root model: this package lives inside the clone (the `.codic` directory).
ROOT is the clone directory; REPO is its parent, the user's repository.
FLEET_ROOT env overrides ROOT for tests.
"""
from __future__ import annotations

import copy
import os
import shlex
import tomllib
from pathlib import Path

ROLES = ("orchestrator", "architect", "implementer", "reviewer", "approver", "supervisor")

# Every [agents.<role>] table, built-in or custom, is merged over this template
# at load: declaring a new role is one table, not a restatement of every key
# (issue #4). prefix defaults to the role name.
ROLE_DEFAULTS = {"count": 1, "agent": "", "model": "", "args": [], "skill_budget": 1500}
STATE_DIRS = ("ready", "doing", "review", "reviewed", "gpu", "blocked", "done")

# Budgets are law (SPEC 4.2): not configurable per repo. Only the token
# estimate divisor is tunable for non-English repos.
BUDGET_LAW = 2048
BUDGET_CENSUS = 1024
BUDGET_BOARD = 8192
BUDGET_DISPATCH = 512

DEFAULTS: dict = {
    "codic": {
        "state_dir": "state",
        "scenarios_path": "",          # empty -> <state_dir>/scenarios; may point outside the repo
        "chars_per_token": 4,
    },
    "harness": {
        "backend": "herdr",            # herdr | tmux | none
        "launch_mode": "pane",         # pane | tab | window (alias of workspace)
        "split_direction": "right",    # right | down, pane mode only
        "tmux_session": "codic",
        "herdr_session": "",           # empty -> inherited session
    },
    "coding_agent": {
        "default": "omp",
    },
    "watchdog": {
        "after_secs": 1800,              # 30 min: wake the watcher if no report landed
        "wake": "",                      # who the watchdog wakes; empty -> orchestrator slot
    },
    "llm": {
        "model": "",                   # global default model; per-role overrides win
        "env": {},                     # extra env vars for launched agent processes
    },
    "coding_agents": {
        # Known launchers. `launch` is the executable, `model_flag` how the
        # model reaches it ("" = model is not passed on the command line),
        # `herdr_kind` the recognized agent kind in herdr ("" = no recognition,
        # the command is run as a plain pane command instead).
        "omp":       {"launch": "omp",       "model_flag": "--model", "herdr_kind": "omp"},
        "claude":    {"launch": "claude",    "model_flag": "--model", "herdr_kind": "claude"},
        "codex":     {"launch": "codex",     "model_flag": "-m",      "herdr_kind": "codex"},
        "opencode":  {"launch": "opencode",  "model_flag": "-m",      "herdr_kind": "opencode"},
        "gemini":    {"launch": "gemini",    "model_flag": "-m",      "herdr_kind": "gemini"},
        "qwen":      {"launch": "qwen",      "model_flag": "-m",      "herdr_kind": "qwen"},
    },
    # One table per agent role: count of concurrent slots, which coding agent,
    # which model, extra native args ({model} placeholder is substituted),
    # name prefix for slots, and the role skill budget in tokens.
    "review": {"cross_family": False},
    "agents": {
        "orchestrator": {"count": 1, "agent": "", "model": "", "args": [], "prefix": "orchestrator", "skill_budget": 1500},
        "architect":    {"count": 1, "agent": "", "model": "", "args": [], "prefix": "arch",         "skill_budget": 1500},
        "implementer":  {"count": 3, "agent": "", "model": "", "args": [], "prefix": "impl",         "skill_budget": 1500},
        "reviewer":     {"count": 1, "agent": "", "model": "", "args": [], "prefix": "rev",          "skill_budget": 1500},
        "approver":     {"count": 1, "agent": "", "model": "", "args": [], "prefix": "appr",         "skill_budget": 1500},
        "supervisor":   {"count": 1, "agent": "", "model": "", "args": [], "prefix": "sup",          "skill_budget": 1500},
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Codic:
    """Resolved paths + config for one codic installation."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else Path(os.environ.get("FLEET_ROOT") or
                                                 Path(__file__).resolve().parents[2])
        self.repo = self.root.parent
        self.config_path = self.root / "codic.toml"
        data = {}
        if self.config_path.exists():
            with open(self.config_path, "rb") as f:
                data = tomllib.load(f)
        self.cfg = _merge(DEFAULTS, data)
        for role, rc in list(self.cfg["agents"].items()):
            unknown = set(rc) - set(ROLE_DEFAULTS) - {"prefix"}
            if unknown:
                raise SystemExit(f"codic.toml [agents.{role}]: unknown key(s) "
                                 f"{', '.join(sorted(unknown))} "
                                 f"(known: prefix, {', '.join(ROLE_DEFAULTS)})")
            self.cfg["agents"][role] = {**copy.deepcopy(ROLE_DEFAULTS), "prefix": role, **rc}
        st = self.cfg["codic"]["state_dir"]
        self.state = (self.root / st) if not Path(st).is_absolute() else Path(st)
        sp = self.cfg["codic"]["scenarios_path"]
        if sp:
            self.scenarios = Path(sp) if Path(sp).is_absolute() else (self.root / sp)
        else:
            self.scenarios = self.state / "scenarios"
        self.queue = self.state / "queue"
        self.law_path = self.state / "STATE.md"
        self.ledger_path = self.state / "NOTES.md"
        self.board_path = self.queue / "BOARD.md"
        self.roster_path = self.state / "roster.json"
        self.gates_dir = self.state / "gates"
        self.pins_path = self.gates_dir / "pins.toml"
        self.skills_dir = self.state / "skills"
        self.evidence_dir = self.state / "evidence"
        self.dispatch_dir = self.state / "dispatch"
        self.runs_dir = self.state / "runs"
        self.watches_dir = self.state / "watches"
        self.reports_dir = self.state / "reports"
        self.resources_dir = self.state / "resources"
        self.chain_dir = self.state / ".chain"
        self.templates = self.root / "templates"

    @property
    def initialized(self) -> bool:
        return self.law_path.exists() and self.queue.exists()

    # -- role helpers -------------------------------------------------------
    def role_cfg(self, role: str) -> dict:
        if role not in self.cfg["agents"]:
            raise SystemExit(f"unknown agent role '{role}' (known: {', '.join(sorted(self.cfg['agents']))})")
        rc = self.cfg["agents"][role]
        agent = rc["agent"] or self.cfg["coding_agent"]["default"]
        model = rc["model"] or self.cfg["llm"]["model"]
        return {"count": int(rc["count"]), "agent": agent, "model": model,
                "args": list(rc["args"]), "prefix": rc["prefix"],
                "skill_budget": int(rc["skill_budget"])}

    def launcher(self, agent: str) -> dict:
        ca = self.cfg["coding_agents"]
        if agent not in ca:
            raise SystemExit(f"unknown coding agent '{agent}' — add a [coding_agents.{agent}] table "
                             f"to codic.toml with launch/model_flag/herdr_kind")
        return ca[agent]

    def agent_command(self, role: str) -> list[str]:
        """Compose the launch command for a role: launcher + model flag + args."""
        rc = self.role_cfg(role)
        ca = self.launcher(rc["agent"])
        cmd = shlex.split(ca["launch"])
        if rc["model"] and ca["model_flag"]:
            cmd += [ca["model_flag"], rc["model"]]
        for a in rc["args"]:
            cmd.append(a.replace("{model}", rc["model"]))
        return cmd

    def tokens(self, text: str) -> int:
        cpt = int(self.cfg["codic"]["chars_per_token"]) or 4
        return -(-len(text) // cpt)  # ceil

    def launch_mode(self) -> str:
        m = str(self.cfg["harness"]["launch_mode"]).lower()
        if m == "window":
            m = "workspace"
        if m not in ("pane", "tab", "workspace"):
            raise SystemExit(f"harness.launch_mode must be pane|tab|window, found '{m}'")
        return m

    def backend_name(self) -> str:
        b = str(self.cfg["harness"]["backend"]).lower()
        if b not in ("herdr", "tmux", "none"):
            raise SystemExit(f"harness.backend must be herdr|tmux|none, found '{b}'")
        return b
