"""Enforce English-only rule across all tracked repository files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Turkish-specific characters:
# U+011F (g-breve), U+011E (G-breve)
# U+0131 (dotless i), U+0130 (dotted capital I)
# U+015F (s-cedilla), U+015E (S-cedilla)
TURKISH_SPECIFIC_CHARS = set("\u011f\u0131\u015f\u011e\u0130\u015e")

# Common Turkish words matched on word boundaries (\b...\b), case-insensitively.
# Avoid ambiguous English tokens like 'once' or 'var'.
COMMON_TURKISH_WORDS = [
    "bir",
    "ve",
    "bu",
    "i\u00e7in",
    "icin",
    "ile",
    "de\u011fil",
    "degil",
    "\u00e7ok",
    "cok",
    "ama",
    "veya",
    "daha",
    "kadar",
    "olarak",
    "gibi",
    "olan",
    "sonra",
    "taraf\u0131ndan",
    "tarafindan",
    "hay\u0131r",
    "hayir",
    "nas\u0131l",
    "nasil",
    "neden",
    "ni\u00e7in",
    "nicin",
    "burada",
    "\u015fimdi",
    "simdi",
    "\u00e7\u00fcnk\u00fc",
    "cunku",
    "b\u00f6yle",
    "boyle",
    "t\u00fcrk\u00e7e",
    "turkce",
    "g\u00fcncelleme",
    "hata",
    "dosya",
    "sat\u0131r",
    "satir",
    "fonksiyon",
    "de\u011fi\u015fken",
    "degisken",
    "d\u00f6nd\u00fcr",
    "dondur",
    "do\u011fru",
    "dogru",
    "yanl\u0131\u015f",
    "yanlis",
    "a\u00e7\u0131klama",
    "aciklama",
    "ba\u015fl\u0131k",
    "baslik",
]

TURKISH_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in COMMON_TURKISH_WORDS) + r")\b",
    re.IGNORECASE,
)

# Proper name allowlist: The owner's surname ('Yücelen' / 'Yucelen') is an allowed
# proper noun, not a language violation.
ALLOWED_PROPER_NAMES = ["Y\u00fccelen", "Yucelen"]

# Control sample used to verify the detector fires
TURKISH_CONTROL_SAMPLE = (
    "Bu fonksiyon sadece t\u00fcrk\u00e7e karakterler i\u00e7erir ve kontrol edilir."
)


def find_turkish_violations(text: str, rel_path: str = "") -> list[tuple[int, str, str]]:
    """Scan text for Turkish characters or words, returning (line_no, reason, line)."""
    violations: list[tuple[int, str, str]] = []
    lines = text.splitlines()

    for idx, line in enumerate(lines, start=1):
        # Exclude only specific, known definition/citation lines in self and goal 028.
        # This keeps the detector from flagging its own definition while catching any
        # Turkish sentences added to either file.
        normalized_path = rel_path.replace("\\", "/")
        if (
            normalized_path == "docs/goals/028-english-only-guard.md"
            and "(`\u011f \u0131 \u015f \u011e \u0130 \u015e`)" in line
        ):
            continue
        if normalized_path == "tests/test_english_only.py" and "TURKISH_CONTROL_SAMPLE =" in line:
            continue

        # 1. Check for Turkish-specific characters
        found_chars = sorted({c for c in line if c in TURKISH_SPECIFIC_CHARS})
        if found_chars:
            violations.append(
                (
                    idx,
                    f"Contains Turkish-specific character(s): {', '.join(found_chars)}",
                    line.strip(),
                )
            )
            continue

        # 2. Check for common Turkish words after removing allowed proper names
        sanitized = line
        for name in ALLOWED_PROPER_NAMES:
            sanitized = re.sub(re.escape(name), "", sanitized, flags=re.IGNORECASE)

        match = TURKISH_WORD_PATTERN.search(sanitized)
        if match:
            violations.append(
                (
                    idx,
                    f"Contains Turkish word: '{match.group(0)}'",
                    line.strip(),
                )
            )

    return violations


def test_detector_fires_on_control_sample() -> None:
    """Break caught: the scanner breaks silently and tests pass vacuously."""
    violations = find_turkish_violations(TURKISH_CONTROL_SAMPLE)
    assert len(violations) > 0, "Detector failed to detect Turkish control string"


def test_owner_surname_is_allowed_narrowly() -> None:
    """Break caught: owner surname in LICENSE or docs fails, or an allowlist allows Turkish."""
    valid_name_line = "Copyright (c) 2026 Egemen Y\u00fccelen"
    assert find_turkish_violations(valid_name_line) == []

    # A Turkish sentence containing the name must still be flagged for other Turkish content.
    turkish_sentence_with_name = "Egemen Y\u00fccelen bu fonksiyonu geli\u015ftirdi ve test etti."
    violations = find_turkish_violations(turkish_sentence_with_name)
    assert len(violations) > 0


def test_typographic_punctuation_and_box_drawing_are_not_flagged() -> None:
    """Break caught: Unicode arrows, dashes, or box-drawing chars trigger false positives."""
    sample = "Title \u2014 subtitle \u2013 info \u2192 next \u2502 \u250c \u2514 \u2022 \u2026"
    assert find_turkish_violations(sample) == []


def test_detector_would_fire_on_turkish_in_self_or_goal_file() -> None:
    """Break caught: self-exclusion is too broad (e.g. skips the whole file)."""
    fake_turkish_line = "bu sat\u0131r t\u00fcrk\u00e7edir"
    violations_self = find_turkish_violations(
        fake_turkish_line, rel_path="tests/test_english_only.py"
    )
    assert len(violations_self) > 0

    violations_goal = find_turkish_violations(
        fake_turkish_line, rel_path="docs/goals/028-english-only-guard.md"
    )
    assert len(violations_goal) > 0


def test_all_tracked_files_are_english_only() -> None:
    """Scan every tracked file in git for Turkish characters and words."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    assert len(tracked_files) > 50, "git ls-files returned unexpectedly few files"

    all_violations: list[str] = []
    for rel_path in tracked_files:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            continue

        try:
            content = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file
            continue

        violations = find_turkish_violations(content, rel_path=rel_path)
        for line_no, reason, line in violations:
            all_violations.append(f"{rel_path}:{line_no}: {reason}\n    {line}")

    assert not all_violations, (
        f"Found {len(all_violations)} English-only violation(s):\n" + "\n".join(all_violations)
    )
