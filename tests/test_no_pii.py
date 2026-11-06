"""No personal data may ship in this repo.

Added 2026-11-05, after an audit found real home details in the
first public releases — a unit number, thermostat room names, and
a building name, all sitting in comments and test fixtures since
the first commit. This test scans every text file in the repo for
the same classes of data and fails the suite if any of it comes
back, so a future commit cannot reintroduce it unnoticed. It runs
in CI on every push (see .github/workflows/tests.yml).

Allowlisted on purpose — public by design, not personal:
- the LICENSE copyright line, which names the author;
- manifest codeowners and README links, which name the public
  account the repo lives under;
- the B2C client ID in const.py — the app's public OAuth client
  ID, identical for every user of the app, not a credential and
  not user-specific;
- synthetic test placeholders (example-domain addresses, the
  all-zero UUID);
- the brand icon filename, which merely looks like an address.

The patterns that would match their own source text are assembled
from parts below, and so are the bad samples in the test — otherwise
this file would flag itself.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories and suffixes the scan skips: version control, bytecode,
# virtualenvs, and binary assets.
SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".ico"}


def _rx(*parts, flags=0):
    """Assemble a pattern from parts, so a pattern that would match
    its own source text never appears as a literal in this file."""
    return re.compile("".join(parts), flags)


# (label, pattern) — every entry is a class of data the 2026-11-05
# audit actually found in the public tree, or a credential-shaped
# value that must never be committed.
PATTERNS = [
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("first name", _rx(r"\b", "Ad", "am", r"\b")),
    ("surname", _rx(r"\b", "Cantrow", "itz", r"\b")),
    ("unit number", _rx(r"\b", "80", "1", r"\b")),
    ("building name", _rx("Power", "house", flags=re.IGNORECASE)),
    ("room name", _rx("main bath", "room", flags=re.IGNORECASE)),
    ("room name", _rx("second bath", "room", flags=re.IGNORECASE)),
    ("remote-access URL", _rx("nabu", r"\.casa")),
    ("LAN address", _rx(r"\b(?:10\.20|192\.168|172\.16)\.")),
    ("personal domain", _rx("cantrowitz", r"\.com")),
    ("street name", _rx("North", "side", flags=re.IGNORECASE)),
    ("management company", _rx("First", "Service", flags=re.IGNORECASE)),
    ("street address", _rx("575 Fi", "fth")),
    ("home coordinates", _rx("40", r"\.74", r"\b")),
    ("home coordinates", _rx("73", r"\.95", r"\b")),
    ("MAC address", re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")),
    ("UUID", re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")),
    ("phone number", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")),
    ("secret value", re.compile(r"(?i)(?:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[\"'][^\"'\s]{16,}")),
    ("lock serial", _rx(r"\bT85", r"V[0-9A-Z]{6,}\b")),
    ("appliance serial", _rx(r"\bMI", r"\d{6}\b")),
]

# Exact matches that are public by design, not personal data.
ALLOWED_TEXT = {
    "icon@2x.png",  # brand icon filename, not an address
    "00000000-0000-0000-0000-000000000000",  # synthetic test UUID
    "4b3a6465-94dd-47c2-976c-18bc29c53c2f",  # public app client ID, see above
}


def _allowed(path: Path, label: str, match: str) -> bool:
    if label == "email address" and (
        match.endswith("@example.com") or match.endswith("@example.org")
    ):
        return True
    if match in ALLOWED_TEXT:
        return True
    if label in {"first name", "surname"} and path.name == "LICENSE":
        return True
    return False


def find_hits_text(text: str) -> list[tuple[str, str]]:
    """(label, match) pairs the patterns find in one string."""
    return [
        (label, m.group(0))
        for label, pattern in PATTERNS
        for m in pattern.finditer(text)
        if not _allowed(Path("sample"), label, m.group(0))
    ]


def find_hits(root: Path = ROOT) -> list[tuple[str, int, str, str]]:
    """(file, line, label, match) for every non-allowlisted hit."""
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                for m in pattern.finditer(line):
                    if not _allowed(path, label, m.group(0)):
                        hits.append(
                            (str(path.relative_to(root)), lineno, label, m.group(0))
                        )
    return hits


def test_no_personal_data_in_repo():
    hits = find_hits()
    assert not hits, (
        "Personal data found in the repo — see tests/test_no_pii.py "
        "for what is allowed and why:\n"
        + "\n".join(f"{f}:{n}: [{label}] {m!r}" for f, n, label, m in hits)
    )


def _bad(*parts):
    """Assemble a bad sample from parts so the literal never appears
    in this file (the scan reads this file too)."""
    return "".join(parts)


def test_patterns_catch_known_bad_samples():
    bad = [
        _bad("user", "@", "mail", ".com"),
        _bad("Ad", "am"),
        _bad("Cantrow", "itz"),
        _bad("80", "1"),
        _bad("Power", "house"),
        _bad("main bath", "room"),
        _bad("second bath", "room"),
        _bad("nabu", ".casa"),
        _bad("192.168", ".1.", "1"),
        _bad("T85", "V0FAKE12345"),
        _bad("pass", "word", "=", '"', "ExamplePassword123456"),
    ]
    for sample in bad:
        assert find_hits_text(sample), f"pattern missed: {sample!r}"


def test_patterns_allow_known_good_samples():
    good = [
        "user@example.com",
        "Bathroom 1",
        "Home",
        "00000000-0000-0000-0000-000000000000",
        "4b3a6465-94dd-47c2-976c-18bc29c53c2f",
        "icon@2x.png",
    ]
    for sample in good:
        assert not find_hits_text(sample), f"false positive: {sample!r}"
