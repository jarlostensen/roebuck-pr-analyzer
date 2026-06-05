from fnmatch import fnmatch
from concurrent.futures import ThreadPoolExecutor, as_completed

from github.Repository import Repository

_MAX_WORKERS = 8


class SpecLoader:
    def __init__(self, repo: Repository, patterns: list[str]) -> None:
        self._repo = repo
        self._patterns = patterns

    def load_specs(self) -> dict[str, str]:
        """
        Return {file_path: content} for all files in the repo that match
        any of the configured glob patterns.
        """
        try:
            tree = self._repo.get_git_tree("HEAD", recursive=True)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch repo file tree: {e}") from e

        candidate_paths = [
            item.path
            for item in tree.tree
            if item.type == "blob" and any(fnmatch(item.path, p) for p in self._patterns)
        ]

        def _fetch(path: str) -> tuple[str, str] | None:
            try:
                contents = self._repo.get_contents(path)
                if isinstance(contents, list):
                    return None
                return path, contents.decoded_content.decode("utf-8", errors="replace")
            except Exception:
                return None

        matched: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch, p): p for p in candidate_paths}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    matched[result[0]] = result[1]

        return matched
