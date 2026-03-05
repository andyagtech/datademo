#!/usr/bin/env python3
"""Render Markdown documentation files into styled HTML pages.

Converts .md files in docs/ to .html with the project's dark theme,
navigation bar, and table of contents sidebar. Matches the look and
feel of the rest of the documentation hub.

Usage:
    python scripts/render_md_docs.py
"""

import markdown
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"

# Which .md files to render (filename → page title)
# Files are looked up in DOCS_DIR first, then PROJECT_ROOT.
MD_FILES = {
    "SOLUTION.md": "Solution Design",
    "PIPELINE.md": "Pipeline Reference",
    "DATA_DICTIONARY.md": "Data Dictionary",
    "REQUIREMENTS_TRACEABILITY.md": "Requirements Traceability",
    "REVIEWER_README.md": "Reviewer Walkthrough",
}

NAV_BAR = """\
<nav class="project-nav">
  <a href="index.html" class="nav-home">Project Docs Index</a>
  <span class="nav-sep">|</span>
  <a href="reviewer_readme.html">Reviewer Guide</a>
  <a href="reports/comparison_report.html">Report</a>
  <a href="architecture.html">Architecture</a>
  <a href="schema_explorer.html">Schema</a>
  <a href="parquet_viewer.html">Parquet</a>
  <a href="sql_explorer.html">SQL</a>
</nav>"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — CMS Claims Comparison Pipeline</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #232733;
    --border: #2d3148; --text: #e2e8f0; --muted: #8892b0;
    --accent: #38bdf8; --accent2: #818cf8; --green: #34d399;
    --orange: #fb923c; --red: #f87171;
    --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: var(--font); background: var(--bg); color: var(--text); line-height: 1.7; }}

  /* -- Project Nav -- */
  .project-nav {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 300;
    height: 32px; background: #0b0d14; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; padding: 0 16px; gap: 6px;
    font-size: 0.7rem;
  }}
  .project-nav a {{
    color: var(--muted); text-decoration: none; padding: 3px 8px;
    border-radius: 4px; transition: all 0.15s; white-space: nowrap;
  }}
  .project-nav a:hover {{ color: var(--text); background: rgba(56,189,248,0.08); }}
  .project-nav a.active {{ color: var(--accent); background: rgba(56,189,248,0.1); }}
  .project-nav .nav-sep {{ color: var(--border); margin: 0 2px; }}
  .project-nav .nav-home {{ font-weight: 700; color: var(--accent); }}

  /* -- Sidebar TOC -- */
  .sidebar {{
    position: fixed; top: 32px; left: 0; width: 240px; bottom: 0;
    background: var(--surface); border-right: 1px solid var(--border);
    overflow-y: auto; padding: 16px 12px; font-size: 0.75rem;
  }}
  .sidebar::-webkit-scrollbar {{ width: 4px; }}
  .sidebar::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}
  .sidebar .toc-title {{
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); margin-bottom: 10px;
  }}
  .sidebar a {{
    display: block; padding: 4px 8px; margin: 1px 0; border-radius: 4px;
    color: var(--muted); text-decoration: none; transition: all 0.15s;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .sidebar a:hover {{ color: var(--text); background: rgba(56,189,248,0.06); }}
  .sidebar a.depth-2 {{ padding-left: 20px; font-size: 0.7rem; }}

  /* -- Content -- */
  .content {{
    margin-left: 240px; margin-top: 32px; padding: 32px 48px 80px;
    max-width: 960px;
  }}
  @media (max-width: 800px) {{
    .sidebar {{ display: none; }}
    .content {{ margin-left: 0; padding: 24px 20px 60px; }}
  }}

  /* -- Typography -- */
  .content h1 {{
    font-size: 1.6rem; font-weight: 800; margin-bottom: 8px;
    color: var(--accent); border-bottom: 2px solid var(--border);
    padding-bottom: 10px;
  }}
  .content h2 {{
    font-size: 1.15rem; font-weight: 700; margin-top: 2.2rem; margin-bottom: 0.6rem;
    color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 6px;
  }}
  .content h3 {{
    font-size: 0.95rem; font-weight: 700; margin-top: 1.6rem; margin-bottom: 0.4rem;
    color: var(--accent2);
  }}
  .content h4 {{
    font-size: 0.85rem; font-weight: 700; margin-top: 1.2rem; margin-bottom: 0.3rem;
    color: var(--muted);
  }}
  .content p {{ margin-bottom: 0.9rem; font-size: 0.88rem; }}
  .content a {{ color: var(--accent); text-decoration: none; }}
  .content a:hover {{ text-decoration: underline; }}
  .content strong {{ color: var(--text); font-weight: 700; }}
  .content em {{ color: var(--muted); }}
  .content ul, .content ol {{ padding-left: 1.5em; margin-bottom: 1rem; font-size: 0.88rem; }}
  .content li {{ margin-bottom: 0.3rem; }}
  .content li > ul, .content li > ol {{ margin-top: 0.3rem; margin-bottom: 0; }}

  /* -- Code -- */
  .content code {{
    font-family: var(--mono); font-size: 0.78rem;
    background: var(--surface2); padding: 2px 6px; border-radius: 4px;
    color: var(--orange);
  }}
  .content pre {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px 20px; overflow-x: auto;
    margin-bottom: 1.2rem;
  }}
  .content pre code {{
    background: none; padding: 0; color: var(--text); font-size: 0.76rem;
    line-height: 1.6;
  }}

  /* -- Tables -- */
  .content table {{
    width: 100%; border-collapse: collapse; margin-bottom: 1.2rem;
    font-size: 0.8rem;
  }}
  .content th {{
    background: var(--surface); border: 1px solid var(--border);
    padding: 8px 12px; text-align: left; font-weight: 700;
    color: var(--accent); font-size: 0.75rem; text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  .content td {{
    border: 1px solid var(--border); padding: 6px 12px;
    vertical-align: top;
  }}
  .content tr:nth-child(even) {{ background: rgba(26,29,39,0.5); }}

  /* -- Blockquote -- */
  .content blockquote {{
    border-left: 3px solid var(--accent); margin: 1rem 0;
    padding: 8px 16px; background: rgba(56,189,248,0.04);
    font-size: 0.85rem; color: var(--muted);
  }}

  /* -- HR -- */
  .content hr {{
    border: none; height: 1px; background: var(--border);
    margin: 2rem 0;
  }}

  /* -- Source badge -- */
  .source-badge {{
    display: inline-block; font-size: 0.65rem; padding: 2px 8px;
    border-radius: 3px; background: rgba(56,189,248,0.1);
    color: var(--accent); font-family: var(--mono); margin-bottom: 1.2rem;
  }}
</style>
</head>
<body>

{nav_bar}

<nav class="sidebar" id="toc">
  <div class="toc-title">Contents</div>
  {toc_links}
</nav>

<div class="content">
  <span class="source-badge">Source: {source_file}</span>
  {body}
</div>

</body>
</html>
"""


