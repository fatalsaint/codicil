#!/usr/bin/env python3
"""End-to-end smoke test for the codic CLI. No network, no herdr needed.

Creates a throwaway repo, clones the harness into .codic, inits with
backend=none, exercises the ticket/board/check/ledger/gate/scenario/dispatch
loop, then breaks invariants one by one and proves `codic check` goes red.
"""
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
        dsp = sorted((st / "dispatch").glob("*.md"))[-1]
        dsp.write_text(dsp.read_text() + "\nw1:p1 do the work\n")
        r = codic(repo, "check", expect=1)
        expect_contains(r.stdout, "pane/tab id", "I6 catches pane-id addressing")
        dsp.unlink()
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

        print("[9] status + config")
        r = codic(repo, "status")
        expect_contains(r.stdout, "backend: none", "status renders")
        r = codic(repo, "config")
        expect_contains(r.stdout, '"launch_mode"', "config renders")
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
