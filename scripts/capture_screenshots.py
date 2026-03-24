#!/usr/bin/env python3
"""Capture all 12 screenshots for REVIEWER_README.md using Playwright.

Prerequisites:
    - pip install playwright
    - playwright install chromium
    - Local web server running: python -m http.server 8888 --directory .
    - Pipeline already run: python -m src.main --new-data data/new_system/
    - Tests already run: pytest tests/ -v

Usage:
    python scripts/capture_screenshots.py
"""

import subprocess
import textwrap
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
BASE_URL = "http://localhost:8888"

# Terminal color palette (One Dark-ish)
TERM_CSS = """
body {
    margin: 0; padding: 24px 28px;
    background: #1e1e2e;
    font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
    font-size: 13.5px; line-height: 1.55;
    color: #cdd6f4;
}
pre { margin: 0; white-space: pre-wrap; word-wrap: break-word; }
.prompt { color: #89b4fa; }
.cmd    { color: #a6e3a1; font-weight: bold; }
.info   { color: #cdd6f4; }
.ok     { color: #a6e3a1; }
.warn   { color: #f9e2af; }
.err    { color: #f38ba8; }
.dim    { color: #6c7086; }
.header { color: #89dceb; font-weight: bold; }
.num    { color: #fab387; }
.pass   { color: #a6e3a1; font-weight: bold; }
.fail   { color: #f38ba8; font-weight: bold; }
.test   { color: #cba6f7; }
.sep    { color: #585b70; }
"""


def _colorize_pipeline(raw: str) -> str:
    """Apply span classes to pipeline output lines."""
    lines = []
    for line in raw.splitlines():
        if not line.strip():
            lines.append("")
            continue
        if "====" in line:
            lines.append(f'<span class="sep">{_esc(line)}</span>')
        elif "STEP" in line:
            lines.append(f'<span class="header">{_esc(line)}</span>')
        elif "✓" in line:
            lines.append(f'<span class="ok">{_esc(line)}</span>')
        elif "⚠" in line:
            lines.append(f'<span class="warn">{_esc(line)}</span>')
        elif "[ERROR]" in line or "✗" in line:
            lines.append(f'<span class="err">{_esc(line)}</span>')
        elif "Pipeline:" in line and "completed" in line:
            lines.append(f'<span class="ok">{_esc(line)}</span>')
        elif "Report:" in line:
            lines.append(f'<span class="ok">{_esc(line)}</span>')
        else:
            lines.append(f'<span class="info">{_esc(line)}</span>')
    return "\n".join(lines)


def _colorize_tests(raw: str) -> str:
    """Apply span classes to pytest -v output lines."""
    lines = []
    for line in raw.splitlines():
        if not line.strip():
            lines.append("")
            continue
        if "PASSED" in line:
            # Split at PASSED to color the test name and PASSED separately
            parts = line.split("PASSED", 1)
            pct = parts[1] if len(parts) > 1 else ""
            lines.append(f'<span class="test">{_esc(parts[0])}</span><span class="pass">PASSED</span><span class="dim">{_esc(pct)}</span>')
        elif "FAILED" in line:
            parts = line.split("FAILED", 1)
            pct = parts[1] if len(parts) > 1 else ""
            lines.append(f'<span class="test">{_esc(parts[0])}</span><span class="fail">FAILED</span><span class="dim">{_esc(pct)}</span>')
        elif "passed" in line and "==" in line:
            lines.append(f'<span class="pass">{_esc(line)}</span>')
        elif "failed" in line and "==" in line:
            lines.append(f'<span class="fail">{_esc(line)}</span>')
        elif line.startswith("tests/"):
            lines.append(f'<span class="test">{_esc(line)}</span>')
        elif "==" in line:
            lines.append(f'<span class="sep">{_esc(line)}</span>')
        elif line.startswith("collecting") or line.startswith("collected"):
            lines.append(f'<span class="dim">{_esc(line)}</span>')
        else:
            lines.append(f'<span class="info">{_esc(line)}</span>')
    return "\n".join(lines)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_terminal_html(title: str, prompt_cmd: str, body_html: str) -> str:
    return textwrap.dedent(f"""\
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <style>{TERM_CSS}</style></head><body>
    <pre><span class="prompt">❯ </span><span class="cmd">{_esc(prompt_cmd)}</span>
{body_html}</pre>
    </body></html>""")


def capture_terminal_screenshot(page, filename: str, html: str, width=1100, min_height=400):
    """Render terminal HTML and screenshot it."""
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(html)
    page.wait_for_timeout(300)
    # Get actual content height
    height = page.evaluate("() => document.body.scrollHeight + 48")
    height = max(height, min_height)
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(100)
    path = str(SCREENSHOTS_DIR / filename)
    page.screenshot(path=path, full_page=False)
    print(f"  ✓ {filename} ({width}x{height})")


def capture_browser_screenshot(page, url: str, filename: str, width=1440, height=900,
                                wait_ms=1500, scroll_to=None, clip=None):
    """Navigate to URL and screenshot."""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(wait_ms)
    if scroll_to:
        page.evaluate(f"window.scrollTo(0, {scroll_to})")
        page.wait_for_timeout(500)
    path = str(SCREENSHOTS_DIR / filename)
    if clip:
        page.screenshot(path=path, clip=clip)
    else:
        page.screenshot(path=path, full_page=False)
    print(f"  ✓ {filename} ({width}x{height})")


