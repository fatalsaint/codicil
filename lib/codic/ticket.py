"""codic.ticket — ticket frontmatter: a strict YAML subset, parsed by hand.

Schema (SPEC 5.3). Required: id, title, role, question.
Optional: worktree, engine, resource, files, acceptance, blocked-by, scenarios.
Unknown keys are a parse failure (I4: every frontmatter field is in schema).
"""
from __future__ import annotations

import re
from pathlib import Path

REQUIRED = ("id", "title", "role", "question")
OPTIONAL = ("worktree", "engine", "model", "resource", "files", "acceptance", "blocked-by", "scenarios")
LIST_KEYS = ("files", "acceptance", "blocked-by", "scenarios")
SCALAR_KEYS = ("id", "title", "role", "question", "worktree", "engine", "model", "resource")
NAME_RE = re.compile(r"^\d+-[a-z0-9][a-z0-9-]*\.md$")


class TicketError(Exception):
    pass


def _strip_quote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text: str, src: str = "<ticket>") -> dict:
    """Parse the leading `---` block. Raises TicketError on anything off-schema."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise TicketError(f"{src}: missing leading '---' frontmatter")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise TicketError(f"{src}: unterminated frontmatter block")
    fm: dict = {}
    i = 1
    while i < end:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not m:
            raise TicketError(f"{src}: frontmatter line {i + 1} is not 'key: value': {line!r}")
        key, rest = m.group(1), m.group(2).strip()
        if key not in REQUIRED + OPTIONAL:
            raise TicketError(f"{src}: unknown frontmatter key '{key}'")
        # strip trailing inline comment (only when unquoted)
        if rest and not rest.startswith(("\"", "'")):
            rest = re.split(r"\s+#", rest, 1)[0].strip()
        if rest in (">", ">", "|", "|-"):  # folded/literal scalar
            block, i = _collect_block(lines, i + 1, end)
            value = " ".join(b.strip() for b in block if b.strip())
            _set(fm, key, value, src, scalar=True)
            continue
        if rest == "":  # possibly a list on following lines
            block, i = _collect_block(lines, i + 1, end)
            items = []
            for b in block:
                bm = re.match(r"^-\s+(.*)$", b.strip())
                if not bm:
                    raise TicketError(f"{src}: key '{key}' expects a list or scalar, got {b!r}")
                items.append(_strip_quote(bm.group(1)))
            if not items:
                raise TicketError(f"{src}: key '{key}' is empty")
            _set(fm, key, items, src, scalar=False)
            continue
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            items = [_strip_quote(x.strip()) for x in inner.split(",")] if inner else []
            _set(fm, key, items, src, scalar=False)
            i += 1
            continue
        _set(fm, key, _strip_quote(rest), src, scalar=True)
        i += 1
    for req in REQUIRED:
        if req not in fm:
            raise TicketError(f"{src}: missing required field '{req}'")
    for lk in LIST_KEYS:
        if lk in fm and not isinstance(fm[lk], list):
            fm[lk] = [str(fm[lk])]
    fm["id"] = str(fm["id"])
    return fm


def _set(fm: dict, key: str, value, src: str, scalar: bool) -> None:
    if key in fm:
        raise TicketError(f"{src}: duplicate frontmatter key '{key}'")
    if key in LIST_KEYS and scalar:
        value = [str(value)]
    fm[key] = value


def _collect_block(lines: list[str], i: int, end: int) -> tuple[list[str], int]:
    block = []
    while i < end and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
        block.append(lines[i])
        i += 1
    return block, i


def load(path: Path) -> dict:
    fm = parse_frontmatter(path.read_text(), str(path))
    fm["_path"] = str(path)
    return fm


def split(path: Path) -> tuple[dict, str]:
    """(frontmatter, body) so a caller can rewrite fields without losing the contract."""
    text = path.read_text()
    fm = parse_frontmatter(text, str(path))
    lines = text.splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    return fm, "".join(lines[end + 1:])


def ticket_id_from_name(path: Path) -> str:
    if not NAME_RE.match(path.name):
        raise TicketError(f"{path}: ticket file name must be '<digits>-<slug>.md'")
    return path.name.split("-", 1)[0]


def all_tickets(queue_dir: Path) -> tuple[list[dict], list[tuple[Path, str]]]:
    """Return (parsed tickets, [(path, error)]) across all state dirs."""
    tickets, errors = [], []
    for d in queue_dir.iterdir() if queue_dir.exists() else []:
        if not d.is_dir() or d.name not in ("ready", "doing", "review", "reviewed", "gpu", "blocked", "done"):
            continue
        for f in sorted(d.glob("*.md")):
            if f.name == "BOARD.md":
                continue
            try:
                t = load(f)
                tid = ticket_id_from_name(f)
                if t["id"] != tid:
                    raise TicketError(f"{f}: frontmatter id {t['id']!r} != file name id {tid!r}")
                t["_state"] = d.name
                tickets.append(t)
            except TicketError as e:
                errors.append((f, str(e)))
    return tickets, errors


def render(fm: dict, body: str = "") -> str:
    out = ["---"]
    for key in REQUIRED + OPTIONAL:
        if key not in fm:
            continue
        v = fm[key]
        if isinstance(v, list):
            if not v:
                out.append(f"{key}: []")
            else:
                out.append(f"{key}:")
                out += [f"  - {x}" for x in v]
        elif key == "question":
            out.append("question: >")
            out += [f"  {line}" for line in _wrap(str(v), 72)]
        else:
            out.append(f"{key}: {v}")
    out.append("---")
    out.append("")
    if body:
        out.append(body.rstrip() + "\n")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines
