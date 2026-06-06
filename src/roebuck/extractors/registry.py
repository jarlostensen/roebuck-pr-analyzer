"""Extractor registry mapping file extensions to LanguageExtractor instances."""
from roebuck.extractors import LanguageExtractor
from roebuck.extractors.python import PythonExtractor

_python = PythonExtractor()

_REGISTRY: dict[str, LanguageExtractor] = {ext: _python for ext in _python.extensions}


def get_extractor(path: str) -> LanguageExtractor | None:
    """Return the registered extractor for this file's extension, or None.

    Looks up by the final extension component of ``path`` (e.g. ``.py`` for
    ``src/roebuck/cli.py``). Files with no extension (e.g. ``Makefile``) always
    return ``None``.

    Args:
        path: File path or filename (e.g. ``"src/foo.py"`` or ``"foo.py"``).

    Returns:
        The :class:`~roebuck.extractors.LanguageExtractor` registered for the
        file's extension, or ``None`` if no extractor is registered.
    """
    filename = path.rsplit("/", 1)[-1]
    if "." not in filename:
        return None
    suffix = "." + filename.rsplit(".", 1)[-1]
    return _REGISTRY.get(suffix)
