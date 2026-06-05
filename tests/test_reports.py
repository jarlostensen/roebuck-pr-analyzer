"""Unit tests for MarkdownReportWriter and _strip_code_fences."""
import re
from pathlib import Path

import pytest

from roebuck.claude_client import _strip_code_fences
from roebuck.reports.markdown import MarkdownReportWriter


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------

def test_strip_plain_json_fence():
    raw = "```\n{\"key\": 1}\n```"
    assert _strip_code_fences(raw) == '{"key": 1}'


def test_strip_json_labelled_fence():
    raw = "```json\n{\"key\": 1}\n```"
    assert _strip_code_fences(raw) == '{"key": 1}'


def test_no_fence_passthrough():
    raw = '{"key": 1}'
    assert _strip_code_fences(raw) == raw


def test_strip_multiline_json():
    raw = "```json\n{\n  \"a\": 1,\n  \"b\": 2\n}\n```"
    result = _strip_code_fences(raw)
    assert result.startswith("{")
    assert result.endswith("}")


def test_unclosed_fence_strips_first_line():
    # If closing ``` is missing, still drops the opening fence line
    raw = "```json\n{\"key\": 1}"
    result = _strip_code_fences(raw)
    assert not result.startswith("```")


# ---------------------------------------------------------------------------
# MarkdownReportWriter
# ---------------------------------------------------------------------------

@pytest.fixture
def writer(tmp_path: Path) -> MarkdownReportWriter:
    return MarkdownReportWriter(tmp_path)


def test_write_creates_file(writer: MarkdownReportWriter, tmp_path: Path):
    path = writer.write("pr-1", [("Summary", "All good.")])
    assert path.exists()
    assert path.suffix == ".md"


def test_write_filename_contains_slug(writer: MarkdownReportWriter):
    path = writer.write("churn", [("Section", "data")])
    assert "churn" in path.name


def test_write_filename_has_timestamp(writer: MarkdownReportWriter):
    path = writer.write("pr-2", [("S", "c")])
    # Expect YYYYMMDD-HHMMSS-microseconds pattern
    assert re.search(r"\d{8}-\d{6}-\d+", path.name)


def test_write_unique_filenames(writer: MarkdownReportWriter):
    paths = [writer.write("test", [("S", "c")]) for _ in range(5)]
    assert len(set(paths)) == len(paths), "Filenames should be unique"


def test_write_contains_heading(writer: MarkdownReportWriter):
    path = writer.write("pr-3", [("Risk Assessment", "High risk.")])
    content = path.read_text(encoding="utf-8")
    assert "## Risk Assessment" in content
    assert "High risk." in content


def test_write_contains_title(writer: MarkdownReportWriter):
    path = writer.write("pr-3", [("S", "c")])
    content = path.read_text(encoding="utf-8")
    assert "# Roebuck Report: pr-3" in content


def test_write_multiple_sections(writer: MarkdownReportWriter):
    sections = [("Alpha", "content A"), ("Beta", "content B"), ("Gamma", "content C")]
    path = writer.write("multi", sections)
    content = path.read_text(encoding="utf-8")
    for heading, body in sections:
        assert f"## {heading}" in content
        assert body in content


def test_write_creates_output_dir(tmp_path: Path):
    subdir = tmp_path / "nested" / "reports"
    writer = MarkdownReportWriter(subdir)
    path = writer.write("test", [("S", "c")])
    assert path.exists()
