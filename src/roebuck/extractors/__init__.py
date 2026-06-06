"""Language extractor protocol and shared data types for project profile capture."""
from typing import Protocol, TypedDict


class ExtractedInterface(TypedDict):
    """A public interface extracted from a source file.

    Produced by :class:`LanguageExtractor` implementations. The ``source``
    tag (``"ast"`` or ``"claude"``) is added by the capture orchestrator when
    merging results — it is intentionally absent from this TypedDict so that
    extractors remain unaware of how their output will be tagged.

    Args:
        name: Identifier name as it appears in source.
        kind: Interface kind — ``"function"``, ``"class"``, ``"method"``,
            ``"endpoint"``, etc. The extractor chooses the most appropriate value.
        signature: Canonical, deterministic string representation. For AST-based
            extractors this is always the same for the same source; for Claude-based
            fallback it may vary across runs.
        module: Source file path containing this interface (typically the ``path``
            argument passed to :meth:`LanguageExtractor.extract`).
        is_public: Whether the extractor considers this interface public. The
            definition of "public" is the extractor's responsibility.
    """

    name: str
    kind: str
    signature: str
    module: str
    is_public: bool


class LanguageExtractor(Protocol):
    """Structural protocol for language-specific interface extraction.

    Implementations parse source code deterministically and return a list of
    :class:`ExtractedInterface` records. The same source always produces the
    same output for a given extractor.

    Attributes:
        extensions: File extensions this extractor handles, including the leading
            dot (e.g. ``frozenset({".py"})``).
        requires_toolchain: ``True`` if the extractor depends on an external
            binary (e.g. the Go compiler, libclang). ``False`` for stdlib-only
            implementations. The capture orchestrator checks this flag and warns
            when the required tool is absent, falling back to Claude extraction.
    """

    extensions: frozenset[str]
    requires_toolchain: bool

    def extract(self, source: str, path: str) -> list[ExtractedInterface]:
        """Extract public interfaces from a single source file.

        Args:
            source: Full text content of the source file.
            path: File path relative to the repository root; used as the
                ``module`` field on returned interfaces.

        Returns:
            List of extracted interfaces. Must return an empty list on parse
            errors — errors must never propagate to the caller.
        """
        ...
