"""Automated verification of the R-11 public launch package for egemenyucelen.me.

Validates:
1. Static site files structure, valid HTML5, and clean internal links.
2. Zero-tracking policy: no analytics scripts, pixels, external CDNs, or cookie trackers.
3. CNAME file correctness for custom domain egemenyucelen.me.
4. Consistency of verified project numbers across README, site, and sponsor brief.
5. Accurate disclosures in privacy policy regarding durable row budget and third-party providers.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from euroleague.mcp.tools import TOOL_NAMES

SITE_DIR = Path("site")
HTML_FILES = ("index.html", "privacy.html", "support.html")
DOC_FILES = ("SPONSOR_ONE_PAGER.md", "LAUNCH_COPY.md", "OWNER_LAUNCH_STEPS.md")
LAUNCH_THREAD = Path("docs/LAUNCH_THREAD_FINAL.md")
PUBLIC_LAUNCH_SURFACES = (
    Path("README.md"),
    SITE_DIR / "index.html",
    SITE_DIR / "support.html",
    Path("docs/LAUNCH_COPY.md"),
    Path("docs/SPONSOR_ONE_PAGER.md"),
    LAUNCH_THREAD,
)
ARCHIVE_STATUS_SURFACES = (
    Path("README.md"),
    SITE_DIR / "index.html",
    Path("docs/LAUNCH_COPY.md"),
    Path("docs/SPONSOR_ONE_PAGER.md"),
)
# Surfaces that must not overclaim, but are not required to raise the subject.
# A tweet thread has no room to disclose the backfill; it still must not say the
# archive is finished.
OVERCLAIM_SURFACES = (*ARCHIVE_STATUS_SURFACES, SITE_DIR / "support.html", LAUNCH_THREAD)

FORBIDDEN_TRACKER_PATTERNS = [
    r"google-analytics\.com",
    r"googletagmanager\.com",
    r"analytics\.js",
    r"gtag",
    r"facebook\.net",
    r"hotjar\.com",
    r"segment\.com",
    r"mixpanel\.com",
    r"clarity\.ms",
]


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a" and "href" in attr_dict:
            self.links.append(attr_dict["href"])
        elif tag == "link" and attr_dict.get("rel") == "stylesheet" and "href" in attr_dict:
            self.stylesheets.append(attr_dict["href"])
        elif tag == "script" and "src" in attr_dict:
            self.scripts.append(attr_dict["src"])


class PrivacyMarkupParser(HTMLParser):
    """Extract structured strong-tagged labels and code fragments from privacy policy."""

    def __init__(self) -> None:
        super().__init__()
        self.strong_labels: list[str] = []
        self.code_elements: list[str] = []
        self._in_strong = False
        self._in_code = False
        self._current_strong: list[str] = []
        self._current_code: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "strong":
            self._in_strong = True
            self._current_strong = []
        elif tag == "code":
            self._in_code = True
            self._current_code = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "strong":
            self._in_strong = False
            label = "".join(self._current_strong).strip().rstrip(":")
            if label:
                self.strong_labels.append(label)
        elif tag == "code":
            self._in_code = False
            code_text = "".join(self._current_code).strip()
            if code_text:
                self.code_elements.append(code_text)

    def handle_data(self, data: str) -> None:
        if self._in_strong:
            self._current_strong.append(data)
        if self._in_code:
            self._current_code.append(data)


def test_site_directory_and_required_files_exist() -> None:
    """All required static site assets must exist on disk."""
    assert SITE_DIR.is_dir(), "site/ directory is missing"
    assert (SITE_DIR / "style.css").is_file(), "site/style.css is missing"
    assert (SITE_DIR / "CNAME").is_file(), "site/CNAME is missing"
    for filename in HTML_FILES:
        path = SITE_DIR / filename
        assert path.is_file(), f"site/{filename} is missing"


def test_cname_file_contains_expected_domain() -> None:
    """CNAME file must specify egemenyucelen.me exactly."""
    cname_text = (SITE_DIR / "CNAME").read_text(encoding="utf-8").strip()
    assert cname_text == "egemenyucelen.me", f"Expected 'egemenyucelen.me', got '{cname_text}'"


def test_html_files_have_valid_html5_structure() -> None:
    """Every HTML file must have valid HTML5 declarations and essential meta tags."""
    for filename in HTML_FILES:
        content = (SITE_DIR / filename).read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content, f"{filename} missing <!DOCTYPE html>"
        assert "<html" in content and "</html>" in content, f"{filename} missing <html> tags"
        assert "<head>" in content and "</head>" in content, f"{filename} missing <head> tags"
        assert '<meta charset="UTF-8">' in content, f"{filename} missing UTF-8 charset"
        assert '<meta name="viewport"' in content, f"{filename} missing viewport meta tag"
        assert "<title>" in content and "</title>" in content, f"{filename} missing <title>"
        assert "<body>" in content and "</body>" in content, f"{filename} missing <body> tags"


def test_internal_links_and_stylesheets_resolve() -> None:
    """All relative links and stylesheet links inside HTML files must point to existing files."""
    for filename in HTML_FILES:
        html_path = SITE_DIR / filename
        content = html_path.read_text(encoding="utf-8")
        parser = LinkExtractor()
        parser.feed(content)

        # Check stylesheets
        for sheet_href in parser.stylesheets:
            target = SITE_DIR / sheet_href
            assert target.is_file(), (
                f"In {filename}: stylesheet '{sheet_href}' not found at {target}"
            )

        # Check relative hyperlinks
        for href in parser.links:
            parsed = urlparse(href)
            if parsed.scheme or href.startswith("#"):
                continue
            # Strip fragment e.g. "index.html#features" -> "index.html"
            base_href = href.split("#", 1)[0]
            if base_href:
                target = SITE_DIR / base_href
                assert target.is_file(), (
                    f"In {filename}: broken relative link '{href}' (resolves to {target})"
                )


def test_external_links_use_https() -> None:
    """All external web links must use HTTPS."""
    for filename in HTML_FILES:
        content = (SITE_DIR / filename).read_text(encoding="utf-8")
        parser = LinkExtractor()
        parser.feed(content)
        for href in parser.links:
            parsed = urlparse(href)
            if parsed.scheme == "http":
                raise AssertionError(f"In {filename}: insecure HTTP link found: '{href}'")


def test_zero_trackers_and_third_party_scripts() -> None:
    """The site must load no script it does not ship itself.

    This used to forbid every `<script src>` outright, which matched the old
    site because the old site had no behaviour. The rebuilt hero types a
    conversation and the shot chart places real coordinates, so first-party
    scripts now exist and that blanket ban would have to be deleted rather than
    tightened - the worst outcome, because the property actually worth keeping
    is not "no scripts" but "nothing from anybody else".

    So the rule is now what its name always said: a script must be a relative
    path inside `site/`. Any absolute URL, protocol-relative URL, or path that
    climbs out of the directory fails, whatever host it names. A visitor's
    browser talks to this site and to nothing else - no CDN, no analytics, no
    font host, nobody who could log the visit.
    """
    for filename in HTML_FILES:
        content = (SITE_DIR / filename).read_text(encoding="utf-8")
        for pattern in FORBIDDEN_TRACKER_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            assert not match, (
                f"In {filename}: forbidden tracker pattern '{pattern}' matched: {match.group(0)}"
            )

        parser = LinkExtractor()
        parser.feed(content)
        for script_src in parser.scripts:
            assert not re.match(r"(?:[a-z][a-z0-9+.-]*:)?//", script_src, re.IGNORECASE), (
                f"In {filename}: script is loaded from another origin: {script_src}"
            )
            assert not script_src.startswith("/") and ".." not in script_src, (
                f"In {filename}: script escapes the site directory: {script_src}"
            )
            assert (SITE_DIR / script_src).is_file(), (
                f"In {filename}: script '{script_src}' is not shipped with the site"
            )


def test_launch_documentation_files_exist() -> None:
    """Sponsor one-pager, launch copy, and owner checklist must exist."""
    sponsor_doc = Path("docs/SPONSOR_ONE_PAGER.md")
    launch_copy = Path("docs/LAUNCH_COPY.md")
    owner_steps = Path("docs/OWNER_LAUNCH_STEPS.md")

    assert sponsor_doc.is_file(), "docs/SPONSOR_ONE_PAGER.md is missing"
    assert launch_copy.is_file(), "docs/LAUNCH_COPY.md is missing"
    assert owner_steps.is_file(), "docs/OWNER_LAUNCH_STEPS.md is missing"

    # Verify non-trivial length
    assert len(sponsor_doc.read_text(encoding="utf-8").splitlines()) >= 30
    assert len(launch_copy.read_text(encoding="utf-8").splitlines()) >= 50
    assert len(owner_steps.read_text(encoding="utf-8").splitlines()) >= 40


def test_privacy_policy_accurately_discloses_durable_row_budget_and_providers() -> None:
    """Privacy policy must describe durable database row ledger and real third-party providers."""
    privacy_text = (SITE_DIR / "privacy.html").read_text(encoding="utf-8")
    parser = PrivacyMarkupParser()
    parser.feed(privacy_text)

    # Durable row budget table and identifier disclosure in code markup
    assert "public.mcp_row_usage" in parser.code_elements, (
        "privacy.html missing code markup for public.mcp_row_usage"
    )
    assert "sub" in parser.code_elements, "privacy.html missing code markup for sub"

    # Structured provider items in Section 5
    required_providers = {
        "Auth0 / Google",
        "Fly.io",
        "Supabase (PostgreSQL)",
        "GitHub Pages",
        "Cloudflare",
    }
    present_strong_labels = set(parser.strong_labels)
    missing = required_providers - present_strong_labels
    assert not missing, f"privacy.html missing structured provider labels: {missing}"


def test_verified_claims_consistency() -> None:
    """A figure quoted anywhere must be the verified one, and must not disagree.

    This used to require every surface to carry all four figures, which was a
    reasonable proxy while the site was a page of claims. The rebuilt site
    deliberately has no statistics row - a visitor who does not yet know what
    the product is cannot be moved by "107,311 possessions" - so requiring the
    figure would force copy back onto the page that the design removed.

    What still matters, and is what this now checks: nobody may quote a
    different number. Each figure is optional per surface and exact where it
    appears, so a stale 730 or 99.4% fails wherever somebody writes it.
    """
    readme_text = Path("README.md").read_text(encoding="utf-8")
    index_text = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    sponsor_text = Path("docs/SPONSOR_ONE_PAGER.md").read_text(encoding="utf-8")

    # (verified value, the pattern that would be a competing claim)
    verified = (
        ("732", re.compile(r"7[0-9]{2} games", re.IGNORECASE)),
        ("107,311", re.compile(r"10[0-9],[0-9]{3} possessions", re.IGNORECASE)),
        ("41,524", re.compile(r"4[0-9],[0-9]{3} (?:verified )?coordinates", re.IGNORECASE)),
        ("99.54%", re.compile(r"99\.[0-9]{1,2}%", re.IGNORECASE)),
    )

    # The two documents whose job is to state the numbers still must state them.
    for name, text in (("README", readme_text), ("SPONSOR_ONE_PAGER", sponsor_text)):
        for value, _competing in verified:
            assert value in text, f"{name} missing {value}"

    # The site may say as much or as little as the design calls for, but a
    # figure it does state has to be the verified one.
    for value, competing in verified:
        for match in competing.finditer(index_text):
            assert value in match.group(0), (
                f"index.html quotes {match.group(0)!r}, which is not the verified {value}"
            )

    assert "732" in index_text, (
        "index.html should still say how many games are loaded; it is the one "
        "coverage claim the page makes"
    )


def test_public_launch_copy_does_not_claim_the_running_archive_is_complete() -> None:
    """The historical chain is still running, so completion copy would be false."""
    # Archived is not loaded. E2007 to E2021 are in the immutable archive; the
    # warehouse a visitor queries holds E2024, E2025 and the filling E2026, and
    # copy that blurs the two promises data nobody can query.
    forbidden = (
        # 23 was the season count before 2026-09-03, when E2006 and older were
        # measured as empty at every game endpoint. Twenty is the true figure,
        # and a public surface still saying 23 is selling four seasons that do
        # not exist upstream.
        re.compile(r"23\s+seasons", re.IGNORECASE),
        # Archived is not loaded. E2007 to E2021 sit in the immutable archive;
        # the warehouse a visitor queries holds E2024, E2025 and the filling
        # E2026, and copy that blurs the two promises data nobody can query.
        re.compile(r"every\s+season.{0,30}(?:loaded|queryable)", re.IGNORECASE),
        re.compile(r"all\s+seasons.{0,30}(?:loaded|queryable)", re.IGNORECASE),
    )

    # Until 2026-09-03 every one of these surfaces had to disclose that the
    # archive backfill was still running. It is not: the chain reached the
    # oldest season the API serves and stopped (Decision 52). Requiring the
    # disclosure now would require the page to describe something that is over,
    # so the requirement is dropped and only the overclaim check below stays.

    for path in OVERCLAIM_SURFACES:
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            assert not pattern.search(text), (
                f"{path} overclaims archive completion: {pattern.pattern}"
            )


def test_public_launch_surfaces_only_advertise_current_mcp_tool_names() -> None:
    """Every concrete el_* name in public copy must exist in the live registry."""
    advertised: dict[Path, set[str]] = {}
    current_names = set(TOOL_NAMES)

    for path in PUBLIC_LAUNCH_SURFACES:
        names = set(re.findall(r"\bel_[a-z_]+\b", path.read_text(encoding="utf-8")))
        unknown = names - current_names
        if unknown:
            advertised[path] = unknown

    assert not advertised, f"Public launch copy advertises unknown MCP tools: {advertised}"


def test_readme_tool_table_lists_every_registered_tool() -> None:
    """The README states a tool count, so its table must match the registry.

    The guard above catches a name we advertise but do not serve. It cannot
    catch the opposite - a tool we serve and forgot to list - because an
    incomplete list contains no unknown name. Both directions mislead a reader
    on a public surface, so this asserts the missing one.
    """
    readme_text = Path("README.md").read_text(encoding="utf-8")

    listed = set(re.findall(r"\|\s*`(el_[a-z_]+)`\s*\|", readme_text))
    missing = set(TOOL_NAMES) - listed
    assert not missing, f"README tool table omits registered tools: {sorted(missing)}"

    claimed = re.search(r"exposes (\d+) read-only tools", readme_text)
    assert claimed is not None, "README must state how many read-only tools it exposes"
    assert int(claimed.group(1)) == len(TOOL_NAMES), (
        f"README claims {claimed.group(1)} tools; the registry serves {len(TOOL_NAMES)}"
    )


def test_lineup_metrics_share_the_copy_column() -> None:
    """The live figures must use the space below the short lineup explanation."""
    index_text = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    lineup = index_text.split('id="lineups"', 1)[1].split('id="ask"', 1)[0]

    copy_start = lineup.index('<div class="claim-copy">')
    figure_start = lineup.index('<div class="claim-figure">')
    verdict = lineup.index('<div class="unit-verdict">')

    assert copy_start < verdict < figure_start, (
        "The lineup metrics must sit below the copy instead of adding height under the court"
    )


def test_hard_questions_show_thinking_without_technical_call_chrome() -> None:
    """Each case gets one human-readable thought, not an internal tool transcript."""
    index_text = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    deep = index_text.split('id="deep"', 1)[1].split('id="how"', 1)[0]

    assert deep.count('class="deep-thought"') == 3
    for technical_class in ("deep-call", "toolcall-name", "deep-args", "deep-back"):
        assert technical_class not in deep, (
            f"The hard-question examples still expose technical UI: {technical_class}"
        )


def test_page_background_keeps_only_the_sideline_system() -> None:
    """The page frame keeps its rails and section ticks, without court furniture."""
    index_text = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    background = index_text.split('<div class="courtgrid"', 1)[1].split('<main id="main">', 1)[0]
    stylesheet = (SITE_DIR / "style.css").read_text(encoding="utf-8")

    assert 'class="rail rail-left"' in background
    assert 'class="rail rail-right"' in background
    assert "<svg" not in background
    assert "halfway" not in background
    assert ".claim::before" in stylesheet
