import re
from datetime import datetime, timedelta, timezone

from github import Github, GithubException, RateLimitExceededException
from github.Repository import Repository

from roebuck.config import GitHubConfig
from roebuck.models import (
    ChurnEntry,
    FileCommit,
    FileHistoryData,
    PRData,
    ReleaseData,
)


def _rate_limit_error(gh: Github) -> RuntimeError:
    """Return a RuntimeError with the API reset time if available."""
    try:
        reset_at = gh.get_rate_limit().rate.reset
        now = datetime.now(timezone.utc)
        wait_secs = max(0, int((reset_at - now).total_seconds()))
        return RuntimeError(
            f"GitHub API rate limit exceeded. "
            f"Resets at {reset_at.strftime('%H:%M:%S UTC')} (~{wait_secs}s from now)."
        )
    except Exception:
        return RuntimeError("GitHub API rate limit exceeded. Wait and retry.")


class GitHubClient:
    def __init__(self, cfg: GitHubConfig) -> None:
        self._gh = Github(cfg.token)
        try:
            self._repo: Repository = self._gh.get_repo(cfg.repo)
        except RateLimitExceededException:
            raise _rate_limit_error(self._gh)
        except GithubException as e:
            if e.status == 401:
                raise RuntimeError(
                    "GitHub token is invalid or expired. "
                    "Update the token in config.toml or set the GITHUB_TOKEN environment variable."
                ) from e
            if e.status == 404:
                raise RuntimeError(
                    f"Repository '{cfg.repo}' not found. "
                    "Check that the repo name in config.toml is correct (owner/repo-name) "
                    "and that your token has read access to it."
                ) from e
            raise RuntimeError(f"Failed to connect to repository '{cfg.repo}': {e.data}") from e

    # ------------------------------------------------------------------
    # PR
    # ------------------------------------------------------------------

    def get_pr(self, number: int) -> PRData:
        try:
            pr = self._repo.get_pull(number)
        except RateLimitExceededException:
            raise _rate_limit_error(self._gh)
        except GithubException as e:
            raise RuntimeError(f"Failed to fetch PR #{number}: {e.data}") from e

        files = list(pr.get_files())
        # Reconstruct unified diff from individual file patches
        diff_parts = []
        for f in files:
            if f.patch:
                diff_parts.append(
                    f"--- a/{f.filename}\n+++ b/{f.filename}\n{f.patch}"
                )
        diff = "\n".join(diff_parts)

        return PRData(
            number=number,
            title=pr.title,
            body=pr.body or "",
            author=pr.user.login,
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            diff=diff,
            changed_files=[f.filename for f in files],
            additions=pr.additions,
            deletions=pr.deletions,
            commits=[c.commit.message for c in pr.get_commits()],
        )

    # ------------------------------------------------------------------
    # File history
    # ------------------------------------------------------------------

    def get_file_history(self, path: str, defect_keywords: list[str]) -> FileHistoryData:
        pattern = re.compile("|".join(re.escape(k) for k in defect_keywords), re.IGNORECASE)
        try:
            commits = list(self._repo.get_commits(path=path))
        except RateLimitExceededException:
            raise _rate_limit_error(self._gh)
        except GithubException as e:
            raise RuntimeError(f"Failed to fetch history for {path}: {e.data}") from e

        return FileHistoryData(
            path=path,
            commits=[
                FileCommit(
                    sha=c.sha[:8],
                    message=c.commit.message,
                    author=c.commit.author.name,
                    date=c.commit.author.date,
                    is_defect=bool(pattern.search(c.commit.message)),
                )
                for c in commits
            ],
        )

    # ------------------------------------------------------------------
    # Churn
    # ------------------------------------------------------------------

    def get_churn_data(
        self,
        lookback_days: int,
        defect_keywords: list[str],
        min_threshold: int,
        max_commits: int = 500,
    ) -> list[ChurnEntry]:
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        pattern = re.compile("|".join(re.escape(k) for k in defect_keywords), re.IGNORECASE)
        file_flags: dict[str, list[bool]] = {}
        file_authors: dict[str, set[str]] = {}

        # Churn analysis fetches every commit + its file list — one API call per
        # commit on active repos. Check quota before starting.
        try:
            remaining = self._gh.get_rate_limit().rate.remaining
            if remaining < 100:
                raise _rate_limit_error(self._gh)
        except RateLimitExceededException:
            raise _rate_limit_error(self._gh)

        try:
            processed = 0
            for commit in self._repo.get_commits(since=since):
                if processed >= max_commits:
                    break
                # Periodic mid-run check every 50 commits; bail with partial
                # results rather than crashing when quota runs low.
                if processed > 0 and processed % 50 == 0:
                    try:
                        if self._gh.get_rate_limit().rate.remaining < 20:
                            break
                    except Exception:
                        pass
                is_defect = bool(pattern.search(commit.commit.message))
                author = commit.commit.author.name or "unknown"
                for f in commit.files:
                    file_flags.setdefault(f.filename, []).append(is_defect)
                    file_authors.setdefault(f.filename, set()).add(author)
                processed += 1
        except RateLimitExceededException:
            raise _rate_limit_error(self._gh)
        except GithubException as e:
            raise RuntimeError(f"Failed to fetch commits: {e.data}") from e

        results = []
        for path, flags in file_flags.items():
            if len(flags) < min_threshold:
                continue
            defect_count = sum(flags)
            results.append(
                ChurnEntry(
                    path=path,
                    total_commits=len(flags),
                    defect_commits=defect_count,
                    defect_ratio=defect_count / len(flags),
                    unique_authors=len(file_authors.get(path, set())),
                )
            )
        return sorted(results, key=lambda e: e.total_commits, reverse=True)

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    def get_release_diff(self, tag: str, base: str | None = None) -> ReleaseData:
        # Resolve base to the previous release tag if not provided
        if base is None:
            base = self._previous_tag(tag)

        try:
            comparison = self._repo.compare(base, tag)
        except RateLimitExceededException:
            raise _rate_limit_error(self._gh)
        except GithubException as e:
            raise RuntimeError(f"Failed to compare {base}...{tag}: {e.data}") from e

        files = list(comparison.files)
        diff_parts = []
        for f in files:
            if f.patch:
                diff_parts.append(
                    f"--- a/{f.filename}\n+++ b/{f.filename}\n{f.patch}"
                )

        # Fetch tag date from the release or tag object
        tag_date: datetime | None = None
        try:
            release = self._repo.get_release(tag)
            tag_date = release.published_at
        except GithubException:
            try:
                git_tag = self._repo.get_git_ref(f"tags/{tag}")
                tag_obj = self._repo.get_git_tag(git_tag.object.sha)
                tag_date = tag_obj.tagger.date if tag_obj.tagger else None
            except GithubException:
                pass

        return ReleaseData(
            tag=tag,
            base_tag=base,
            diff="\n".join(diff_parts),
            changed_files=[f.filename for f in files],
            additions=sum(f.additions for f in files),
            deletions=sum(f.deletions for f in files),
            tag_date=tag_date,
        )

    def _previous_tag(self, tag: str) -> str:
        tags = [t.name for t in self._repo.get_tags()]
        if tag not in tags:
            raise ValueError(f"Tag '{tag}' not found in repository.")
        idx = tags.index(tag)
        if idx + 1 >= len(tags):
            raise ValueError(f"No previous tag found before '{tag}'.")
        return tags[idx + 1]

    # ------------------------------------------------------------------
    # Expose underlying repo for SpecLoader
    # ------------------------------------------------------------------

    @property
    def repo(self) -> Repository:
        return self._repo
