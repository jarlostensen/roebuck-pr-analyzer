"""Unit tests for GitHubClient — all GitHub API calls are mocked."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException, RateLimitExceededException

from roebuck.config import GitHubConfig
from roebuck.github_client import GitHubClient, _rate_limit_error


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_gh():
    return MagicMock()


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def client(mock_gh, mock_repo):
    """GitHubClient with _gh and _repo pre-wired, bypassing __init__ network calls."""
    c = GitHubClient.__new__(GitHubClient)
    c._gh = mock_gh
    c._repo = mock_repo
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file(filename, patch=None):
    f = MagicMock()
    f.filename = filename
    f.patch = patch
    return f


def _commit_msg(message):
    c = MagicMock()
    c.commit.message = message
    return c


def _gh_commit(sha, message, author, date):
    c = MagicMock()
    c.sha = sha
    c.commit.message = message
    c.commit.author.name = author
    c.commit.author.date = date
    return c


def _churn_commit(message, filenames):
    c = MagicMock()
    c.commit.message = message
    c.files = [MagicMock(filename=f) for f in filenames]
    return c


def _tag(name):
    t = MagicMock()
    t.name = name
    return t


def _release_file(filename, additions, deletions, patch=None):
    f = MagicMock()
    f.filename = filename
    f.additions = additions
    f.deletions = deletions
    f.patch = patch
    return f


_NOW = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# GitHubClient.__init__
# ---------------------------------------------------------------------------

def test_init_repo_not_found_raises_clear_error():
    with patch("roebuck.github_client.Github") as MockGithub:
        MockGithub.return_value.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, {})
        cfg = GitHubConfig(token="tok", repo="bad/repo")
        with pytest.raises(RuntimeError, match="not found"):
            GitHubClient(cfg)


def test_init_bad_credentials_raises_clear_error():
    with patch("roebuck.github_client.Github") as MockGithub:
        MockGithub.return_value.get_repo.side_effect = GithubException(401, {"message": "Bad credentials"}, {})
        cfg = GitHubConfig(token="tok", repo="owner/repo")
        with pytest.raises(RuntimeError, match="invalid or expired"):
            GitHubClient(cfg)


def test_init_other_github_error_raises():
    with patch("roebuck.github_client.Github") as MockGithub:
        MockGithub.return_value.get_repo.side_effect = GithubException(500, {"message": "Server Error"}, {})
        cfg = GitHubConfig(token="tok", repo="owner/repo")
        with pytest.raises(RuntimeError, match="Failed to connect"):
            GitHubClient(cfg)


# ---------------------------------------------------------------------------
# _rate_limit_error
# ---------------------------------------------------------------------------

def test_rate_limit_error_includes_reset_time(mock_gh):
    mock_gh.get_rate_limit.return_value.rate.reset = _NOW
    err = _rate_limit_error(mock_gh)
    assert "12:00:00 UTC" in str(err)
    assert "rate limit" in str(err).lower()


def test_rate_limit_error_fallback_on_exception(mock_gh):
    mock_gh.get_rate_limit.side_effect = Exception("network error")
    err = _rate_limit_error(mock_gh)
    assert "rate limit" in str(err).lower()


# ---------------------------------------------------------------------------
# get_pr
# ---------------------------------------------------------------------------

def test_get_pr_returns_pr_data(client, mock_repo):
    pr = MagicMock()
    pr.title = "Add feature"
    pr.body = "Some description"
    pr.user.login = "alice"
    pr.base.ref = "main"
    pr.head.ref = "feature/x"
    pr.additions = 10
    pr.deletions = 5
    pr.get_files.return_value = [
        _file("src/foo.py", "@@ -1 +1,2 @@ +line"),
        _file("README.md", None),  # no patch — excluded from diff
    ]
    pr.get_commits.return_value = [_commit_msg("First commit"), _commit_msg("Fix tests")]
    mock_repo.get_pull.return_value = pr

    result = client.get_pr(42)

    assert result.number == 42
    assert result.title == "Add feature"
    assert result.author == "alice"
    assert result.base_branch == "main"
    assert result.additions == 10
    assert result.deletions == 5
    assert "src/foo.py" in result.changed_files
    assert "README.md" in result.changed_files
    assert "src/foo.py" in result.diff
    assert "README.md" not in result.diff  # no patch → not included
    assert result.commits == ["First commit", "Fix tests"]


def test_get_pr_rate_limit_raises(client, mock_repo, mock_gh):
    mock_repo.get_pull.side_effect = RateLimitExceededException(403, {}, {})
    mock_gh.get_rate_limit.return_value.rate.reset = _NOW
    with pytest.raises(RuntimeError, match="rate limit"):
        client.get_pr(1)


def test_get_pr_not_found_raises(client, mock_repo):
    mock_repo.get_pull.side_effect = GithubException(404, {"message": "Not Found"}, {})
    with pytest.raises(RuntimeError, match="Failed to fetch PR #99"):
        client.get_pr(99)


# ---------------------------------------------------------------------------
# get_file_history
# ---------------------------------------------------------------------------

def test_get_file_history_returns_commits(client, mock_repo):
    mock_repo.get_commits.return_value = [
        _gh_commit("abc12345abcd", "fix: null pointer", "alice", _NOW),
        _gh_commit("def67890efgh", "Add unit tests", "bob", _NOW),
    ]

    result = client.get_file_history("src/foo.py", ["fix", "bug"])

    assert result.path == "src/foo.py"
    assert len(result.commits) == 2
    assert result.commits[0].sha == "abc12345"  # truncated to 8
    assert result.commits[0].is_defect is True
    assert result.commits[1].is_defect is False


def test_get_file_history_defect_pattern_case_insensitive(client, mock_repo):
    mock_repo.get_commits.return_value = [
        _gh_commit("aaa", "BUG: critical issue", "alice", _NOW),
    ]
    result = client.get_file_history("src/foo.py", ["bug"])
    assert result.commits[0].is_defect is True


def test_get_file_history_rate_limit_raises(client, mock_repo, mock_gh):
    mock_repo.get_commits.side_effect = RateLimitExceededException(403, {}, {})
    mock_gh.get_rate_limit.return_value.rate.reset = _NOW
    with pytest.raises(RuntimeError, match="rate limit"):
        client.get_file_history("src/foo.py", ["fix"])


def test_get_file_history_github_exception_raises(client, mock_repo):
    mock_repo.get_commits.side_effect = GithubException(500, {"message": "Server Error"}, {})
    with pytest.raises(RuntimeError, match="Failed to fetch history"):
        client.get_file_history("src/bar.py", ["fix"])


# ---------------------------------------------------------------------------
# get_churn_data
# ---------------------------------------------------------------------------

def test_get_churn_data_happy_path(client, mock_repo, mock_gh):
    mock_gh.get_rate_limit.return_value.rate.remaining = 500
    mock_repo.get_commits.return_value = [
        _churn_commit("fix: bug in parser", ["src/parser.py", "src/lexer.py"]),
        _churn_commit("fix: another bug",   ["src/parser.py"]),
        _churn_commit("Add feature",         ["src/parser.py", "src/utils.py"]),
    ]

    results = client.get_churn_data(30, ["fix", "bug"], min_threshold=2, max_commits=100)

    parser = next(e for e in results if e.path == "src/parser.py")
    assert parser.total_commits == 3
    assert parser.defect_commits == 2
    assert pytest.approx(parser.defect_ratio) == 2 / 3
    # src/utils.py only has 1 commit — below threshold=2
    assert not any(e.path == "src/utils.py" for e in results)


def test_get_churn_data_pre_check_rate_limit_raises(client, mock_gh):
    mock_gh.get_rate_limit.return_value.rate.remaining = 50  # below 100
    mock_gh.get_rate_limit.return_value.rate.reset = _NOW
    with pytest.raises(RuntimeError, match="rate limit"):
        client.get_churn_data(30, ["fix"], min_threshold=3, max_commits=100)


def test_get_churn_data_mid_run_rate_limit_raises(client, mock_repo, mock_gh):
    mock_gh.get_rate_limit.return_value.rate.remaining = 200
    mock_gh.get_rate_limit.return_value.rate.reset = _NOW
    mock_repo.get_commits.side_effect = RateLimitExceededException(403, {}, {})
    with pytest.raises(RuntimeError, match="rate limit"):
        client.get_churn_data(30, ["fix"], min_threshold=3, max_commits=100)


def test_get_churn_data_max_commits_caps_processing(client, mock_repo, mock_gh):
    mock_gh.get_rate_limit.return_value.rate.remaining = 500
    # 10 commits, each touching a unique file
    mock_repo.get_commits.return_value = [
        _churn_commit(f"commit {i}", [f"file{i}.py"]) for i in range(10)
    ]

    results = client.get_churn_data(30, ["fix"], min_threshold=1, max_commits=3)

    # Only 3 commits processed → 3 unique files, each with 1 commit
    assert len(results) == 3
    assert sum(e.total_commits for e in results) == 3


def test_get_churn_data_sorted_by_total_commits_descending(client, mock_repo, mock_gh):
    mock_gh.get_rate_limit.return_value.rate.remaining = 500
    mock_repo.get_commits.return_value = [
        _churn_commit("Add feature", ["low.py"]),
        _churn_commit("fix bug",     ["high.py"]),
        _churn_commit("fix issue",   ["high.py"]),
        _churn_commit("refactor",    ["high.py"]),
    ]

    results = client.get_churn_data(30, ["fix"], min_threshold=1, max_commits=100)
    assert results[0].path == "high.py"
    assert results[0].total_commits == 3


# ---------------------------------------------------------------------------
# get_release_diff
# ---------------------------------------------------------------------------

def test_get_release_diff_explicit_base(client, mock_repo):
    comparison = MagicMock()
    comparison.files = [
        _release_file("src/main.py", 10, 3, "@@ -1,1 +1,2 @@\n+new line"),
        _release_file("docs/index.md", 5, 0, None),  # no patch
    ]
    mock_repo.compare.return_value = comparison
    mock_repo.get_release.side_effect = GithubException(404, {}, {})

    result = client.get_release_diff("v1.1.0", base="v1.0.0")

    mock_repo.compare.assert_called_once_with("v1.0.0", "v1.1.0")
    assert result.tag == "v1.1.0"
    assert result.base_tag == "v1.0.0"
    assert result.additions == 15
    assert result.deletions == 3
    assert "src/main.py" in result.changed_files
    assert "src/main.py" in result.diff
    assert "docs/index.md" in result.changed_files
    assert "docs/index.md" not in result.diff  # no patch


def test_get_release_diff_auto_base_uses_previous_tag(client, mock_repo):
    mock_repo.get_tags.return_value = [_tag("v2.0.0"), _tag("v1.0.0")]
    comparison = MagicMock()
    comparison.files = []
    mock_repo.compare.return_value = comparison
    mock_repo.get_release.side_effect = GithubException(404, {}, {})

    client.get_release_diff("v2.0.0")  # base resolved automatically

    mock_repo.compare.assert_called_once_with("v1.0.0", "v2.0.0")


def test_get_release_diff_rate_limit_raises(client, mock_repo, mock_gh):
    mock_repo.compare.side_effect = RateLimitExceededException(403, {}, {})
    mock_gh.get_rate_limit.return_value.rate.reset = _NOW
    with pytest.raises(RuntimeError, match="rate limit"):
        client.get_release_diff("v1.1.0", base="v1.0.0")


def test_get_release_diff_github_exception_raises(client, mock_repo):
    mock_repo.compare.side_effect = GithubException(404, {"message": "Not Found"}, {})
    with pytest.raises(RuntimeError, match="Failed to compare"):
        client.get_release_diff("v1.1.0", base="v1.0.0")


# ---------------------------------------------------------------------------
# _previous_tag
# ---------------------------------------------------------------------------

def test_previous_tag_returns_predecessor(client, mock_repo):
    mock_repo.get_tags.return_value = [_tag("v2.0.0"), _tag("v1.0.0"), _tag("v0.9.0")]
    assert client._previous_tag("v2.0.0") == "v1.0.0"
    assert client._previous_tag("v1.0.0") == "v0.9.0"


def test_previous_tag_not_in_repo_raises(client, mock_repo):
    mock_repo.get_tags.return_value = [_tag("v1.0.0")]
    with pytest.raises(ValueError, match="Tag 'v9.9.9' not found"):
        client._previous_tag("v9.9.9")


def test_previous_tag_no_predecessor_raises(client, mock_repo):
    mock_repo.get_tags.return_value = [_tag("v1.0.0")]
    with pytest.raises(ValueError, match="No previous tag"):
        client._previous_tag("v1.0.0")
