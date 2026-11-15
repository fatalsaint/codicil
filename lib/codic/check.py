"""codic.check — enforce SPEC section 7 invariants I1..I15. Exit nonzero on any."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import board as B
from . import state as S
from . import ticket as T
from .config import BUDGET_BOARD, BUDGET_CENSUS, BUDGET_LAW, STATE_DIRS

PANE_ID_RE = re.compile(r"\bw\d+:[pt]\d+\b")
PID_ADDR_RE = re.compile(r"(--pane[= ]\d|--target\s+\d|--pid[= ]\d|\bpid\s+\d{2,})")


def run_check(f, backend) -> int:
    fails: list[str] = []
    warns: list[str] = []

    def fail(inv, msg):
        fails.append(f"[{inv}] {msg}")

    def warn(inv, msg):
        warns.append(f"[{inv}] {msg}")

    if not f.initialized:
        print("codic check: not initialized — run `codic init` first")
        return 1

    tickets, errors = T.all_tickets(f.queue)

    # I1 budgets
    law = S.law_section_text(f)
    n_law = f.tokens(law)
    if n_law > BUDGET_LAW:
        fail("I1", f"Law is {n_law} tokens, budget {BUDGET_LAW}: compress, move to a skill, or promote to a gate")
    census = S.census_text(f)
    if not census:
        warn("I1", "no Census section yet — run `codic board`")
    elif f.tokens(census) > BUDGET_CENSUS:
        fail("I1", f"Census is {f.tokens(census)} tokens, budget {BUDGET_CENSUS}")
    if f.board_path.exists():
        n_b = f.tokens(f.board_path.read_text())
        if n_b > BUDGET_BOARD:
            fail("I1", f"BOARD.md is {n_b} tokens, budget {BUDGET_BOARD}")
    law_lines = S.law_lines(f)
    if len(law_lines) > 25:
        warn("I1", f"{len(law_lines)} law lines (>25): something is being memorized instead of decided")

    # I2 citations exist
    lids = S.ledger_ids(f)
    for ll in law_lines:
        if ll.get("ok_shape") and ll["cite"] not in lids:
            fail("I2", f"law line cites {ll['cite']} which does not exist in the ledger: {ll['raw'][:80]}")

    # I3 ledger append-only chain
    ok, why = S.chain_verify(f, f.ledger_path)
    if not ok:
        fail("I3", f"ledger chain: {why}")

    # I4 tickets parse, sit in known dirs, fields in schema
    for p, e in errors:
        fail("I4", f"{p}: {e}")
    for d in (f.queue.iterdir() if f.queue.exists() else []):
        if d.is_dir() and d.name not in STATE_DIRS and list(d.glob("*.md")):
            fail("I4", f"ticket files in unknown state directory {d}")
    for t in tickets:
        if t["role"] not in f.cfg["agents"]:
            fail("I4", f"{t['_path']}: role {t['role']!r} is not a configured agent role")

    # I5 frozen gates match pins
    pins = S.pins_load(f)
    for name, pin in sorted(pins.items()):
        gp = Path(pin["path"])
        if not gp.is_absolute():
            gp = f.repo / gp
        if not gp.exists():
            fail("I5", f"gate '{name}' pinned but missing: {gp}")
        elif S.sha256_file(gp) != pin["sha256"]:
            fail("I5", f"gate '{name}' does not match its pin — a frozen gate was edited; "
                       "changing a gate needs a maintainer decision, a new pin, and a ledger entry")

    # I6 no pane-id/pid addressing in scripts or dispatch templates
    scan_roots = [f.dispatch_dir, f.state / "scripts"]
    for root in scan_roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix not in (".md", ".sh", ".py", ".txt", ""):
                continue
            text = p.read_text(errors="replace")
            for rx, label in ((PANE_ID_RE, "pane/tab id"), (PID_ADDR_RE, "pid/pane-id flag")):
                m = rx.search(text)
                if m:
                    fail("I6", f"{p}: addresses an agent by {label} ({m.group(0)!r}); names are the contract (R2)")

    # I7 done tickets carry verdicts (+ window evidence for gpu)
    for t in tickets:
        if t.get("_state") != "done":
            continue
        ev = f.evidence_dir / t["id"]
        if not (ev.exists() and any(ev.glob("verdict*.md"))):
            fail("I7", f"done ticket {t['id']} has no reviewer verdict in evidence/{t['id']}/")
        if str(t.get("resource", "")) == "gpu" and not (ev / "window").is_dir():
            fail("I7", f"done ticket {t['id']} declares resource: gpu but has no evidence/{t['id']}/window/")

    # I8 no holdout predicate in implementer-visible paths
    scenarios = S.scenarios_load(f)
    if scenarios:
        visible = []
        for root in (f.queue, f.dispatch_dir):
            if root.exists():
                visible += [p for p in root.rglob("*.md") if p.name != "BOARD.md"]
        vis = f.skills_dir / "implementer.md"
        if vis.exists():
            visible.append(vis)
        if f.ledger_path.exists():
            visible.append(f.ledger_path)
        texts = {p: p.read_text(errors="replace") for p in visible}
        entries = S.ledger_entries(f) if f.ledger_path.exists() else []
        for sc in scenarios:
            if sc.get("status", "active") == "retired":
                continue
            for pred in sc.get("predicates", []):
                for p, text in texts.items():
                    if pred not in text:
                        continue
                    if p == f.ledger_path:
                        bad = [e for e in entries
                               if pred in "\n".join(e["body"]) + e["title"]
                               and e["ts"] >= sc.get("designated", "0000")]
                        if bad:
                            fail("I8", f"scenario {sc.get('id', p.name)} predicate leaked into ledger "
                                       f"entries {[e['id'] for e in bad]} after designation — retire and rewrite the scenario")
                        else:
                            warn("I8", f"scenario {sc.get('id', p.name)} predicate predates designation in the ledger: "
                                       "mark it retired (5.6)")
                    else:
                        fail("I8", f"scenario {sc.get('id', p.name)} predicate found in implementer-visible path {p} — "
                                   "contamination is terminal: retire and rewrite the scenario")

    # I9 census counts equal directory counts
    if census:
        clines = census.splitlines()
        hdr = None
        for idx, ln in enumerate(clines):
            if ln.strip() == "| " + " | ".join(STATE_DIRS) + " |":
                hdr = idx
                break
        if hdr is not None and hdr + 2 < len(clines):
            nums = [int(x.strip()) for x in clines[hdr + 2].strip().strip("|").split("|")]
            actual = {d: len(list((f.queue / d).glob("*.md"))) if (f.queue / d).exists() else 0
                      for d in STATE_DIRS}
            if len(nums) == len(STATE_DIRS):
                for d, n in zip(STATE_DIRS, nums):
                    if n != actual[d]:
                        fail("I9", f"census says {d}={n}, directory holds {actual[d]} — run `codic board`")
        else:
            warn("I9", "census counts row not found; run `codic board`")

    # I10 roster names resolve; running detached jobs have wake registrations
    roster = S.roster_load(f)
    if backend.interactive:
        live = backend.list_agents()
        for name in sorted(roster):
            if roster[name].get("pinned_absent_ok"):
                continue
            if name not in live:
                warn("I10", f"roster name {name!r} does not resolve in the harness (absent); "
                            "relaunch with `codic launch` or drop it from the roster with `codic forget`")
        if f.runs_dir.exists():
            for w in sorted(f.runs_dir.glob("*.wake")):
                if (f.runs_dir / (w.stem + ".result")).exists():
                    continue
                try:
                    target = json.loads(w.read_text())["wake"]
                except Exception:
                    fail("I10", f"{w}: wake registration unreadable")
                    continue
                if target not in live:
                    fail("I10", f"running job {w.stem} wakes {target!r} which does not resolve — nobody will hear from this job")
        if f.watches_dir.exists():
            for w in sorted(f.watches_dir.glob("*.watch")):
                if (f.watches_dir / (w.stem + ".result")).exists() or \
                   (f.watches_dir / (w.stem + ".cancelled")).exists():
                    continue
                try:
                    wake = json.loads(w.read_text())["wake"]
                except Exception:
                    fail("I10", f"{w}: watchdog registration unreadable")
                    continue
                if wake not in live:
                    fail("I10", f"armed watchdog {w.stem} wakes {wake!r} which does not resolve — it will fire into silence")
    else:
        warn("I10", f"backend '{f.backend_name()}' cannot resolve agent names; roster check skipped")

    # I11 dispatch templates: generated, capped, ticket exists
    if f.dispatch_dir.exists():
        for p in sorted(f.dispatch_dir.glob("*.md")):
            text = p.read_text()
            m = re.search(r"<!-- codic:dispatch v1 ticket=(\S+) -->", text)
            if not m:
                fail("I11", f"{p}: not a generated dispatch (missing marker); dispatches come from `codic dispatch <id>`")
                continue
            if not any(t["id"] == m.group(1) for t in tickets):
                fail("I11", f"{p}: cites ticket {m.group(1)} which does not exist")
            for msg in S.dispatch_check_size(f, text, p.name):
                fail("I11", msg)

    # I12 role skills declared + budgeted; law line shape
    for role, rc in f.cfg["agents"].items():
        sk = f.skills_dir / f"{role}.md"
        if not sk.exists():
            fail("I12", f"role {role!r} has no declared skill set at state/skills/{role}.md")
        else:
            n = f.tokens(sk.read_text())
            if n > int(rc["skill_budget"]):
                fail("I12", f"skills/{role}.md is {n} tokens, budget {rc['skill_budget']}")
    for ll in law_lines:
        if not ll.get("ok_shape"):
            fail("I12", f"law line is not '<- [Lxxx] text (owner, YYYY-MM-DD)': {ll['raw'][:80]}")
        elif not S.has_counterexample(ll["text"]):
            fail("I12", f"law line {ll['cite']} carries no counterexample clause: {ll['raw'][:80]}")

    # I13 in-flight write scopes must not intersect
    def _norm_path(p):
        p = str(p).strip()
        while p.startswith("./"):
            p = p[2:]
        return p.rstrip("/")

    def _scope_hit(a, b):
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")

    inflight = [t for t in tickets if t.get("_state") in ("doing", "review")]
    for i in range(len(inflight)):
        for j in range(i + 1, len(inflight)):
            fa = [_norm_path(x) for x in inflight[i].get("files") or []]
            fb = [_norm_path(x) for x in inflight[j].get("files") or []]
            hit = next(((a, b) for a in fa for b in fb if _scope_hit(a, b)), None)
            if hit:
                fail("I13", f"tickets {inflight[i]['id']} and {inflight[j]['id']} have intersecting "
                            f"write scopes ({hit[0]!r} vs {hit[1]!r}); one writer per path (6.7)")

    # I14 done verdicts pin the exact commit reviewed
    commit_re = re.compile(r"^commit:\s*([0-9a-f]{7,40})\s*$", re.M)
    is_git = (f.repo / ".git").exists()
    for t in tickets:
        if t.get("_state") != "done":
            continue
        ev = f.evidence_dir / t["id"]
        shas = []
        if ev.exists():
            for vp in sorted(ev.glob("verdict*.md")):
                shas += commit_re.findall(vp.read_text(errors="replace"))
        if not shas:
            fail("I14", f"done ticket {t['id']} verdict records no 'commit: <sha>' — "
                        "a verdict must name the exact commit it reviewed (I14)")
        elif is_git:
            for sha in shas:
                r = subprocess.run(["git", "-C", str(f.repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                                   capture_output=True)
                if r.returncode != 0:
                    fail("I14", f"done ticket {t['id']} verdict cites commit {sha} "
                                "which does not exist in the repository")

    # I15 cross-family review, opt-in via [review] cross_family
    if f.cfg["review"]["cross_family"]:
        model_re = re.compile(r"^model:\s*(\S+)\s*$", re.M)

        def _family(m):
            m2 = re.match(r"[a-z]+", m.lower())
            return m2.group(0) if m2 else m.lower()

        for t in tickets:
            if t.get("_state") not in ("review", "reviewed", "done"):
                continue
            ev = f.evidence_dir / t["id"]
            vmodels = []
            verdicts = sorted(ev.glob("verdict*.md")) if ev.exists() else []
            for vp in verdicts:
                vmodels += model_re.findall(vp.read_text(errors="replace"))
            if verdicts and not vmodels:
                warn("I15", f"ticket {t['id']} verdict names no 'model: <model>'; "
                            "cross_family review needs the reviewer model on record")
                continue
            tm = str(t.get("model") or "")
            if vmodels and not tm:
                warn("I15", f"ticket {t['id']} has no dispatched model stamped; "
                            "dispatch --send stamps it from the roster")
                continue
            for vm in vmodels:
                if _family(vm) == _family(tm):
                    fail("I15", f"ticket {t['id']}: reviewer model {vm!r} shares the family of "
                                f"implementer model {tm!r}; cross_family review requires another "
                                "family, or set [review] cross_family = false")

    for w in warns:
        print(f"WARN {w}")
    for x in fails:
        print(f"FAIL {x}")
    print(f"codic check: {len(fails)} fail, {len(warns)} warn")
    return 1 if fails else 0
