"""Tests for the REPORT stage."""

from pathlib import Path

from src.profile import run as profile_run
from src.validate import run as validate_run
from src.compare import run as compare_run
from src.report import run as report_run, REPORT_DIR


def test_report_generates_html(con, tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.REPORT_DIR", tmp_path)

    profiles = profile_run(con)
    validations = validate_run(con)
    comparisons = compare_run(con)

    report_path = report_run(profiles, validations, comparisons, con=con)
    assert report_path.exists()
    assert report_path.suffix == ".html"

    content = report_path.read_text()
    assert "CMS Claims Data Comparison Report" in content
    assert "Validation Results" in content


def test_report_includes_profile_data(con, tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.REPORT_DIR", tmp_path)

    profiles = profile_run(con)
    validations = validate_run(con)
    comparisons = compare_run(con)

    report_path = report_run(profiles, validations, comparisons, con=con)
    content = report_path.read_text()
    assert "beneficiary_summary" in content
    assert "carrier_claims" in content


def test_report_includes_validation_checks(con, tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.REPORT_DIR", tmp_path)

    profiles = profile_run(con)
    validations = validate_run(con)
    comparisons = compare_run(con)

    report_path = report_run(profiles, validations, comparisons, con=con)
    content = report_path.read_text()
    assert "orphan_claims_beneficiaries" in content
    assert "claims_after_death" in content


def test_report_with_comparisons(con_with_new, tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.REPORT_DIR", tmp_path)

    profiles = profile_run(con_with_new)
    validations = validate_run(con_with_new)
    comparisons = compare_run(con_with_new)

    report_path = report_run(profiles, validations, comparisons, con=con_with_new)
    content = report_path.read_text()
    assert "System Comparison" in content


def test_report_shows_no_new_data_message(con, tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.REPORT_DIR", tmp_path)

    profiles = profile_run(con)
    validations = validate_run(con)
    comparisons = []  # No comparisons

    report_path = report_run(profiles, validations, comparisons, con=con)
    content = report_path.read_text()
    assert "Not Yet Loaded" in content
