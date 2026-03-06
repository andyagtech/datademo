#!/usr/bin/env python3
"""Post-upload verification: check that all expected assets are reachable on CloudFront.

Usage:
    python .deploy/verify_upload.py
"""

import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://ddmmvtx76d1f8.cloudfront.net"

# Every file that upload_to_s3.sh deploys
EXPECTED_PATHS = [
    # 1. Root redirect
    "index.html",

    # 2. docs/ HTML
    "docs/index.html",
    "docs/architecture.html",
    "docs/data_dictionary.html",
    "docs/feedback.html",
    "docs/parquet_viewer.html",
    "docs/pipeline.html",
    "docs/requirements_traceability.html",
    "docs/reviewer_readme.html",
    "docs/schema_explorer.html",
    "docs/solution.html",
    "docs/sql_explorer.html",

    # 2b. docs/ JS
    "docs/cached-answers.js",
    "docs/chat-widget.js",

    # 3. screenshots/
    "screenshots/screenshot_1.png",
    "screenshots/screenshot_2.png",
    "screenshots/screenshot_3.png",
    "screenshots/screenshot_4.png",
    "screenshots/screenshot_5.png",
    "screenshots/screenshot_6.png",
    "screenshots/screenshot_7.png",
    "screenshots/screenshot_8.png",
    "screenshots/screenshot_9.png",
    "screenshots/screenshot_10.png",
    "screenshots/screenshot_11.png",
    "screenshots/screenshot_12.png",

    # 4. reports/
    "reports/comparison_report.html",

    # 5. reports/exports/
    "reports/exports/_discrepancy_detail.csv",
    "reports/exports/_discrepancy_detail.parquet",
    "reports/exports/_financial_recon.csv",
    "reports/exports/_financial_recon.parquet",
    "reports/exports/_match_beneficiary.csv",
    "reports/exports/_match_beneficiary.parquet",
    "reports/exports/_match_claims.csv",
    "reports/exports/_match_claims.parquet",

    # 6. reports/report_data.json
    "reports/report_data.json",
]

# Expected Content-Type prefixes for each extension
CONTENT_TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".csv": "text/csv",         # or binary/octet-stream from S3
    ".parquet": None,           # no specific expectation
}


def check_url(path: str) -> dict:
    """HEAD-request a single URL and return status info."""
    url = f"{BASE_URL}/{path}"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            content_length = resp.headers.get("Content-Length", "?")
            return {
                "path": path,
                "status": status,
                "content_type": content_type,
                "size": content_length,
                "ok": True,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {
            "path": path,
            "status": e.code,
            "content_type": "",
            "size": "0",
            "ok": False,
            "error": f"HTTP {e.code} {e.reason}",
        }
    except Exception as e:
        return {
            "path": path,
            "status": 0,
            "content_type": "",
            "size": "0",
            "ok": False,
            "error": str(e),
        }


def check_content_type(path: str, actual: str) -> str | None:
    """Return a warning string if Content-Type doesn't match expectation."""
    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    expected = CONTENT_TYPES.get(ext)
    if expected and not actual.startswith(expected):
        return f"expected {expected}, got {actual}"
    return None


def main():
    print(f"Verifying {len(EXPECTED_PATHS)} assets on {BASE_URL}\n")

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(check_url, p): p for p in EXPECTED_PATHS}
        for future in as_completed(futures):
            results.append(future.result())

    # Sort by original order
    path_order = {p: i for i, p in enumerate(EXPECTED_PATHS)}
    results.sort(key=lambda r: path_order[r["path"]])

    # Print results
    ok_count = 0
    warn_count = 0
    fail_count = 0

    for r in results:
        if r["ok"]:
            ct_warn = check_content_type(r["path"], r["content_type"])
            if ct_warn:
                print(f"  ⚠  {r['path']}  — {ct_warn}")
                warn_count += 1
            else:
                print(f"  ✓  {r['path']}  ({r['size']} bytes)")
                ok_count += 1
        else:
            print(f"  ✗  {r['path']}  — {r['error']}")
            fail_count += 1

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  ✓ {ok_count} OK    ⚠ {warn_count} warnings    ✗ {fail_count} failures")
    print(f"  Total: {len(EXPECTED_PATHS)} assets checked")
    print(f"{'=' * 60}")

    if fail_count > 0:
        print("\n❌ VERIFICATION FAILED — missing assets detected!")
        sys.exit(1)
    elif warn_count > 0:
        print("\n⚠️  All assets reachable but some Content-Type mismatches.")
        sys.exit(0)
    else:
        print("\n✅ All assets verified successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
