#!/usr/bin/env python3
"""End-to-end smoke test for the codic CLI. No network, no herdr needed.

Creates a throwaway repo, clones the harness into .codic, inits with
backend=none, exercises the ticket/board/check/ledger/gate/scenario/dispatch
loop, then breaks invariants one by one and proves `codic check` goes red.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FAILURES = []


def codic(repo: Path, *args: str, expect: int = 0, cwd: Path | None = None):
    r = subprocess.run([sys.executable, str(repo / ".codic" / "bin" / "codic"), *args],
                       cwd=str(cwd or repo), capture_output=True, text=True)
    tag = " ".join(args[:2])
    if r.returncode != expect:
        FAILURES.append(f"`codic {' '.join(args)}` exit {r.returncode} != {expect}\n"
                        f"stdout: {r.stdout[-800:]}\nstderr: {r.stderr[-800:]}")
        print(f"  ✗ {tag} (exit {r.returncode})")
    else:
        print(f"  ✓ {tag}")
    return r


def expect_contains(hay: str, needle: str, what: str):
    if needle in hay:
        print(f"  ✓ {what}")
    else:
        FAILURES.append(f"{what}: {needle!r} not in output:\n{hay[-800:]}")
        print(f"  ✗ {what}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="codic-smoke-"))
    try:
        repo = tmp / "myapp"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
        (repo / "AGENTS.md").write_text("# myapp\n\nBuild: make\n")
        (repo / "src").mkdir()
        (repo / "src" / "main.py").write_text("print('hi')\n")

        print("[1] install: clone to .codic + init")
        shutil.copytree(HERE, repo / ".codic")
        codic(repo, "init", "--backend", "none")
        expect_contains((repo / ".gitignore").read_text(), ".codic/", "outer .gitignore ignores .codic/")
        expect_contains((repo / "AGENTS.md").read_text(), "<!-- BEGIN codic -->", "AGENTS.md wired")
        st = repo / ".codic" / "state"
        for p in ("STATE.md", "NOTES.md", "queue/BOARD.md", "skills/implementer.md",
                  "gates/pins.toml", "scenarios/README.md", ".chain/NOTES.md.sha"):
            if (st / p).exists():
                print(f"  ✓ seeded {p}")
            else:
                FAILURES.append(f"missing seeded file: {p}")
                print(f"  ✗ missing {p}")
        r = subprocess.run(["git", "-C", str(st), "log", "--oneline"], capture_output=True, text=True)
        expect_contains(r.stdout, "codic genesis", "state/ has its own git history")
        r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True, check=True)
        if ".codic" not in r.stdout:
            print("  ✓ outer git status clean of .codic")
        else:
            FAILURES.append(f"outer git tracks .codic: {r.stdout}")

        print("[2] green path: ticket -> board -> check")
        codic(repo, "ticket", "new", "7", "--role", "implementer",
              "--title", "add retry to client",
              "--question", "Does the client retry 503s with backoff?",
              "--file", "src/client.py", "--accept", "pytest tests/test_retry.py")
        codic(repo, "ticket", "move", "7", "doing")
        codic(repo, "board")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "check green on fresh tree")
        expect_contains((st / "queue" / "BOARD.md").read_text(), "Does the client retry 503s", "board row rendered")
        expect_contains((st / "STATE.md").read_text(), "doing", "census rendered in STATE.md")

        print("[3] ledger + law")
        r = codic(repo, "ledger", "--title", "window policy v1", "--body", "marker-based admission.")
        expect_contains(r.stdout, "[L2]", "ledger entry L2")
        r = codic(repo, "law", "add", "--owner", "orchestrator", "--cite", "L2",
                  "--text", "Admission is marker presence, never a free-memory floor: "
                            "a floor once admitted a build that hard-killed the box.",
                  expect=0)
        r = codic(repo, "law", "add", "--owner", "orchestrator", "--cite", "L2",
                  "--text", "Always be nice to reviewers.", expect=1)
        expect_contains(r.stderr + r.stdout, "counterexample", "law add rejects a clause-less line")
        codic(repo, "check")

        print("[4] gates: pin, run, tamper")
        gate = repo / "scripts" / "smoke-gate.sh"
        gate.parent.mkdir(exist_ok=True)
        gate.write_text("#!/bin/sh\nexit 0\n")
        gate.chmod(0o755)
        codic(repo, "gate", "pin", str(gate))
        codic(repo, "gate", "run", "smoke-gate")
        gate.write_text("#!/bin/sh\nexit 0\n# quietly relaxed\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout, "does not match its pin", "I5 catches an edited frozen gate")
        gate.write_text("#!/bin/sh\nexit 0\n")
        codic(repo, "check")

        print("[5] scenarios + I8 leak detection")
        codic(repo, "scenario", "new", "S1", "--title", "retry honors backoff",
              "--predicate", "output_tokens == 128 AND backoff_seconds >= 1.0 AND attempts == 3")
        codic(repo, "check")
        leak = st / "queue" / "doing" / "7-add-retry-to-client.md"
        orig = leak.read_text()
        leak.write_text(orig + "\nNOTE: must satisfy output_tokens == 128 AND backoff_seconds >= 1.0 AND attempts == 3\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout, "predicate found in implementer-visible path", "I8 catches a ticket leak")
        leak.write_text(orig)
        codic(repo, "check")

        print("[6] dispatch: generated, capped, ticket-cited")
        r = codic(repo, "dispatch", "7", "--delta", "first dispatch", "--budget", "default model")
        expect_contains(r.stdout, "codic:dispatch v1 ticket=7", "dispatch marker")
        expect_contains(r.stdout, "Ticket: 7", "dispatch cites ticket")
        expect_contains(r.stdout, "codic report 7 done|blocked", "handoff names the report command")
        dsp = sorted((st / "dispatch").glob("*.md"))[-1]
        dsp.write_text(dsp.read_text() + "\nw1:p1 do the work\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout, "pane/tab id", "I6 catches pane-id addressing")
        dsp.unlink()
        codic(repo, "check")

        print("[6b] report: durable file, watchdog disarm, wake gap stated")
        (st / "watches" / "wdtest.watch").write_text(
            json.dumps({"target": "impl1", "wake": "orchestrator", "why": "dispatch ticket 7",
                        "after": 1800, "set_at": "2026-11-14T00:00:00Z"}) + "\n")
        r = codic(repo, "report", "7", "done", "all acceptance green; evidence state/evidence/7/run.md",
                  "--as", "impl1")
        expect_contains(r.stdout, "disarmed wdtest", "report disarms the armed watchdog")
        assert (st / "watches" / "wdtest.cancelled").exists(), "watch registration cancelled"
        reps = sorted((st / "reports").glob("*-7-done.md"))
        assert reps, "durable report file written"
        expect_contains(reps[-1].read_text(), "impl1  ticket 7  done", "report cites agent, ticket, status")
        expect_contains(r.stdout, "cannot wake orchestrator", "none backend states the wake gap")
        r = codic(repo, "report", "7", "done", "x", "--as", "not a name!", expect=1)
        assert r.returncode == 1, "report rejects an unnameable agent"
        codic(repo, "check")

        print("[7] invariant breakage: schema, chain, census drift")
        bad = st / "queue" / "ready" / "9-bad-ticket.md"
        bad.write_text("---\nid: 9\ntitle: x\nrole: implementer\nquestion: q\nbogus_key: 1\n---\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout, "unknown frontmatter key", "I4 catches off-schema keys")
        bad.unlink()
        st2 = st / "NOTES.md"
        backup = st2.read_text()
        st2.write_text(backup.replace("# NOTES", "# NOTES TAMPERED", 1))
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout, "ledger chain", "I3 catches a rewritten ledger")
        st2.write_text(backup)
        (st / "queue" / "ready" / "8-sneaky.md").write_text(
            "---\nid: 8\ntitle: sneaky\nrole: reviewer\nquestion: q?\n---\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout, "census says", "I9 catches census/directory drift")
        (st / "queue" / "ready" / "8-sneaky.md").unlink()
        codic(repo, "board")
        codic(repo, "check")

        print("[8] addressing rules (R2/I6)")
        r = codic(repo, "prompt", "w1:p1", "hello", expect=1)
        expect_contains(r.stderr + r.stdout, "not a valid agent name", "pane-id target rejected")
        r = codic(repo, "run", "--wake", "nobody-here", "--", "true", expect=1)
        expect_contains(r.stderr + r.stdout, "backend 'none' cannot wake", "detached job refused without harness")
        r = codic(repo, "watch", "arm", "impl1", "--why", "ticket 7", expect=1)
        expect_contains(r.stderr + r.stdout, "watchdog must be able to wake", "watchdog refused without harness")
        r = codic(repo, "watch", "list")
        if r.returncode == 0:
            print("  ✓ watch list renders")

        print("[9] status + config")
        r = codic(repo, "status")
        expect_contains(r.stdout, "backend: none", "status renders")
        r = codic(repo, "config")
        expect_contains(r.stdout, '"launch_mode"', "config renders")

        print("[10] frontmatter: inline lists parse; empty lists round-trip (issue #2)")
        sys.path.insert(0, str(HERE / "lib"))
        from codic import ticket as T
        fm = T.parse_frontmatter("---\nid: 1\ntitle: t\nrole: implementer\n"
                                 "question: q\nblocked-by: [52, 53]\n---\n")
        if fm.get("blocked-by") != ["52", "53"]:
            FAILURES.append(f"inline list parsed as {fm.get('blocked-by')!r}")
        else:
            print("  ✓ inline list parses")
        fm = T.parse_frontmatter("---\nid: 1\ntitle: t\nrole: implementer\n"
                                 "question: q\nblocked-by: []\n---\n")
        if fm.get("blocked-by") != []:
            FAILURES.append(f"empty inline list parsed as {fm.get('blocked-by')!r}")
        else:
            print("  ✓ empty inline list parses to []")
        fm = {"id": "1", "title": "t", "role": "implementer", "question": "q",
              "files": [], "acceptance": ["pytest -q"], "blocked-by": ["52"]}
        rt = T.parse_frontmatter(T.render(fm))
        if not (rt["files"] == [] and rt["acceptance"] == ["pytest -q"]
                and rt["blocked-by"] == ["52"]):
            FAILURES.append(f"render->parse round trip broken: {rt}")
        else:
            print("  ✓ render -> parse round-trips empty and inline lists")
        mig = st / "queue" / "ready" / "12-migrated.md"
        mig.write_text("---\nid: 12\ntitle: migrated ticket\nrole: implementer\n"
                       "question: does an empty list survive I4?\nfiles: []\n"
                       "blocked-by: []\nacceptance:\n  - true\n---\n")
        codic(repo, "board")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "I4 accepts migrated empty-list tickets")
        mig.unlink()
        codic(repo, "board")

        print("[11] custom roles inherit defaults (issue #4)")
        cfg = repo / ".codic" / "codic.toml"
        cfg.write_text(cfg.read_text() + '\n[agents.scout]\ncount = 1\nprefix = "scout"\n')
        (st / "skills" / "scout.md").write_text("# scout skill\n\nRecon only; report in one line.\n")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "minimal custom role passes check with inherited defaults")
        codic(repo, "ticket", "new", "13", "--role", "scout", "--title", "recon deps",
              "--question", "Which deps are unmaintained?", "--accept", "true")
        r = codic(repo, "launch", "scout", expect=1)
        expect_contains(r.stdout + r.stderr, "cannot launch agents",
                        "custom role resolves through role_cfg")
        r = codic(repo, "launch", "nosuch", expect=1)
        expect_contains(r.stdout + r.stderr, "unknown agent role",
                        "unconfigured role gets a named diagnostic")
        (st / "queue" / "ready" / "13-recon-deps.md").unlink()
        codic(repo, "board")
        cfg.write_text(cfg.read_text() + "\n[agents.gossip]\nskill_budgt = 999\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "unknown key(s) skill_budgt",
                        "typo'd role key is named, not silently defaulted")

        print("[12] write scopes, pinned commits, cross-family review, merge queue")
        cfg.write_text(cfg.read_text().replace("\n[agents.gossip]\nskill_budgt = 999\n", "")
                       .replace("cross_family = false", "cross_family = true"))

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=smoke", "-c", "user.email=smoke@local",
                                   "-C", str(repo), *args],
                                  capture_output=True, text=True, check=True)

        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "seed")
        sha = git("rev-parse", "HEAD").stdout.strip()

        # I13: two in-flight tickets sharing a write scope
        codic(repo, "ticket", "new", "14", "--role", "implementer", "--title", "touch core",
              "--question", "Q14?", "--file", "src/core.py", "--accept", "true")
        codic(repo, "ticket", "new", "15", "--role", "implementer", "--title", "also core",
              "--question", "Q15?", "--file", "src/core.py", "--accept", "true")
        codic(repo, "ticket", "move", "14", "doing")
        codic(repo, "ticket", "move", "15", "doing")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I13]", "overlapping write scopes fail")
        codic(repo, "ticket", "move", "15", "ready")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "disjoint write scopes pass")

        # I14: done verdict must pin the exact commit reviewed
        codic(repo, "ticket", "move", "14", "done")
        ev14 = st / "evidence" / "14"
        ev14.mkdir(parents=True)
        (ev14 / "verdict.md").write_text("accept\n\nfindings: none.\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I14]", "verdict without a commit pin fails")
        (ev14 / "verdict.md").write_text("accept\n\ncommit: deadbeef1234567\n\nfindings: none.\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I14]", "verdict citing a nonexistent commit fails")

        # I15: cross-family review, opt-in
        t14 = next((st / "queue" / "done").glob("14-*.md"))
        t14.write_text(t14.read_text().replace("role: implementer",
                                               "role: implementer\nmodel: claude-opus-4-1"))
        (ev14 / "verdict.md").write_text(f"accept\n\ncommit: {sha}\nmodel: claude-sonnet-4-5\n\n"
                                         "findings: none.\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I15]", "same-family verdict fails when cross_family is on")
        (ev14 / "verdict.md").write_text(f"accept\n\ncommit: {sha}\nmodel: gpt-5.2\n\nfindings: none.\n")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "real commit + cross-family verdict passes")

        # merge queue: reviewed worktree lands under lock, ledger line written
        git("worktree", "add", "-q", "-b", "ticket-16", "work/wt/16")
        subprocess.run(["git", "-c", "user.name=smoke", "-c", "user.email=smoke@local",
                        "-C", str(repo / "work" / "wt" / "16"),
                        "commit", "-q", "--allow-empty", "-m", "ticket 16 work"], check=True)
        codic(repo, "ticket", "new", "16", "--role", "implementer", "--title", "land me",
              "--question", "Q16?", "--accept", "true")
        t16 = next((st / "queue" / "ready").glob("16-*.md"))
        t16.write_text(t16.read_text().replace("role: implementer",
                                               "role: implementer\nworktree: work/wt/16"))
        codic(repo, "ticket", "move", "16", "reviewed")
        r = codic(repo, "merge", "status")
        expect_contains(r.stdout, "queue: 16", "merge status lists the reviewed worktree")
        (st / "merge.lock").write_text(f"{os.getpid()} ticket 99 fake\n")
        r = codic(repo, "merge", "next", expect=1)
        expect_contains(r.stdout + r.stderr, "merge lock held", "a live lock blocks landing")
        (st / "merge.lock").unlink()
        r = codic(repo, "merge", "next")
        expect_contains(r.stdout, "merged ticket 16", "merge next lands the queue head")
        expect_contains((st / "NOTES.md").read_text(), "merge ticket 16 branch ticket-16",
                        "the merge writes its ledger line")
        expect_contains(" ".join(p.name for p in (st / "queue" / "reviewed").glob("16-*.md")),
                        "16-", "merging did not move the ticket (approver's job)")
        expect_contains(" ".join(p.name for p in (st / "queue" / "done").glob("16-*.md")) or "none",
                        "none", "the ticket did not reach done on its own")
        r = codic(repo, "merge", "next")
        expect_contains(r.stdout, "already merged", "a landed branch is not merged twice")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "fleet green after the merge")

        print("[13] red fixture per invariant: I1, I2, I7, I10, I11, I12")
        # (I3, I4, I5, I6, I8, I9 fire in sections above; I13-I15 in [12].
        #  Rule: every invariant gets a state that must make check go red.)
        state_md = st / "STATE.md"
        orig_state = state_md.read_text()

        # I1: law over token budget
        state_md.write_text(orig_state.replace(
            "\n## Census", "\n" + "filler law padding. " * 1200 + "\n## Census"))
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I1]", "law over budget fails")
        state_md.write_text(orig_state)

        # I2: law line citing a ledger id that does not exist
        state_md.write_text(orig_state.replace(
            "\n## Census",
            "\n- [L999] phantom ruling unless the repo is archived (maintainer, 2026-11-14)\n"
            "## Census"))
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I2]", "law citing a dead ledger id fails")
        state_md.write_text(orig_state)

        # I7: done ticket without a reviewer verdict (I14 rides along)
        codic(repo, "ticket", "new", "17", "--role", "implementer", "--title", "no verdict",
              "--question", "Q17?", "--accept", "true")
        codic(repo, "ticket", "move", "17", "done")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I7]", "done without a verdict fails")
        expect_contains(r.stdout + r.stderr, "[I14]", "the missing verdict trips I14 too")
        ev17 = st / "evidence" / "17"
        ev17.mkdir(parents=True)
        (ev17 / "verdict.md").write_text(f"accept\n\ncommit: {sha}\nmodel: gpt-5.2\n\nnone.\n")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "verdict with pinned commit closes the ticket")

        # I11: hand-written dispatch, then dispatch citing a dead ticket
        (st / "dispatch" / "999-handwritten.md").write_text("do the thing\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I11]", "hand-written dispatch fails the marker rule")
        (st / "dispatch" / "999-handwritten.md").write_text(
            "<!-- codic:dispatch v1 ticket=999 -->\n\nTicket: 999\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "cites ticket 999 which does not exist",
                        "dispatch citing a dead ticket fails")
        (st / "dispatch" / "999-handwritten.md").unlink()

        # I12: role skill over its declared budget
        cfg.write_text(cfg.read_text() + "skill_budget = 5\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "[I12]", "skill over budget fails")
        cfg.write_text(cfg.read_text().replace("skill_budget = 5", "skill_budget = 1500"))

        # I10: running job waking a name that does not resolve (needs an
        # interactive backend; the none backend skips the roster check by design)
        if shutil.which("tmux"):
            cfg.write_text(cfg.read_text().replace('backend = "none"', 'backend = "tmux"'))
            (st / "runs").mkdir(exist_ok=True)
            (st / "runs" / "j1.wake").write_text('{"wake": "ghostslot"}')
            r = codic(repo, "check", expect=1)
            expect_contains(r.stdout + r.stderr, "[I10]",
                            "a job waking an unresolved name fails")
            (st / "runs" / "j1.wake").unlink()
            cfg.write_text(cfg.read_text().replace('backend = "tmux"', 'backend = "none"'))
        else:
            print("  - tmux absent; I10 red fixture skipped (roster check is backend-gated)")

        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "every fixture repaired; fleet green")

        print("[14] issue regressions: #8 #9 #10 #11")
        libdir = str(repo / ".codic" / "lib")

        # #8: verdict citing a commit real only in the codic install tree
        harness_sha = subprocess.run(["git", "-C", str(repo / ".codic"), "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()
        codic(repo, "ticket", "new", "18", "--role", "implementer", "--title", "harness work",
              "--question", "Q18?", "--accept", "true")
        codic(repo, "ticket", "move", "18", "done")
        ev18 = st / "evidence" / "18"
        ev18.mkdir(parents=True)
        (ev18 / "verdict.md").write_text(f"accept\n\ncommit: {harness_sha}\nmodel: gpt-5.2\n\nnone.\n")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "install-tree commit resolves (issue #8)")
        (ev18 / "verdict.md").write_text("accept\n\ncommit: aabbccddeeff00\nmodel: gpt-5.2\n\nnone.\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "exists in neither", "fabricated sha still fails")
        (ev18 / "verdict.md").write_text(f"accept\n\ncommit: {harness_sha}\nmodel: gpt-5.2\n\nnone.\n")

        # #9: run_board(write=False) renders and measures without touching files
        before = (st / "STATE.md").read_text()
        r = subprocess.run([sys.executable, "-c",
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from pathlib import Path\n"
            "from codic.config import Codic\n"
            "from codic import board as B\n"
            "f = Codic(Path(sys.argv[2]) / '.codic')\n"
            "B.run_board(f, None, quiet=True, write=False)\n"
            "print('rendered')",
            libdir, str(repo)], capture_output=True, text=True)
        expect_contains(r.stdout, "rendered", "pure render mode runs (issue #9)")
        expect_contains((st / "STATE.md").read_text(), before, "pure render left STATE.md untouched")

        # #10: done collapses to a count line; only the active set can overflow
        verbose = ("---\nid: {i}\ntitle: old work {i} with a long descriptive title "
                   "that used to burn board tokens\nrole: implementer\nquestion: >\n"
                   "  Does this verbose historical work item with a long question about "
                   "parity and throughput actually close when verified end to end?\n---\n\nbody\n")
        for i in range(501, 601):
            (st / "queue" / "done" / f"{i}-old.md").write_text(verbose.format(i=i))
        r = codic(repo, "board")
        expect_contains(r.stdout, "BOARD.md", "board regenerates with 100 done tickets (issue #10)")
        board_text = (st / "queue" / "BOARD.md").read_text()
        expect_contains(board_text, "closed: done: 103", "done collapses to a count line")
        if "| 501 |" in board_text:
            FAILURES.append("done rows still rendered on the board (issue #10)")
            print("  ✗ done rows omitted")
        else:
            print("  ✓ done rows omitted")
        for i in range(701, 1101):
            (st / "queue" / "ready" / f"{i}-noise.md").write_text(verbose.format(i=i))
        r = codic(repo, "board", expect=1)
        expect_contains(r.stdout + r.stderr, "active set itself",
                        "overflow remedy names the active set, not done archiving")
        for i in range(701, 1101):
            (st / "queue" / "ready" / f"{i}-noise.md").unlink()
        for i in range(501, 601):
            (st / "queue" / "done" / f"{i}-old.md").unlink()
        codic(repo, "board")

        # #11: render keeps injected keys; the parser rejects off-schema loudly
        r = subprocess.run([sys.executable, "-c",
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from codic import ticket as T\n"
            "out = T.render({'id':'1','title':'t','role':'implementer','question':'q',"
            "'branch':'ticket-1'})\n"
            "assert 'branch: ticket-1' in out, 'key dropped: ' + out\n"
            "try:\n"
            "    T.parse_frontmatter(out)\n"
            "except T.TicketError as e:\n"
            "    assert 'unknown frontmatter key' in str(e), e\n"
            "    print('loud')\n"
            "else:\n"
            "    raise SystemExit('silent acceptance of unknown key')",
            libdir], capture_output=True, text=True)
        expect_contains(r.stdout, "loud",
                        "render round-trips; parser rejects off-schema loudly (issue #11)")

        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "fleet green after all issue regressions")

        print("[15] render_states honored and late-bound")
        r = subprocess.run([sys.executable, "-c",
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from pathlib import Path\n"
            "from codic.config import Codic\n"
            "from codic import board as B, ticket as T\n"
            "f = Codic(Path(sys.argv[2]) / '.codic')\n"
            "tickets, _ = T.all_tickets(f.queue)\n"
            "done_only = B.build_board(f, tickets, render_states=('done',))\n"
            "assert '## done (3)' in done_only, 'parameter ignored: ' + done_only\n"
            "assert 'closed: doing: 1, ready: 1, reviewed: 1' in done_only, done_only\n"
            "orig = B.RENDER_STATES\n"
            "B.RENDER_STATES = ('done',)\n"
            "swapped = B.build_board(f, tickets)\n"
            "B.RENDER_STATES = orig\n"
            "assert '## done (3)' in swapped, 'global swap ignored'\n"
            "print('honored')",
            libdir, str(repo)], capture_output=True, text=True)
        expect_contains(r.stdout, "honored",
                        "render_states honored per call and via global swap (issue #13)")

        print("[16] issue regressions: #15 #16 #17 #18 #19")

        # #15: plain dispatch arms nothing and no longer promises a watchdog
        r = codic(repo, "dispatch", "7", "--delta", "d2", "--budget", "b")
        expect_contains(r.stdout, "disarms any watchdog armed for you",
                        "dispatch footer promises only what report does (issue #15)")
        r = codic(repo, "watch", "list")
        armed = [ln for ln in r.stdout.splitlines() if " armed " in ln]
        if armed:
            FAILURES.append(f"plain dispatch armed a watch (issue #15): {armed}")
            print("  ✗ plain dispatch arms nothing")
        else:
            print("  ✓ plain dispatch arms nothing, and says so")

        # #16: two arms in the same second both survive
        r = subprocess.run([sys.executable, "-c",
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from pathlib import Path\n"
            "from codic.config import Codic\n"
            "import codic.harness as H\n"
            "from codic import cli\n"
            "f = Codic(Path(sys.argv[2]) / '.codic')\n"
            "class Stub:\n"
            "    name = 'stub'; interactive = True\n"
            "    def resolve(self, n): return True\n"
            "H.get = lambda f: Stub()\n"
            "a = cli._arm_watchdog(f, 'impl', 'why', 2, 'orchy')\n"
            "b = cli._arm_watchdog(f, 'appr', 'why', 2, 'orchy')\n"
            "assert a != b, f'both arms got {a}: one silently lost'\n"
            "files = {p.name for p in f.watches_dir.glob('*.watch')}\n"
            "assert a + '.watch' in files and b + '.watch' in files, files\n"
            "for p in f.watches_dir.glob('*.watch'): p.unlink()\n"
            "print('distinct')",
            libdir, str(repo)], capture_output=True, text=True)
        expect_contains(r.stdout, "distinct", "same-second arms both survive (issue #16)")

        # #17: archived ids are spent; a manual collision goes check red
        codic(repo, "ticket", "new", "19", "--role", "implementer", "--title", "retire me",
              "--question", "Q19?", "--accept", "true")
        codic(repo, "ticket", "move", "19", "done")
        (st / "archive").mkdir(exist_ok=True)
        p19 = next((st / "queue" / "done").glob("19-*.md"))
        p19.rename(st / "archive" / p19.name)
        r = codic(repo, "ticket", "new", "19", "--role", "implementer", "--title", "again",
                  "--question", "Q19 again?", expect=1)
        expect_contains(r.stdout + r.stderr, "already used", "archived id rejected (issue #17)")
        (st / "queue" / "ready" / "19-clone.md").write_text((st / "archive" / p19.name).read_text())
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout + r.stderr, "evidence/19/", "live+archive id collision fails I4")
        (st / "queue" / "ready" / "19-clone.md").unlink()

        # #19: deferred_files parses clean, contradicts loud, demands paperwork
        codic(repo, "ticket", "new", "21", "--role", "implementer", "--title", "defer work",
              "--question", "Q21?", "--accept", "true", "--file", "src/a.py",
              "--defer", "src/b.py (since 2026-11-16: ticket 16 owns it)")
        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "annotated deferral parses clean (issue #19)")
        t21 = next((st / "queue" / "ready").glob("21-*.md"))
        txt = t21.read_text().replace("  - src/a.py", "  - src/a.py\n  - src/b.py")
        t21.write_text(txt)
        r = codic(repo, "check")
        expect_contains(r.stdout, "both files and deferred_files",
                        "path in files and deferred_files warns")
        t21.write_text(txt.replace(" (since 2026-11-16: ticket 16 owns it)", ""))
        r = codic(repo, "check")
        expect_contains(r.stdout, "without '(since", "unannotated deferral warns")
        t21.unlink()
        codic(repo, "board")

        # #18: the public module surface is a contract; renames break here first
        r = subprocess.run([sys.executable, "-c",
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from codic import board, ticket, state, config, check, harness\n"
            "surface = {\n"
            "    board: ('RENDER_STATES', 'STATE_ORDER', 'build_board', 'build_census', 'run_board'),\n"
            "    ticket: ('REQUIRED', 'OPTIONAL', 'LIST_KEYS', 'SCALAR_KEYS', 'render',\n"
            "             'parse_frontmatter', 'load', 'split', 'all_tickets'),\n"
            "    state: ('law_lines', 'set_census', 'roster_load', 'chain_verify', 'chain_checkpoint',\n"
            "            'atomic_write', 'dispatch_render', 'dispatch_check_size', 'now_utc', 'today'),\n"
            "    config: ('Codic', 'STATE_DIRS', 'BUDGET_LAW', 'BUDGET_CENSUS', 'BUDGET_BOARD',\n"
            "              'BUDGET_DISPATCH'),\n"
            "    harness: ('get', 'validate_name'),\n"
            "    check: ('run_check',),\n"
            "}\n"
            "for obj, names in surface.items():\n"
            "    missing = [n for n in names if not hasattr(obj, n)]\n"
            "    assert not missing, obj.__name__ + ' lost: ' + ', '.join(missing)\n"
            "print('public')",
            libdir], capture_output=True, text=True)
        expect_contains(r.stdout, "public", "public module surface intact (issue #18)")

        r = codic(repo, "check")
        expect_contains(r.stdout, "0 fail", "fleet green after all regressions")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILURES:
        print(f"\nSMOKE FAILED ({len(FAILURES)} problems):")
        for f in FAILURES:
            print("---\n" + f)
        return 1
    print("\nSMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
