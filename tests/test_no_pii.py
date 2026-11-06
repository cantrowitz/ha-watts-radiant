"""No personal data may ship in this repo.

Added 2026-11-05, after an audit found real home details in the
first public releases. This test scans every text file in the repo
for generic classes of personal data — credential-shaped values,
private addresses, identifiers — and fails the suite if any of it
comes back, so a future commit cannot reintroduce it unnoticed.
It runs in CI on every push (see .github/workflows/tests.yml).

Deliberately generic: this file contains NO real personal values
at all. The specific values from the audit (names, unit/building/
room names, addresses, serials) are NOT listed here — they live
only in the PII_DENYLIST repository secret, checked by
.github/workflows/pii-denylist.yml, which also runs in CI on
every push. Nothing in this file can leak anything about the
author, because nothing real is written in it. Every sample below
is invented.

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
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories and suffixes the scan skips: version control, bytecode,
# virtualenvs, and binary assets.
SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".ico"}

# Generic shapes only — no real value is named anywhere in this file.
PATTERNS = [
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("private IP address", re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b")),
    ("MAC address", re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")),
    ("UUID", re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")),
    ("phone number", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")),
    ("secret value", re.compile(r"(?i)(?:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[\"'][^\"'\s]{16,}")),
    ("lock serial", re.compile(r"\bT85V[0-9A-Z]{6,}\b")),
    ("appliance serial", re.compile(r"\bMI\d{6}\b")),
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
    return match in ALLOWED_TEXT


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
    in this file (the scan reads this file too). Every sample here is
    invented — none of it is real data."""
    return "".join(parts)


def test_patterns_catch_known_bad_samples():
    bad = [
        _bad("user", "@", "mail", ".com"),
        _bad("192.168", ".1.", "1"),
        _bad("AA", ":", "BB", ":", "CC", ":", "DD", ":", "EE", ":", "FF"),
        _bad("123e4567", "-", "e89b", "-", "12d3", "-", "a456", "-", "426614174000"),
        _bad("555", "-", "123", "-", "4567"),
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
        "8.8.8.8",
        "2026.10.4",
        "00000000-0000-0000-0000-000000000000",
        "4b3a6465-94dd-47c2-976c-18bc29c53c2f",
        "icon@2x.png",
    ]
    for sample in good:
        assert not find_hits_text(sample), f"false positive: {sample!r}"
