"""Python AST-based language extractor using the stdlib ``ast`` module."""
import ast
import logging

from roebuck.extractors import ExtractedInterface

logger = logging.getLogger(__name__)


class PythonExtractor:
    """Extracts public module-level functions and classes from Python source.

    Uses the stdlib ``ast`` module — zero external dependencies.

    Scope (initial version):
    - Module-level ``def``, ``async def``, and ``class`` statements only.
    - Names starting with ``_`` are excluded (private by convention).
    - Class methods, nested functions, and ``__all__``-based exports are not
      expanded at this stage; these are refinements for a later iteration.

    Attributes:
        extensions: Handles ``.py`` files.
        requires_toolchain: ``False`` — stdlib ``ast`` only.
    """

    extensions: frozenset[str] = frozenset({".py"})
    requires_toolchain: bool = False

    def extract(self, source: str, path: str) -> list[ExtractedInterface]:
        """Extract public module-level functions and classes from Python source.

        Args:
            source: Full Python source text.
            path: File path used as the ``module`` field on returned interfaces.

        Returns:
            List of :class:`~roebuck.extractors.ExtractedInterface` records.
            Returns an empty list if ``source`` contains a syntax error or is
            empty.
        """
        # Strip BOM and null bytes that can arrive from some API responses.
        source = source.lstrip("﻿").replace("\x00", "")
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logger.warning("Syntax error parsing %s (%s); skipping extraction", path, e)
            return []

        results: list[ExtractedInterface] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                results.append(
                    ExtractedInterface(
                        name=node.name,
                        kind="function",
                        signature=_function_signature(node),
                        module=path,
                        is_public=True,
                    )
                )
            elif isinstance(node, ast.ClassDef):
                if node.name.startswith("_"):
                    continue
                results.append(
                    ExtractedInterface(
                        name=node.name,
                        kind="class",
                        signature=_class_signature(node),
                        module=path,
                        is_public=True,
                    )
                )
        return results


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Reconstruct a canonical type-annotated function signature from an AST node.

    Decorators are stripped so the signature is stable across decorator changes.
    Uses ``ast.unparse()`` for canonical formatting (available in Python 3.9+).

    Args:
        node: A ``FunctionDef`` or ``AsyncFunctionDef`` AST node.

    Returns:
        Signature string, e.g. ``def charge(amount: Decimal, currency: str) -> Receipt``.
    """
    if isinstance(node, ast.AsyncFunctionDef):
        dummy = ast.AsyncFunctionDef(
            name=node.name,
            args=node.args,
            body=[ast.Pass()],
            decorator_list=[],
            returns=node.returns,
            type_comment=None,
        )
    else:
        dummy = ast.FunctionDef(
            name=node.name,
            args=node.args,
            body=[ast.Pass()],
            decorator_list=[],
            returns=node.returns,
            type_comment=None,
        )
    # ast.unparse() requires lineno/col_offset on the node; fix_missing_locations
    # sets them recursively on any node that lacks them.
    ast.fix_missing_locations(dummy)
    # "def foo(x: int) -> str:\n    pass" — take the first line, strip trailing ":"
    return ast.unparse(dummy).splitlines()[0].rstrip(":")


def _class_signature(node: ast.ClassDef) -> str:
    """Reconstruct a canonical class definition line from an AST node.

    Decorators are stripped. Base classes and keyword arguments are preserved.

    Args:
        node: A ``ClassDef`` AST node.

    Returns:
        Signature string, e.g. ``class Foo(Base, Mixin)`` or ``class Foo``.
    """
    dummy = ast.ClassDef(
        name=node.name,
        bases=node.bases,
        keywords=node.keywords,
        body=[ast.Pass()],
        decorator_list=[],
    )
    # "class Foo(Base):\n    pass" — take the first line, strip trailing ":"
    return ast.unparse(dummy).splitlines()[0].rstrip(":")