def main():
    print("Capturing screenshots...\n")

    # ── 1. Run pipeline and capture output ──
    print("[1/12] Pipeline run output...")
    result = subprocess.run(
        ["python", "-m", "src.main", "--new-data", "data/new_system/", "--skip-ingest"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    pipeline_output = result.stdout + result.stderr
    # Keep only the pipeline log lines (skip blank/setup lines)
    pipeline_lines = [l for l in pipeline_output.splitlines() if l.strip()]
    # Trim to show the interesting parts (steps + summary)
    pipeline_text = "\n".join(pipeline_lines)

    # ── 2. Run tests and capture output ──
    print("[2/12] Test suite output...")
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-v"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    test_output = result.stdout + result.stderr

    # ── 3-12. Browser screenshots ──
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(device_scale_factor=2)  # Retina quality
        page = ctx.new_page()

        # Screenshot 1: Pipeline run
        html1 = _render_terminal_html(
            "Pipeline Run",
            "python -m src.main --new-data data/new_system/",
            _colorize_pipeline(pipeline_text),
        )
        capture_terminal_screenshot(page, "screenshot_1.png", html1, width=1100)

        # Screenshot 2: Test suite
        html2 = _render_terminal_html(
            "Test Suite",
            "pytest tests/ -v",
            _colorize_tests(test_output),
        )
        capture_terminal_screenshot(page, "screenshot_2.png", html2, width=1100)

        # Screenshot 3: Executive Summary — KPIs, pass/fail indicators
        print("[3/12] Executive Summary...")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{BASE_URL}/reports/comparison_report.html", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        el = page.query_selector("#executive-summary-heading")
        if el:
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOTS_DIR / "screenshot_3.png"), full_page=False)
        print(f"  ✓ screenshot_3.png")

        # Screenshot 4: Key Findings — root cause hypotheses, risk assessment
        print("[4/12] Key Findings...")
        el = page.query_selector("#key-findings-heading")
        if el:
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOTS_DIR / "screenshot_4.png"), full_page=False)
        print(f"  ✓ screenshot_4.png")

        # Screenshot 5: Validation Results — expand Issues by Check bar chart
        print("[5/12] Validation Results...")
        # Click to expand the "Issues by Check" collapsible bar chart
        toggle = page.query_selector("#issues-by-check")
        if toggle:
            toggle.click()
            page.wait_for_timeout(800)
            # Pin the bar chart summary to top of viewport so chart dominates
            page.evaluate('''() => {
                const el = document.querySelector("#issues-by-check");
                if (el) el.scrollIntoView({block: "start", behavior: "instant"});
            }''')
            page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOTS_DIR / "screenshot_5.png"), full_page=False)
        print(f"  ✓ screenshot_5.png")

        # Screenshot 6: Financial Reconciliation — MEDREIMB/BENRES/PPPYMT rows
        print("[6/12] Financial Reconciliation...")
        # Scroll to the financial_recon_medreimb_car row in the validation table
        page.evaluate('''() => {
            const cells = document.querySelectorAll("#validation-table td");
            for (const cell of cells) {
                if (cell.textContent.trim() === "financial_recon_medreimb_car") {
                    cell.closest("tr").scrollIntoView({block: "center"});
                    return;
                }
            }
        }''')
        page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOTS_DIR / "screenshot_6.png"), full_page=False)
        print(f"  ✓ screenshot_6.png")

        # Screenshot 7: System Comparison — schema diffs, row-level, field-level, aggregates
        print("[7/12] System Comparison...")
        # Expand the comparison checks detail, then pin heading to top
        detail = page.query_selector("#comparison-checks-detail")
        if detail:
            detail.evaluate("el => el.open = true")
            page.wait_for_timeout(500)
        page.evaluate('''() => {
            const el = document.querySelector("#system-comparison-heading");
            if (el) el.scrollIntoView({block: "start", behavior: "instant"});
        }''')
        page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOTS_DIR / "screenshot_7.png"), full_page=False)
        print(f"  ✓ screenshot_7.png")

        # Screenshot 8: Year-over-Year Trends — interactive Plotly charts
        print("[8/12] Year-over-Year Trends...")
        # Fresh page load so collapsed details don't affect layout
        page.goto(f"{BASE_URL}/reports/comparison_report.html", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        page.evaluate('''() => {
            const el = document.querySelector("#yoy-trends-heading");
            if (el) el.scrollIntoView({block: "start", behavior: "instant"});
        }''')
        page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOTS_DIR / "screenshot_8.png"), full_page=False)
        print(f"  ✓ screenshot_8.png")

        # Screenshot 9: Documentation Hub
        print("[9/12] Documentation Hub...")
        capture_browser_screenshot(
            page, f"{BASE_URL}/docs/index.html",
            "screenshot_9.png", width=1440, height=900, wait_ms=2000,
        )

        # Screenshot 10: Schema Explorer
        print("[10/12] Schema Explorer...")
        capture_browser_screenshot(
            page, f"{BASE_URL}/docs/schema_explorer.html",
            "screenshot_10.png", width=1440, height=900, wait_ms=3000,
        )

        # Screenshot 11: SQL Explorer
        print("[11/12] SQL Explorer...")
        capture_browser_screenshot(
            page, f"{BASE_URL}/docs/sql_explorer.html",
            "screenshot_11.png", width=1440, height=900, wait_ms=3000,
        )

        # Screenshot 12: Parquet Viewer — click a file to show schema + data preview
        print("[12/12] Parquet Viewer...")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{BASE_URL}/docs/parquet_viewer.html", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        # Click the first pipeline export card to load data
        card = page.query_selector(".file-card, .export-card, [onclick]")
        if card:
            card.click()
            page.wait_for_timeout(3000)  # Wait for Parquet parsing
        page.screenshot(path=str(SCREENSHOTS_DIR / "screenshot_12.png"), full_page=False)
        print(f"  ✓ screenshot_12.png")

        browser.close()

    print(f"\n✅ All 12 screenshots saved to {SCREENSHOTS_DIR}/")


if __name__ == "__main__":
    main()
