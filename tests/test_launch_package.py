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

SITE_DIR = Path("site")
HTML_FILES = ("index.html", "privacy.html", "support.html")
DOC_FILES = ("SPONSOR_ONE_PAGER.md", "LAUNCH_COPY.md", "OWNER_LAUNCH_STEPS.md")

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
            if (
                href.startswith("#")
                or href.startswith("mailto:")
                or href.startswith("https://")
                or href.startswith("http://")
            ):
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
            if href.startswith("http://"):
                raise AssertionError(f"In {filename}: insecure HTTP link found: '{href}'")


def test_zero_trackers_and_scripts() -> None:
    """The static site must not include external tracking scripts, CDNs, or analytics."""
    for filename in HTML_FILES:
        content = (SITE_DIR / filename).read_text(encoding="utf-8")
        for pattern in FORBIDDEN_TRACKER_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            assert not match, (
                f"In {filename}: forbidden tracker pattern '{pattern}' matched: {match.group(0)}"
            )

        parser = LinkExtractor()
        parser.feed(content)
        # There should be zero external scripts
        for script_src in parser.scripts:
            raise AssertionError(f"In {filename}: unexpected external script found: {script_src}")


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

    # Durable row budget table / mechanism
    assert "mcp_row_usage" in privacy_text, (
        "privacy.html missing disclosure of mcp_row_usage ledger"
    )
    assert "50,000" in privacy_text, "privacy.html missing daily row limit"
    assert "sub" in privacy_text, "privacy.html missing subject identifier disclosure"

    # Third-party infrastructure providers
    assert "Fly.io" in privacy_text, "privacy.html missing Fly.io disclosure"
    assert "Supabase" in privacy_text, "privacy.html missing Supabase disclosure"
    assert "Cloudflare" in privacy_text, "privacy.html missing Cloudflare disclosure"
    assert "GitHub Pages" in privacy_text, "privacy.html missing GitHub Pages disclosure"
    assert "Auth0" in privacy_text or "Google" in privacy_text, (
        "privacy.html missing OAuth provider disclosure"
    )


def test_verified_claims_consistency() -> None:
    """Numerical claims in README, site, and sponsor doc must match verified constants."""
    readme_text = Path("README.md").read_text(encoding="utf-8")
    index_text = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    sponsor_text = Path("docs/SPONSOR_ONE_PAGER.md").read_text(encoding="utf-8")

    # 732 games across loaded seasons
    assert "732" in readme_text, "README missing 732 games count"
    assert "732" in index_text, "index.html missing 732 games count"
    assert "732" in sponsor_text, "SPONSOR_ONE_PAGER missing 732 games count"

    # 107,311 total possessions
    assert "107,311" in readme_text, "README missing 107,311 possession count"
    assert "107,311" in index_text, "index.html missing 107,311 possession count"
    assert "107,311" in sponsor_text, "SPONSOR_ONE_PAGER missing 107,311 possession count"

    # 41,524 verified real coordinates in E2024
    assert "41,524" in readme_text, "README missing 41,524 verified coordinates count"
    assert "41,524" in index_text, "index.html missing 41,524 verified coordinates count"
    assert "41,524" in sponsor_text, "SPONSOR_ONE_PAGER missing 41,524 verified coordinates count"

    # 99.54% minute accuracy
    assert "99.54%" in readme_text, "README missing 99.54% minute accuracy"
    assert "99.54%" in index_text, "index.html missing 99.54% minute accuracy"
    assert "99.54%" in sponsor_text, "SPONSOR_ONE_PAGER missing 99.54% minute accuracy"

    # 23 seasons archived
    assert "23 seasons" in readme_text, "README missing 23 seasons mention"
    assert "23" in index_text and "Seasons Archived" in index_text, (
        "index.html missing 23 seasons mention"
    )
    assert "23 seasons" in sponsor_text, "SPONSOR_ONE_PAGER missing 23 seasons mention"