def extract_toc(md_text: str) -> list[tuple[int, str, str]]:
    """Extract headings from markdown for TOC. Returns (level, id, text)."""
    import re
    toc = []
    for line in md_text.splitlines():
        m = re.match(r'^(#{1,4})\s+(.+)$', line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            # Strip markdown formatting from heading text
            clean = re.sub(r'[`*_\[\]()]', '', text)
            slug = re.sub(r'[^a-z0-9]+', '-', clean.lower()).strip('-')
            toc.append((level, slug, clean))
    return toc


def build_toc_html(toc: list[tuple[int, str, str]]) -> str:
    """Convert a TOC list into sidebar HTML links (h1–h3 only)."""
    links = []
    for level, slug, text in toc:
        depth_class = f"depth-{level}" if level >= 2 else ""
        if level <= 3:  # Only show h1-h3 in sidebar
            links.append(f'<a href="#{slug}" class="{depth_class}">{text}</a>')
    return "\n  ".join(links)


def render_md(md_path: Path, title: str) -> str:
    """Render a Markdown file to a styled HTML page with TOC sidebar."""
    md_text = md_path.read_text(encoding="utf-8")

    # Extract TOC before rendering
    toc = extract_toc(md_text)
    toc_html = build_toc_html(toc)

    # Render markdown to HTML
    extensions = ["tables", "fenced_code", "toc", "nl2br", "sane_lists"]
    body = markdown.markdown(
        md_text,
        extensions=extensions,
        extension_configs={"toc": {"permalink": False, "slugify": lambda value, separator: __import__("re").sub(r'[^a-z0-9]+', '-', __import__("re").sub(r'[`*_\[\]()]', '', value.lower())).strip('-')}},
    )

    return HTML_TEMPLATE.format(
        title=title,
        nav_bar=NAV_BAR,
        toc_links=toc_html,
        body=body,
        source_file=md_path.name,
    )


def main():
    """Render all configured Markdown docs to HTML in the docs/ directory."""
    rendered = 0
    for filename, title in MD_FILES.items():
        # Look in docs/ first, then project root
        md_path = DOCS_DIR / filename
        if not md_path.exists():
            md_path = PROJECT_ROOT / filename
        if not md_path.exists():
            print(f"  SKIP  {filename} (not found)")
            continue

        html_name = filename.replace(".md", ".html").lower()
        out_path = DOCS_DIR / html_name
        html = render_md(md_path, title)
        out_path.write_text(html, encoding="utf-8")
        print(f"  OK    {filename} -> {html_name}")
        rendered += 1

    print(f"\nRendered {rendered} file(s) to {DOCS_DIR}/")


if __name__ == "__main__":
    main()
