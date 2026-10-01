"""Tests for github_tool.py"""

from typing import Any

import httpx
import pytest

from agent.tools.github_tool import GitHubTool
from ingestion.parsers.repo_analyzer import RepoAnalyzer

BASE = "https://api.github.com/repos/octo/demo"

REPO_JSON: dict[str, Any] = {
    "name": "demo",
    "description": "Demo repo",
    "language": "Python",
    "stargazers_count": 3,
    "forks_count": 1,
    "open_issues_count": 0,
    "pushed_at": "2026-09-16T00:00:00Z",
    "topics": [],
    "homepage": None,
    "default_branch": "main",
}

TREE_JSON: dict[str, Any] = {
    "truncated": False,
    "tree": [
        {"path": ".github", "type": "tree"},
        {"path": ".github/workflows", "type": "tree"},
        {"path": ".github/workflows/ci.yml", "type": "blob"},
        {"path": "pyproject.toml", "type": "blob"},
        {"path": "tests", "type": "tree"},
        {"path": "tests/unit/test_app.py", "type": "blob"},
    ],
}


def _response(method: str, url: str, status: int, json: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=json, request=httpx.Request(method, url))


@pytest.mark.unit
class TestGitHubTool:
    """Test suite for GitHubTool."""

    @pytest.fixture
    def fake_github(self, monkeypatch):
        """Patch httpx so GitHubTool talks to a canned GitHub API.

        Returns the dict of GET responses by URL, so a test can change one.
        """
        get_routes = {
            BASE: (200, REPO_JSON),
            f"{BASE}/git/trees/main": (200, TREE_JSON),
        }

        def fake_get(url, **kwargs):
            status, body = get_routes.get(url, (404, {"message": "Not Found"}))
            return _response("GET", url, status, body)

        def fake_head(url, **kwargs):
            return _response("HEAD", url, 200)

        monkeypatch.setattr(httpx, "get", fake_get)
        monkeypatch.setattr(httpx, "head", fake_head)
        return get_routes

    def test_file_structure_lists_every_tree_path(self, fake_github):
        """Every tree path comes back newline-joined under file_structure."""
        metadata = GitHubTool()._fetch_repo_metadata("octo", "demo")

        assert metadata["file_structure"].splitlines() == [
            entry["path"] for entry in TREE_JSON["tree"]
        ]

    def test_failed_tree_request_returns_empty_file_structure(self, fake_github):
        """A failing tree request degrades to an empty string, not an exception."""
        fake_github[f"{BASE}/git/trees/main"] = (409, {"message": "Git Repository is empty."})

        metadata = GitHubTool()._fetch_repo_metadata("octo", "demo")

        assert metadata["file_structure"] == ""
        assert metadata["name"] == "demo"

    def test_repo_analyzer_detects_tests_and_ci_from_tool_output(self, fake_github):
        """Issue #18: the tool's own output is enough for has_tests and has_ci."""
        repo_data = GitHubTool()._fetch_repo_metadata("octo", "demo")

        result = RepoAnalyzer().parse(repo_data)

        assert result.metadata["has_tests"] is True
        assert result.metadata["has_ci"] is True
