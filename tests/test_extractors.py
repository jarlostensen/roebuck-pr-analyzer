"""Unit tests for the LanguageExtractor protocol and PythonExtractor."""
from roebuck.extractors.python import PythonExtractor
from roebuck.extractors.registry import get_extractor


_EXTRACTOR = PythonExtractor()


# ---------------------------------------------------------------------------
# PythonExtractor — function extraction
# ---------------------------------------------------------------------------

def test_extracts_simple_function():
    source = "def hello() -> None: ..."
    results = _EXTRACTOR.extract(source, "mod.py")
    assert len(results) == 1
    assert results[0]["name"] == "hello"
    assert results[0]["kind"] == "function"
    assert results[0]["is_public"] is True
    assert results[0]["module"] == "mod.py"


def test_extracts_annotated_function_signature():
    source = "def charge(amount: int, currency: str) -> bool: ..."
    results = _EXTRACTOR.extract(source, "billing.py")
    assert results[0]["signature"] == "def charge(amount: int, currency: str) -> bool"


def test_extracts_unannotated_function():
    source = "def greet(name): ..."
    results = _EXTRACTOR.extract(source, "mod.py")
    assert results[0]["signature"] == "def greet(name)"


def test_extracts_async_function():
    source = "async def fetch(url: str) -> bytes: ..."
    results = _EXTRACTOR.extract(source, "client.py")
    assert results[0]["signature"] == "async def fetch(url: str) -> bytes"
    assert results[0]["kind"] == "function"


def test_extracts_function_with_default_arg():
    source = "def greet(name: str = 'world') -> str: ..."
    results = _EXTRACTOR.extract(source, "greet.py")
    sig = results[0]["signature"]
    assert "greet" in sig
    assert "name: str" in sig


def test_decorator_stripped_from_signature():
    source = "@staticmethod\ndef compute(x: int) -> int: ..."
    results = _EXTRACTOR.extract(source, "mod.py")
    assert results[0]["signature"].startswith("def compute")


def test_excludes_private_function():
    source = "def _helper() -> None: ...\ndef __dunder__() -> None: ..."
    results = _EXTRACTOR.extract(source, "mod.py")
    assert results == []


def test_extracts_public_and_excludes_private():
    source = "def public_fn() -> int: ...\ndef _private_fn() -> int: ..."
    results = _EXTRACTOR.extract(source, "mod.py")
    assert len(results) == 1
    assert results[0]["name"] == "public_fn"


# ---------------------------------------------------------------------------
# PythonExtractor — class extraction
# ---------------------------------------------------------------------------

def test_extracts_plain_class():
    source = "class Foo: pass"
    results = _EXTRACTOR.extract(source, "mod.py")
    assert results[0]["name"] == "Foo"
    assert results[0]["kind"] == "class"
    assert results[0]["signature"] == "class Foo"


def test_extracts_class_with_bases():
    source = "class Bar(Base, Mixin): pass"
    results = _EXTRACTOR.extract(source, "mod.py")
    sig = results[0]["signature"]
    assert "Bar" in sig
    assert "Base" in sig
    assert "Mixin" in sig


def test_excludes_private_class():
    source = "class _Internal: pass"
    results = _EXTRACTOR.extract(source, "mod.py")
    assert results == []


def test_decorator_stripped_from_class_signature():
    source = "@dataclass\nclass Point:\n    x: int"
    results = _EXTRACTOR.extract(source, "mod.py")
    assert results[0]["signature"] == "class Point"


# ---------------------------------------------------------------------------
# PythonExtractor — module-level scope only
# ---------------------------------------------------------------------------

def test_does_not_extract_nested_functions():
    source = """
def outer() -> None:
    def inner() -> None:
        pass
"""
    results = _EXTRACTOR.extract(source, "mod.py")
    assert len(results) == 1
    assert results[0]["name"] == "outer"


def test_does_not_extract_class_methods():
    source = """
class MyClass:
    def method(self) -> None:
        pass
    def another(self) -> str:
        return "x"
"""
    results = _EXTRACTOR.extract(source, "mod.py")
    assert len(results) == 1
    assert results[0]["kind"] == "class"
    assert results[0]["name"] == "MyClass"


def test_multiple_top_level_items():
    source = """
def foo() -> int: ...
class Bar: pass
def baz(x: str) -> None: ...
"""
    results = _EXTRACTOR.extract(source, "mod.py")
    names = [r["name"] for r in results]
    assert names == ["foo", "Bar", "baz"]


# ---------------------------------------------------------------------------
# PythonExtractor — error handling
# ---------------------------------------------------------------------------

def test_syntax_error_returns_empty_list(caplog):
    source = "def broken(: ..."
    results = _EXTRACTOR.extract(source, "broken.py")
    assert results == []


def test_empty_source_returns_empty_list():
    assert _EXTRACTOR.extract("", "empty.py") == []


def test_imports_only_returns_empty_list():
    source = "import os\nfrom pathlib import Path"
    assert _EXTRACTOR.extract(source, "imports.py") == []


# ---------------------------------------------------------------------------
# PythonExtractor — metadata
# ---------------------------------------------------------------------------

def test_extensions():
    assert ".py" in PythonExtractor.extensions


def test_requires_no_toolchain():
    assert PythonExtractor.requires_toolchain is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_returns_python_extractor_for_py():
    extractor = get_extractor("src/main.py")
    assert extractor is not None
    assert isinstance(extractor, PythonExtractor)


def test_registry_returns_python_extractor_for_bare_filename():
    assert get_extractor("models.py") is not None


def test_registry_returns_none_for_go():
    assert get_extractor("main.go") is None


def test_registry_returns_none_for_ts():
    assert get_extractor("app.ts") is None


def test_registry_returns_none_for_no_extension():
    assert get_extractor("Makefile") is None


def test_registry_returns_none_for_no_extension_in_path():
    assert get_extractor("src/Makefile") is None
