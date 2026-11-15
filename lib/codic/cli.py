"""codic.cli — subcommand surface.

Install model: `git clone <codic-repo> .codic && .codic/bin/codic init`.
Every command works from anywhere; paths derive from the clone location.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import board as B
from . import check as C
from . import harness as H
from . import state as S
from . import ticket as T
from .config import Codic, ROLES, STATE_DIRS


# ---------------------------------------------------------------- init ----
def cmd_init(f: Codic, a) -> int:
    if f.initialized and not a.force:
        sys.exit("codic init: already initialized (use --force to re-seed missing files only)")
    f.root.mkdir(parents=True, exist_ok=True)
    for d in ([f.queue / s for s in STATE_DIRS] + [f.gates_dir / "results", f.skills_dir,
              f.evidence_dir, f.dispatch_dir, f.runs_dir, f.watches_dir, f.reports_dir,
              f.resources_dir, f.chain_dir, f.scenarios]):
        d.mkdir(parents=True, exist_ok=True)

    # config
    if not f.config_path.exists():
        tmpl = _tmpl(f, "codic.toml")
        backend = a.backend or _detect_backend()
        tmpl = tmpl.replace('backend = "herdr"', f'backend = "{backend}"')
        if a.agent:
            tmpl = re.sub(r'^default = "omp"', f'default = "{a.agent}"', tmpl, flags=re.M)
        f.config_path.write_text(tmpl)
        print(f"wrote {f.config_path.relative_to(f.root)} (backend: {backend})")
        f = Codic(f.root)  # reload with the written config

    # L0 + ledger
    if not f.law_path.exists():
        state_md = _tmpl(f, "STATE.md.tmpl").replace("{repo}", f.repo.name).replace("{date}", S.today())
        S.atomic_write(f.law_path, state_md)
        print("seeded state/STATE.md (edit ## Law by hand; ## Census is generated)")
    if not f.ledger_path.exists():
        S.atomic_write(f.ledger_path,
                       f"# NOTES — {f.repo.name} codic ledger\n"
                       "Append-only. Entry ids are monotonic and never reused. "
                       "A superseding entry names the id it supersedes.\n")
        S.ledger_append(f, "codic", f"genesis: codic harness initialized in {f.repo.name}",
                        "Clone of the codic harness installed at "
                        f"{f.root.name}/; state tree versioned separately.")
        S.chain_checkpoint(f, f.ledger_path)
        print("seeded state/NOTES.md with entry [L1]")

    # role skills
    for role in ROLES + ("maintainer",):
        dst = f.skills_dir / f"{role}.md"
        if not dst.exists():
            shutil.copyfile(f.templates / "skills" / f"{role}.md", dst)
    print(f"declared role skills in state/skills/ ({len(ROLES) + 1} files)")

    # gates + scenarios
    if not f.pins_path.exists():
        f.pins_path.write_text("# frozen gates (SPEC 5.5): `codic gate pin <script>` freezes a gate\n")
    sc_readme = f.scenarios / "README.md"
    if not sc_readme.exists():
        sc_readme.write_text(_tmpl(f, "scenario-README.md"))

    # state gets its own git history; bulk stays out
    st_ign = f.state / ".gitignore"
    if not st_ign.exists():
        st_ign.write_text("evidence/\nruns/\nwatches/\n*.tmp\nroster.json\n")
    if not (f.state / ".git").exists():
        S.git(f.state, "init", "-q")
        S.git(f.state, "add", "-A")
        S.git(f.state, "-c", "user.name=codic", "-c", "user.email=codic@local",
              "commit", "-qm", "codic genesis")
        print("state/ has its own git history (the ledger's trust depends on it)")

    # outer repo must not track the codic
    gi = f.repo / ".gitignore"
    entry = f"{f.root.name}/"
    cur = gi.read_text() if gi.exists() else ""
    if entry not in cur.splitlines():
        gi.write_text((cur.rstrip() + "\n" if cur.strip() else "") + entry + "\n")
        print(f"added {entry} to {f.repo.name}/.gitignore")

    # wire the repo's agent instructions
    if not a.no_agents_md:
        _wire_agents_md(f)

    rc = 0
    try:
        B.run_board(f, H.get(f))
    except SystemExit as e:
        print(f"board: {e}", file=sys.stderr)
        rc = 1
    rc = C.run_check(f, H.get(f)) or rc
    print("\nnext: edit state/STATE.md ## Law, harvest state/skills/*.md, "
          "then `codic launch orchestrator`.")
    return rc


def _detect_backend() -> str:
    if shutil.which("herdr"):
        return "herdr"
    if shutil.which("tmux"):
        return "tmux"
    return "none"


def _tmpl(f: Codic, name: str) -> str:
    return (f.templates / name).read_text()


def _wire_agents_md(f: Codic) -> None:
    block = _tmpl(f, "AGENTS.snippet.md").replace("{dir}", f.root.name)
    for name in ("AGENTS.md", "CLAUDE.md"):
        p = f.repo / name
        if not p.exists():
            continue
        cur = p.read_text()
        if "<!-- BEGIN codic -->" in cur:
            continue
        p.write_text(cur.rstrip() + "\n\n" + block)
        print(f"wired codic boot rule into {name}")


# ------------------------------------------------------- board/check ----
def cmd_board(f: Codic, a) -> int:
    B.run_board(f, H.get(f))
    return 0


def cmd_check(f: Codic, a) -> int:
    return C.run_check(f, H.get(f))


def cmd_status(f: Codic, a) -> int:
    backend = H.get(f)
    live = backend.list_agents() if backend.available() else {}
    roster = S.roster_load(f)
    print(f"backend: {backend.name}  launch_mode: {f.launch_mode()}")
    print("\nroster:")
    if not roster:
        print("  (empty; `codic launch <role>`)")
    for name in sorted(roster):
        r = roster[name]
        st = live.get(name, {}).get("state", "absent")
        print(f"  {name:<14} {r.get('role', '?'):<12} {r.get('agent', '?'):<10} "
              f"{r.get('model') or '(default model)':<24} {st}")
    res = S.resource_state(f)
    if res:
        print("\nresources:")
        for n, r in res.items():
            print(f"  {n}: open, held by {r['holder']}")
    if f.runs_dir.exists():
        running = [w for w in sorted(f.runs_dir.glob("*.wake"))
                   if not (f.runs_dir / (w.stem + ".result")).exists()]
        if running:
            print("\ndetached jobs running:")
            for w in running:
                j = json.loads(w.read_text())
                print(f"  {w.stem}: wakes {j['wake']} — {j.get('label') or j['cmd']}")
    return 0


# ------------------------------------------------------------ launch ----
def _slot_name(f: Codic, role: str, roster: dict, live: dict) -> str:
    prefix = f.role_cfg(role)["prefix"]
    if prefix == role and role == "orchestrator":
        base = [role]
    else:
        base = [prefix]
    taken = set(roster) | set(live)
    for i in range(1, 64):
        name = base[0] if i == 1 else f"{base[0]}{i}"
        if name not in taken:
            return name
    sys.exit(f"no free slot for role {role}")


def cmd_launch(f: Codic, a) -> int:
    rc = f.role_cfg(a.role)
    backend = H.get(f)
    if not backend.interactive:
        sys.exit(f"backend '{backend.name}' cannot launch agents; set harness.backend in codic.toml")
    roster = S.roster_load(f)
    live = backend.list_agents()
    name = a.name or _slot_name(f, a.role, roster, live)
    H.validate_name(name)
    ca = f.launcher(rc["agent"])
    cmd = f.agent_command(a.role)
    mode = (a.mode or f.launch_mode())
    if mode == "window":
        mode = "workspace"
    cwd = str(Path(a.dir).resolve()) if a.dir else str(f.repo)
    env = {str(k): str(v) for k, v in (f.cfg["llm"].get("env") or {}).items()}
    kind = ca.get("herdr_kind", "")
    # herdr's `agent start` launches the kind's canonical executable itself;
    # args after -- are native args only. Plain-command launches need the exe.
    launch_cmd = cmd[1:] if (kind and backend.name == "herdr") else cmd
    info = backend.start(name, launch_cmd, mode, cwd, kind=kind, env=env)
    roster[name] = {"role": a.role, "agent": rc["agent"], "model": rc["model"],
                    "mode": mode, "target": info["target"], "kind": info["kind"],
                    "started": S.now_utc()}
    S.roster_save(f, roster)
    print(f"launched {name} ({a.role}, {rc['agent']}"
          f"{', ' + rc['model'] if rc['model'] else ''}) as {mode}: {info['target']}")
    B.run_board(f, backend, quiet=True)
    return 0


def cmd_stop(f: Codic, a) -> int:
    roster = S.roster_load(f)
    if a.name not in roster:
        sys.exit(f"{a.name} is not in the roster; `codic forget` only removes stale entries")
    H.get(f).stop(a.name, roster[a.name])
    del roster[a.name]
    S.roster_save(f, roster)
    print(f"stopped and removed {a.name}")
    return 0


def cmd_forget(f: Codic, a) -> int:
    roster = S.roster_load(f)
    if a.name not in roster:
        sys.exit(f"{a.name} is not in the roster")
    del roster[a.name]
    S.roster_save(f, roster)
    print(f"removed {a.name} from the roster (the pane/process itself is untouched)")
    return 0


# ----------------------------------------------------- prompt / read ----
def cmd_prompt(f: Codic, a) -> int:
    H.validate_name(a.name)
    out = H.get(f).prompt(a.name, a.text, wait=not a.no_wait, timeout_ms=a.timeout)
    if out:
        print(out)
    return 0


def cmd_read(f: Codic, a) -> int:
    H.validate_name(a.name)
    print(H.get(f).read(a.name, a.lines))
    return 0


# ----------------------------------------------------------- ledger ----
def cmd_ledger(f: Codic, a) -> int:
    lid = S.ledger_append(f, a.role, a.title, a.body or "", a.supersedes or "")
    print(f"appended [{lid}]")
    return 0


def cmd_law(f: Codic, a) -> int:
    line = S.law_add(f, a.owner, a.cite, a.text, force=a.force)
    print(line)
    print("remember: superseded rulings go to the ledger (SPEC 6.3), nothing stale stays in Law")
    return 0


# ----------------------------------------------------------- tickets ----
def _find_ticket(f: Codic, tid: str) -> Path:
    for d in STATE_DIRS:
        for p in (f.queue / d).glob(f"{tid}-*.md"):
            return p
    sys.exit(f"no ticket {tid} in any state directory")


def cmd_ticket(f: Codic, a) -> int:
    if a.action == "new":
        f.role_cfg(a.role)  # any role configured in codic.toml; raises with the known list
        slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", a.title.lower())).strip("-")[:48]
        path = f.queue / "ready" / f"{a.id}-{slug}.md"
        if path.exists():
            sys.exit(f"{path} already exists")
        fm = {"id": a.id, "title": a.title, "role": a.role, "question": a.question}
        if a.worktree: fm["worktree"] = a.worktree
        if a.engine: fm["engine"] = a.engine
        if a.resource: fm["resource"] = a.resource
        if a.file: fm["files"] = a.file
        if a.accept: fm["acceptance"] = a.accept
        if a.blocked_by: fm["blocked-by"] = [b.strip() for b in a.blocked_by.split(",")]
        if a.scenario: fm["scenarios"] = a.scenario
        body = a.body or "## Contract\n\n<the complete contract: what to change, how it is\n" \
                         "checked, what must not be touched. A worker never needs chat history.>\n"
        S.atomic_write(path, T.render(fm, body))
        print(f"created {path.relative_to(f.root)}")
        B.run_board(f, H.get(f), quiet=True)
        return 0
    if a.action == "move":
        src = _find_ticket(f, a.id)
        dst_dir = f.queue / a.state
        if not dst_dir.exists():
            sys.exit(f"unknown state '{a.state}' (known: {', '.join(STATE_DIRS)})")
        dst = dst_dir / src.name
        src.rename(dst)
        print(f"moved {src.name}: {src.parent.name} -> {a.state}")
        if a.note:
            lid = S.ledger_append(f, "orchestrator", f"ticket {a.id}: {src.parent.name} -> {a.state}", a.note)
            print(f"ledger [{lid}]")
        B.run_board(f, H.get(f), quiet=True)
        return 0
    if a.action == "show":
        p = _find_ticket(f, a.id)
        print(p.read_text())
        return 0
    sys.exit(f"unknown ticket action {a.action}")


# ------------------------------------------------------------- gates ----
def cmd_gate(f: Codic, a) -> int:
    pins = S.pins_load(f)
    if a.action == "pin":
        gp = Path(a.path).resolve()
        if not gp.exists():
            sys.exit(f"{gp} does not exist")
        name = a.name or gp.stem
        pins[name] = {"path": _rel(f, gp), "sha256": S.sha256_file(gp)}
        _write_pins(f, pins)
        lid = S.ledger_append(f, "maintainer", f"gate '{name}' pinned",
                              f"sha256 {pins[name]['sha256']} of {pins[name]['path']}. "
                              "Frozen: never edited to change a threshold.")
        print(f"pinned gate '{name}' ({pins[name]['sha256'][:12]}…), ledger [{lid}]")
        return 0
    if a.action == "check":
        bad = 0
        for name, pin in sorted(pins.items()):
            gp = Path(pin["path"])
            if not gp.is_absolute():
                gp = f.repo / gp
            ok = gp.exists() and S.sha256_file(gp) == pin["sha256"]
            print(f"{name}: {'OK' if ok else 'MISMATCH or missing'}")
            bad += 0 if ok else 1
        return 1 if bad else 0
    if a.action == "run":
        pin = pins.get(a.name)
        if pin is None and not a.provisional:
            sys.exit(f"gate '{a.name}' is not pinned; quoting an unpinned pass is a conformance "
                     "failure (SPEC 5.5). Run `codic gate pin` or pass --provisional.")
        gp = Path(pin["path"]) if pin else Path(a.name)
        if not gp.is_absolute():
            gp = f.repo / gp
        if not gp.exists():
            sys.exit(f"gate script missing: {gp}")
        sha_ok = bool(pin) and S.sha256_file(gp) == pin["sha256"]
        if pin and not sha_ok:
            sys.exit(f"gate '{a.name}' does not match its pin; refusing to run it as a frozen gate")
        r = subprocess.run([str(gp)], cwd=str(f.repo), capture_output=True, text=True, timeout=3600)
        result = {"pass": r.returncode == 0, "rc": r.returncode, "ts": S.now_utc(),
                  "sha_ok": sha_ok, "provisional": pin is None}
        S.atomic_write(f.gates_dir / "results" / f"{a.name}.json", json.dumps(result) + "\n")
        print(("PASS" if result["pass"] else f"FAIL (rc {r.returncode})") +
              ("" if pin else " [provisional: unpinned, never quote this as a pass]"))
        out = (r.stdout + r.stderr).strip()
        if out:
            print(out[-2000:])
        B.run_board(f, H.get(f), quiet=True)
        return 0 if result["pass"] else 1
    sys.exit(f"unknown gate action {a.action}")


def _rel(f: Codic, p: Path) -> str:
    try:
        return str(p.relative_to(f.repo))
    except ValueError:
        return str(p)


def _write_pins(f: Codic, pins: dict) -> None:
    lines = ["# frozen gates (SPEC 5.5): sha256 per gate script; a frozen gate is never\n"
             "# edited to change a threshold — new pin needs a maintainer decision + ledger entry"]
    for name, pin in sorted(pins.items()):
        lines.append(f"\n[{name}]\npath = \"{pin['path']}\"\nsha256 = \"{pin['sha256']}\"")
    S.atomic_write(f.pins_path, "\n".join(lines) + "\n")


# -------------------------------------------------------- scenarios ----
def cmd_scenario(f: Codic, a) -> int:
    if a.action == "new":
        pred = Path(a.predicate_file).read_text() if a.predicate_file else a.predicate + "\n"
        path = f.scenarios / f"{a.id}.md"
        if path.exists():
            sys.exit(f"{path} already exists (contaminated scenarios are retired and rewritten, not edited)")
        path.write_text(
            f"id: {a.id}\ntitle: {a.title}\nstatus: active\ndesignated: {a.designated or S.today()}\n\n"
            f"{a.title}\n\n```predicate\n{pred.rstrip()}\n```\n")
        lid = S.ledger_append(f, "maintainer", f"scenario {a.id} designated",
                              f"predicate lives only in scenarios/{a.id}.md; tickets and dispatches cite the id.")
        print(f"created scenarios/{a.id}.md, ledger [{lid}]")
        return 0
    if a.action == "retire":
        path = f.scenarios / f"{a.id}.md"
        if not path.exists():
            sys.exit(f"{path} does not exist")
        path.write_text(re.sub(r"^status: .*$", "status: retired", path.read_text(), flags=re.M))
        S.ledger_append(f, "maintainer", f"scenario {a.id} retired",
                        a.reason or "contaminated or superseded; rewrite under a new id.")
        print(f"retired {a.id}")
        return 0
    if a.action == "list":
        for sc in S.scenarios_load(f):
            print(f"{sc.get('id', '?'):<6} {sc.get('status', '?'):<8} {sc.get('designated', '?')}  {sc.get('title', '')}")
        return 0
    sys.exit(f"unknown scenario action {a.action}")


# --------------------------------------------------------- dispatch ----
def cmd_dispatch(f: Codic, a) -> int:
    p = _find_ticket(f, a.id)
    t = T.load(p)
    t["_state"] = p.parent.name
    text = S.dispatch_render(f, t, a.delta, a.budget, a.send or "")
    for msg in S.dispatch_check_size(f, text, "dispatch"):
        sys.exit(msg)
    out = f.dispatch_dir / f"{a.id}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.md"
    S.atomic_write(out, text)
    print(text)
    print(f"[saved {out.relative_to(f.root)}]")
    if a.send:
        H.get(f).prompt(a.send, text, wait=False, timeout_ms=0)
        print(f"[dispatched to {a.send}]")
        r = S.roster_load(f).get(a.send)
        if r and r.get("role") == t["role"] and r.get("model"):
            fm, body = T.split(p)
            fm["model"] = r["model"]
            S.atomic_write(p, T.render(fm, body))
            print(f"[stamped model {r['model']} from roster slot {a.send} (I15)]")
        if not a.no_watch:
            wid = _arm_watchdog(f, a.send, f"dispatch ticket {a.id}", 0, "")
            print(f"[watchdog {wid} armed: silent worker wakes the orchestrator "
                  f"in {int(f.cfg['watchdog']['after_secs'])}s; cancel when the report lands]")
    return 0


# ---------------------------------------------------------------- merge ----
def _merge_queue(f: Codic) -> list[dict]:
    tickets, _ = T.all_tickets(f.queue)
    q = [t for t in tickets if t.get("_state") == "reviewed" and str(t.get("worktree") or "")]
    return sorted(q, key=lambda t: int(t["id"]))


def cmd_merge(f: Codic, a) -> int:
    """Serialized landing of reviewed worktrees (SPEC 6.7). Does not move tickets."""
    lock = f.state / "merge.lock"

    def git(args, cwd=None, check=True):
        r = subprocess.run(["git", "-C", str(cwd or f.repo), *args],
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            sys.exit(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:300]}")
        return r

    if a.action == "status":
        print(f"lock: HELD {lock.read_text().strip()}" if lock.exists() else "lock: free")
        q = _merge_queue(f)
        if not q:
            print("queue: empty")
        for t in q:
            print(f"queue: {t['id']} {t['title'][:60]} ({t['worktree']})")
        return 0
    q = _merge_queue(f)
    if not q:
        print("merge queue empty (tickets in reviewed with worktree: enter it)")
        return 0
    if lock.exists():
        holder = lock.read_text().strip()
        pid = int(holder.split()[0]) if holder.split() and holder.split()[0].isdigit() else 0
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if alive and not a.force:
            sys.exit(f"merge lock held (pid {holder}); wait for it or use --force")
        print(f"[replacing {'stale' if not alive else 'forced'} merge lock: {holder}]")
    t = q[0]
    wt = Path(str(t["worktree"]))
    if not wt.is_absolute():
        wt = f.repo / wt
    if not wt.is_dir():
        sys.exit(f"ticket {t['id']}: worktree {wt} does not exist")
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt).stdout.strip()
    if branch == git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip():
        sys.exit(f"ticket {t['id']}: worktree is on the current branch {branch}; nothing to merge")
    if git(["merge-base", "--is-ancestor", branch, "HEAD"], check=False).returncode == 0:
        print(f"ticket {t['id']}: branch {branch} is already merged; "
              "only the approver moves tickets to done (R1)")
        return 0
    S.atomic_write(lock, f"{os.getpid()} ticket {t['id']} {S.now_utc()}\n")
    try:
        m = git(["merge", "--no-ff", "-m", f"ticket {t['id']}: {t['title']}", branch], check=False)
        if m.returncode != 0:
            git(["merge", "--abort"], check=False)
            sys.exit(f"ticket {t['id']}: merge of {branch} conflicts; resolve in {wt}, "
                     f"then run `codic merge next` again\n{m.stdout.strip()[:300]}")
        sha = git(["rev-parse", "--short", "HEAD"]).stdout.strip()
        S.ledger_append(f, "orchestrator", f"merge ticket {t['id']} branch {branch} at {sha}")
        print(f"merged ticket {t['id']}: {branch} -> {sha}; ledger line appended")
    finally:
        lock.unlink(missing_ok=True)
    return 0


# ---------------------------------------------------------------- report ----
def cmd_report(f: Codic, a) -> int:
    """The worker's completion signal: durable report file, watchdog disarm,
    orchestrator wake. A finish without a report is indistinguishable from a
    dead agent, so this is the step the dispatch footer and role skills name."""
    p = _find_ticket(f, a.id)
    t = T.load(p)
    H.validate_name(a.as_agent)
    line = a.line.strip()
    if not line:
        sys.exit("codic report needs a one-line summary")
    wake = (a.wake or str(f.cfg["watchdog"].get("wake") or "")
            or f.role_cfg("orchestrator")["prefix"])
    H.validate_name(wake)
    stamp = S.now_utc()
    f.reports_dir.mkdir(parents=True, exist_ok=True)
    out = f.reports_dir / (f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
                           f"-{t['id']}-{a.status}.md")
    S.atomic_write(out, f"{stamp}  {a.as_agent}  ticket {t['id']}  {a.status}\n{line}\n")
    disarmed = []
    wd = f.watches_dir
    for w in sorted(wd.glob("*.watch")) if wd.exists() else []:
        if (wd / (w.stem + ".cancelled")).exists() or (wd / (w.stem + ".result")).exists():
            continue
        try:
            reg = json.loads(w.read_text())
        except Exception:
            continue
        if reg.get("target") == a.as_agent:
            S.atomic_write(wd / (w.stem + ".cancelled"), stamp + "\n")
            disarmed.append(w.stem)
    backend = H.get(f)
    msg = f"report {out.name}"
    if backend.interactive:
        try:
            backend.prompt(wake, f"{a.as_agent}: ticket {t['id']} {a.status} — {line}",
                           wait=False, timeout_ms=0)
            msg += f", woke {wake}"
        except SystemExit as e:
            msg += f"; wake FAILED ({e}) — report file stands, read it on boot (6.5)"
    else:
        msg += f"; backend '{backend.name}' cannot wake {wake} — report file stands"
    if disarmed:
        msg += ", disarmed " + " ".join(disarmed)
    print(msg)
    return 0


# ----------------------------------------------------- detached runs ----
def _arm_watchdog(f: Codic, target: str, why: str, after: int, wake: str) -> str:
    """Register-then-sleep pattern (6.5): the wake registration exists before
    the timer process does, and the wake target must resolve now."""
    wd = f.watches_dir
    wd.mkdir(parents=True, exist_ok=True)
    backend = H.get(f)
    if not backend.interactive:
        sys.exit("a watchdog must be able to wake someone by name; "
                 f"backend '{backend.name}' cannot")
    H.validate_name(target)
    wake = wake or str(f.cfg["watchdog"].get("wake") or "") or f.role_cfg("orchestrator")["prefix"]
    H.validate_name(wake)
    if not backend.resolve(wake):
        sys.exit(f"watchdog wake target {wake!r} does not resolve in the harness; "
                 "refusing to arm a watch nobody will hear from (I10)")
    if not backend.resolve(target):
        sys.exit(f"{target!r} does not resolve in the harness; nothing to watch")
    after = after or int(f.cfg["watchdog"]["after_secs"])
    wid = f"wd{int(time.time())}"
    reg = {"target": target, "wake": wake, "why": why or "", "after": after, "set_at": S.now_utc()}
    S.atomic_write(wd / f"{wid}.watch", json.dumps(reg) + "\n")
    codic = f.root / "bin" / "codic"
    wrapper = (f"sleep {after}; {H._shq(str(codic))} _watchfire {wid} "
               f">>{H._shq(str(wd / (wid + '.log')))} 2>&1")
    subprocess.Popen(["setsid", "sh", "-c", wrapper], start_new_session=True,
                     cwd=str(f.repo), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wid


def cmd_watch(f: Codic, a) -> int:
    wd = f.watches_dir
    if a.action == "arm":
        if not a.id_or_agent:
            sys.exit("codic watch arm needs an agent name")
        wid = _arm_watchdog(f, a.id_or_agent, a.why or "", a.after, a.wake or "")
        print(f"watchdog {wid}: wakes the watcher in {a.after or int(f.cfg['watchdog']['after_secs'])}s "
              f"if {a.id_or_agent} has not reported")
        return 0
    if a.action == "cancel":
        if not (wd / f"{a.id_or_agent}.watch").exists():
            sys.exit(f"no watchdog {a.id_or_agent}")
        S.atomic_write(wd / f"{a.id_or_agent}.cancelled", S.now_utc() + "\n")
        print(f"watchdog {a.id_or_agent} cancelled (the report landed)")
        return 0
    if a.action == "list":
        for w in sorted(wd.glob("*.watch")) if wd.exists() else []:
            reg = json.loads(w.read_text())
            state = ("cancelled" if (wd / (w.stem + ".cancelled")).exists()
                     else "fired" if (wd / (w.stem + ".result")).exists() else "armed")
            print(f"{w.stem:<12} {state:<9} watch {reg['target']:<14} wake {reg['wake']:<14} "
                  f"after {reg['after']}s ({reg['set_at']}) {reg['why']}")
        return 0
    sys.exit(f"unknown watch action {a.action}")


def cmd_watchfire(f: Codic, a) -> int:
    wf = f.watches_dir / f"{a.id}.watch"
    if not wf.exists() or (f.watches_dir / (a.id + ".cancelled")).exists():
        return 0
    reg = json.loads(wf.read_text())
    state = "unknown"
    try:
        state = H.get(f).list_agents().get(reg["target"], {}).get("state", "absent")
    except SystemExit:
        pass
    S.atomic_write(f.watches_dir / f"{a.id}.result",
                   json.dumps({"fired": S.now_utc(), "target_state": state}) + "\n")
    line = (f"watchdog {a.id}: {reg['target']} state={state} {reg['after']}s after "
            f"{reg['why'] or 'dispatch'} — no report landed; check it")
    try:
        H.get(f).prompt(reg["wake"], line, wait=False, timeout_ms=0)
        print(f"woke {reg['wake']}: {line}")
    except SystemExit as e:
        print(f"wake failed ({e}); result file stands — the watcher reads it on boot (6.5)")
    return 0


def cmd_run(f: Codic, a) -> int:
    backend = H.get(f)
    if not backend.interactive:
        sys.exit("a detached job must have a resolvable wake target (SPEC 6.5); "
                 "backend 'none' cannot wake anyone")
    H.validate_name(a.wake)
    if not backend.resolve(a.wake):
        sys.exit(f"wake target {a.wake!r} does not resolve in the harness; refusing to launch "
                 "a job nobody will hear from (I10)")
    job = f"j{int(time.time())}"
    reg = {"wake": a.wake, "cmd": " ".join(a.cmd_args), "label": a.label or "", "started": S.now_utc()}
    S.atomic_write(f.runs_dir / f"{job}.wake", json.dumps(reg) + "\n")
    log = f.runs_dir / f"{job}.log"
    exitf = f.runs_dir / f"{job}.exit"
    codic = f.root / "bin" / "codic"
    wrapper = (f"{' '.join(H._shq(x) for x in a.cmd_args)} >{H._shq(str(log))} 2>&1; "
               f"echo $? >{H._shq(str(exitf))}; {H._shq(str(codic))} _wakeup {job} "
               f">>{H._shq(str(f.runs_dir / (job + '.wake.log')))} 2>&1")
    subprocess.Popen(["setsid", "sh", "-c", wrapper], start_new_session=True,
                     cwd=str(f.repo), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"job {job} launched detached; wakes {a.wake}; log {log.relative_to(f.root)}")
    return 0


def cmd_wakeup(f: Codic, a) -> int:
    wf = f.runs_dir / f"{a.job}.wake"
    if not wf.exists():
        sys.exit(f"no wake registration for {a.job}")
    reg = json.loads(wf.read_text())
    code = 127
    exitf = f.runs_dir / f"{a.job}.exit"
    if exitf.exists():
        code = int(exitf.read_text().strip() or 127)
    result = {"exit": code, "finished": S.now_utc(), "wake": reg["wake"]}
    S.atomic_write(f.runs_dir / f"{a.job}.result", json.dumps(result) + "\n")
    line = (f"job {a.job} {reg.get('label') or reg['cmd'][:60]} finished exit={code}; "
            f"evidence {f.runs_dir.name}/{a.job}.log")
    try:
        H.get(f).prompt(reg["wake"], line, wait=False, timeout_ms=0)
        print(f"woke {reg['wake']}: {line}")
    except SystemExit as e:
        print(f"wake failed ({e}); result file stands — the agent reads it on boot (6.5)")
    return 0


# ------------------------------------------------------------ config ----
def cmd_config(f: Codic, a) -> int:
    print(json.dumps(f.cfg, indent=1))
    print(f"\nroot:   {f.root}\nrepo:   {f.repo}\nstate:  {f.state}\nscenarios: {f.scenarios}")
    return 0


# ---------------------------------------------------------- parser ----
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="codic", description="codic harness: state layer for agent-built software")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="scaffold state, config, gitignore wiring")
    s.add_argument("--backend", choices=("herdr", "tmux", "none"))
    s.add_argument("--agent", help="default coding agent (omp, claude, codex, opencode, ...)")
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-agents-md", action="store_true", help="do not touch AGENTS.md/CLAUDE.md")

    sub.add_parser("board", help="regenerate BOARD.md + Census")
    sub.add_parser("check", help="enforce invariants I1-I12")
    sub.add_parser("status", help="roster, resources, jobs")

    s = sub.add_parser("launch", help="start a named agent per config")
    s.add_argument("role")
    s.add_argument("--name")
    s.add_argument("--mode", choices=("pane", "tab", "window", "workspace"))
    s.add_argument("--dir", help="working directory (default: repo root)")

    s = sub.add_parser("stop", help="close an agent codic launched")
    s.add_argument("name")
    s = sub.add_parser("forget", help="drop a stale roster entry")
    s.add_argument("name")

    s = sub.add_parser("prompt", help="dispatch to a named agent (names only, R2)")
    s.add_argument("name")
    s.add_argument("text")
    s.add_argument("--no-wait", action="store_true")
    s.add_argument("--timeout", type=int, default=120000)

    s = sub.add_parser("read", help="read a named agent's recent output")
    s.add_argument("name")
    s.add_argument("--lines", type=int, default=120)

    s = sub.add_parser("ledger", help="append a ledger entry")
    s.add_argument("--role", default="orchestrator")
    s.add_argument("--title", required=True)
    s.add_argument("--body", default="")
    s.add_argument("--supersedes")

    s = sub.add_parser("law", help="append a law line with shape enforcement")
    s.add_argument("action", choices=("add",))
    s.add_argument("--owner", required=True, choices=("maintainer", "orchestrator"))
    s.add_argument("--cite", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("ticket", help="ticket lifecycle helpers")
    s.add_argument("action", choices=("new", "move", "show"))
    s.add_argument("id", nargs="?", default="")
    s.add_argument("state", nargs="?", default="")
    s.add_argument("--role")
    s.add_argument("--title")
    s.add_argument("--question")
    s.add_argument("--worktree")
    s.add_argument("--engine")
    s.add_argument("--resource")
    s.add_argument("--file", action="append")
    s.add_argument("--accept", action="append")
    s.add_argument("--blocked-by")
    s.add_argument("--scenario", action="append")
    s.add_argument("--body")
    s.add_argument("--note")

    s = sub.add_parser("gate", help="frozen gates: pin, check, run")
    s.add_argument("action", choices=("pin", "check", "run"))
    s.add_argument("path_or_name", nargs="?", default="")
    s.add_argument("--name")
    s.add_argument("--provisional", action="store_true")

    s = sub.add_parser("scenario", help="holdout scenarios")
    s.add_argument("action", choices=("new", "retire", "list"))
    s.add_argument("id", nargs="?", default="")
    s.add_argument("--title")
    s.add_argument("--predicate")
    s.add_argument("--predicate-file")
    s.add_argument("--designated")
    s.add_argument("--reason")

    s = sub.add_parser("dispatch", help="generate a dispatch from ticket frontmatter (6.6)")
    s.add_argument("id")
    s.add_argument("--delta", default="first dispatch")
    s.add_argument("--budget", default="default model, no extra slots")
    s.add_argument("--send", help="also prompt this agent name")
    s.add_argument("--no-watch", action="store_true", help="do not arm the silence watchdog")

    s = sub.add_parser("report", help="worker completion report: wakes the orchestrator, disarms the watchdog")
    s.add_argument("id", help="ticket id")
    s.add_argument("status", choices=("done", "blocked"))
    s.add_argument("line", help="one-line summary, with the evidence path")
    s.add_argument("--as", dest="as_agent", required=True, metavar="AGENT", help="your slot name")
    s.add_argument("--wake", default="", help="who to wake (default: [watchdog] wake or the orchestrator)")

    s = sub.add_parser("merge", help="serialized landing of reviewed worktrees (SPEC 6.7)")
    s.add_argument("action", choices=("next", "status"))
    s.add_argument("--force", action="store_true", help="take over a held merge lock")

    s = sub.add_parser("run", help="detached job with wake registration (6.5)")
    s.add_argument("--wake", required=True)
    s.add_argument("--label")
    s.add_argument("cmd_args", nargs=argparse.REMAINDER)

    s = sub.add_parser("watch", help="watchdog: wake the watcher if an agent goes silent")
    s.add_argument("action", choices=("arm", "cancel", "list"))
    s.add_argument("id_or_agent", nargs="?", default="")
    s.add_argument("--after", type=int, default=0, help="seconds (default: [watchdog] after_secs)")
    s.add_argument("--why", help="what you are waiting on (ticket id, question)")
    s.add_argument("--wake", help="who to wake (default: [watchdog] wake or the orchestrator)")

    s = sub.add_parser("_watchfire", help=argparse.SUPPRESS)
    s.add_argument("id")

    s = sub.add_parser("_wakeup", help=argparse.SUPPRESS)
    s.add_argument("job")

    sub.add_parser("config", help="print resolved config")
    return p


def cmd_gate_dispatch(f: Codic, a) -> int:
    a.name = a.path_or_name if a.action == "run" else a.name
    a.path = a.path_or_name if a.action == "pin" else ""
    return cmd_gate(f, a)


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    f = Codic()
    if args.cmd == "ticket" and args.action in ("move", "show") and not args.id:
        sys.exit(f"codic ticket {args.action} needs a ticket id")
    if args.cmd == "scenario" and args.action == "new" and not (args.title and (args.predicate or args.predicate_file)):
        sys.exit("codic scenario new needs --title and --predicate or --predicate-file")
    if args.cmd == "ticket" and args.action == "new":
        missing = [x for x in ("id", "role", "title", "question") if not getattr(args, x)]
        if missing:
            sys.exit(f"codic ticket new missing: {', '.join('--' + m.replace('_', '-') for m in missing)}")
    if args.cmd == "run":
        args.cmd_args = [c for c in args.cmd_args if c != "--"]
        if not args.cmd_args:
            sys.exit("codic run needs a command after --")
    handlers = {
        "init": cmd_init, "board": cmd_board, "check": cmd_check, "status": cmd_status,
        "launch": cmd_launch, "stop": cmd_stop, "forget": cmd_forget,
        "prompt": cmd_prompt, "read": cmd_read, "ledger": cmd_ledger, "law": cmd_law,
        "ticket": cmd_ticket, "gate": cmd_gate_dispatch, "scenario": cmd_scenario,
        "dispatch": cmd_dispatch, "run": cmd_run, "watch": cmd_watch, "report": cmd_report,
        "merge": cmd_merge,
        "_watchfire": cmd_watchfire, "_wakeup": cmd_wakeup, "config": cmd_config,
    }
    return handlers[args.cmd](f, args)
