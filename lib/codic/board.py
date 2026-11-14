"""codic.board — regenerate BOARD.md (L1) and the Census section of STATE.md.

Rules (SPEC 5.7): parse every ticket or fail naming the file; refuse on a
ticket in an unknown directory; enforce budgets; write via tmp+rename.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import state as S
from . import ticket as T
from .config import BUDGET_BOARD, BUDGET_CENSUS, STATE_DIRS

STATE_ORDER = ("doing", "gpu", "review", "reviewed", "ready", "blocked", "done")


def _age_days(path: Path) -> int:
    mtime = path.stat().st_mtime
    return max(0, int((datetime.now(timezone.utc).timestamp() - mtime) // 86400))


def build_board(f, tickets: list[dict]) -> str:
    lines = [f"# BOARD — {f.repo.name} fleet",
             f"generated {S.now_utc()} by `codic board`; do not edit", ""]
    by_state: dict[str, list[dict]] = {d: [] for d in STATE_ORDER}
    for t in tickets:
        by_state.setdefault(t["_state"], []).append(t)
    for st in list(STATE_ORDER) + [s for s in by_state if s not in STATE_ORDER]:
        rows = by_state.get(st) or []
        if not rows:
            continue
        lines.append(f"## {st} ({len(rows)})")
        lines.append("")
        lines.append("| ticket | role | worktree | question | age |")
        lines.append("| --- | --- | --- | --- | --- |")
        for t in sorted(rows, key=lambda x: int(x["id"])):
            q = str(t["question"]).replace("|", "\\|")
            lines.append(f"| {t['id']} | {t['role']} | {t.get('worktree', '')} | {q} | {_age_days(Path(t['_path']))}d |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _critical_path(tickets: list[dict]) -> list[str]:
    """One line per active (doing/gpu/review) ticket, with its unmet blockers."""
    by_id = {t["id"]: t for t in tickets}
    active = [t for t in tickets if t["_state"] in ("doing", "gpu", "review")]
    active.sort(key=lambda t: (t["_state"] != "doing", -_age_days(Path(t["_path"]))))
    out = []
    for t in active[:8]:
        blockers = [b for b in t.get("blocked-by", [])
                    if by_id.get(str(b), {}).get("_state") not in ("done", None)
                    or str(b).startswith("resource:")]
        extra = f" blocked-by: {','.join(map(str, blockers))}" if blockers else ""
        out.append(f"- {t['id']} [{t['_state']}] {t['role']}: {t['title']}{extra}")
    return out


def build_census(f, tickets: list[dict], roster: dict, backend) -> str:
    counts = {d: 0 for d in STATE_DIRS}
    for t in tickets:
        counts[t["_state"]] = counts.get(t["_state"], 0) + 1
    lines = []
    lines.append(f"generated {S.now_utc()} by `codic board`")
    lines.append("")
    lines.append("| " + " | ".join(STATE_DIRS) + " |")
    lines.append("| " + " | ".join("---" for _ in STATE_DIRS) + " |")
    lines.append("| " + " | ".join(str(counts[d]) for d in STATE_DIRS) + " |")
    lines.append("")
    pins = S.pins_load(f)
    results = S.gate_results(f)
    if pins or results:
        lines.append("gates:")
        for name in sorted(set(pins) | set(results)):
            pinned = "pinned" if name in pins else "UNPINNED"
            r = results.get(name)
            verdict = "unrun"
            if r:
                verdict = ("PASS" if r.get("pass") else "FAIL") + \
                          ("" if r.get("sha_ok", True) else " (hash mismatch!)") + \
                          (", provisional" if r.get("provisional") else "")
            lines.append(f"- {name}: {pinned}, {verdict}")
        lines.append("")
    cp = _critical_path(tickets)
    if cp:
        lines.append("critical path:")
        lines += cp
        lines.append("")
    res = S.resource_state(f)
    if res:
        lines.append("resources:")
        for name, r in res.items():
            lines.append(f"- {name}: open, held by {r['holder']}")
        for name in _declared_resources(f):
            if name not in res:
                lines.append(f"- {name}: closed")
        lines.append("")
    lines.append("roster:")
    if roster:
        live = {}
        if backend is not None:
            try:
                live = backend.list_agents()
            except Exception:
                live = {}
        for name in sorted(roster):
            r = roster[name]
            st = live.get(name, {}).get("state", "absent")
            lines.append(f"- {name} ({r.get('role', '?')}, {r.get('agent', '?')}): {st}")
    else:
        lines.append("- (empty; `codic launch <role>`)")
    wakes = _wake_registrations(f)
    if wakes:
        lines.append("")
        lines.append("wake registrations (running detached jobs):")
        for job, name in wakes.items():
            lines.append(f"- {job} -> {name}")
    return "\n".join(lines).rstrip() + "\n"


def _declared_resources(f) -> set[str]:
    out = set()
    for t_dir in f.queue.iterdir() if f.queue.exists() else []:
        if not t_dir.is_dir():
            continue
        for p in t_dir.glob("*.md"):
            try:
                t = T.load(p)
                r = str(t.get("resource", ""))
                if r:
                    out.add(r)
            except T.TicketError:
                pass
    return out


def _wake_registrations(f) -> dict:
    out = {}
    if f.runs_dir.exists():
        for w in sorted(f.runs_dir.glob("*.wake")):
            if (f.runs_dir / (w.stem + ".result")).exists():
                continue
            try:
                out[w.stem] = __import__("json").loads(w.read_text())["wake"]
            except Exception:
                out[w.stem] = "?"
    return out


def run_board(f, backend=None, quiet: bool = False) -> list[str]:
    """Regenerate both artifacts. Returns budget report lines; raises SystemExit
    on parse failures, unknown directories, or budget violations."""
    ok, why = S.chain_verify(f, f.ledger_path)
    if not ok:
        raise SystemExit(f"codic board: refusing to regenerate, ledger chain broken: {why}")
    tickets, errors = T.all_tickets(f.queue)
    if errors:
        raise SystemExit("codic board: unparseable tickets:\n  " +
                         "\n  ".join(f"{p}: {e}" for p, e in errors))
    for d in (f.queue.iterdir() if f.queue.exists() else []):
        if d.is_dir() and d.name not in STATE_DIRS and d.name not in ("..", "."):
            stray = list(d.glob("*.md"))
            if stray and d.name not in ("scenarios", "gates"):
                raise SystemExit(f"codic board: ticket files in unknown directory {d}")
    board = build_board(f, tickets)
    n_board = f.tokens(board)
    if n_board > BUDGET_BOARD:
        raise SystemExit(f"codic board: BOARD.md is {n_board} tokens, budget {BUDGET_BOARD}. "
                         "Archive done tickets or split the fleet.")
    S.atomic_write(f.board_path, board)
    census = build_census(f, tickets, S.roster_load(f), backend)
    n_census = f.tokens(census)
    if n_census > BUDGET_CENSUS:
        raise SystemExit(f"codic board: Census is {n_census} tokens, budget {BUDGET_CENSUS}. "
                         "Compress the roster or archive finished work.")
    S.set_census(f, census)
    S.chain_checkpoint(f, f.ledger_path)
    report = [f"BOARD.md {n_board}/{BUDGET_BOARD} tokens",
              f"Census {n_census}/{BUDGET_CENSUS} tokens",
              f"tickets parsed: {len(tickets)}"]
    if not quiet:
        for line in report:
            print(line)
    return report
