"""
sandbox_runner.py - executes ONE LLM-written script inside a locked-down interpreter.

Invoked by the Code Mode Engine as:   python -I sandbox_runner.py   (script on stdin)

Layers of defence (any one failing still leaves the others):
 1. Static AST validation: import allow-list, forbidden names/builtins, no
    underscore attribute access (blocks __class__/__globals__ escapes), no
    format-string attribute tricks, no `while True`.
 2. Restricted builtins: only a small whitelist exists at runtime, and
    __import__ is replaced by an allow-list gate.
 3. Process isolation: separate interpreter in isolated mode, scrubbed
    environment (no API keys), wall-clock timeout enforced by the parent, and
    CPU/memory rlimits where the OS supports them (POSIX).

NOTE: In-process Python sandboxing is hardening, not a hard security boundary.
For multi-tenant production deployment also run this process in a container /
gVisor / Firecracker with no network and a read-only filesystem.

Exit codes: 0 ok | 1 runtime error | 3 security violation | 4 syntax error
Errors are reported on stderr as a single JSON line: {"type":..., "message":...}
"""

import ast
import builtins
import json
import os
import re
import sys
import traceback

ALLOWED_IMPORTS = {"json", "math", "datetime", "sandbox_sdk"}

FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input", "__import__", "globals", "locals",
    "vars", "dir", "getattr", "setattr", "delattr", "breakpoint", "help", "exit",
    "quit", "memoryview", "type", "super", "object", "classmethod", "staticmethod",
    "property", "os", "sys", "subprocess", "socket", "requests", "importlib",
}

SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
    "frozenset", "int", "isinstance", "len", "list", "map", "max", "min", "pow",
    "print", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str",
    "sum", "tuple", "zip", "ValueError", "ZeroDivisionError", "KeyError", "TypeError",
    "IndexError", "Exception", "StopIteration", "ArithmeticError", "OverflowError",
]

# "{0.__class__}" style attribute/index access inside str.format templates
_FORMAT_ESCAPE = re.compile(r"\{[^{}]*[.\[]\s*_")


class SecurityViolation(Exception):
    pass


def _validate(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    raise SecurityViolation(
                        f"import of '{alias.name}' is forbidden; allowed: {sorted(ALLOWED_IMPORTS)}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module not in ALLOWED_IMPORTS:
                raise SecurityViolation(
                    f"'from {node.module} import ...' is forbidden; allowed: {sorted(ALLOWED_IMPORTS)}"
                )
            if any(a.name.startswith("_") or a.name == "*" for a in node.names):
                raise SecurityViolation("importing private names or '*' is forbidden")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise SecurityViolation(f"access to private attribute '{node.attr}' is forbidden")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                raise SecurityViolation(f"use of '{node.id}' is forbidden")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _FORMAT_ESCAPE.search(node.value):
                raise SecurityViolation("format strings that access private attributes are forbidden")
        elif isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and node.test.value:
                raise SecurityViolation("unbounded 'while True' loops are forbidden")
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef, ast.Await)):
            raise SecurityViolation(f"{type(node).__name__} is not allowed in Code Mode scripts")


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Runtime import gate (defence in depth behind the AST check)."""
    if level != 0 or name not in ALLOWED_IMPORTS:
        raise ImportError(f"import of '{name}' is forbidden in the Code Mode sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _apply_rlimits() -> None:
    try:
        import resource  # POSIX only
    except ImportError:
        return
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    except (ValueError, OSError):
        pass


def _fail(code: int, err_type: str, message: str) -> None:
    sys.stderr.write(json.dumps({"type": err_type, "message": message}) + "\n")
    sys.stderr.flush()
    sys.exit(code)


def main() -> None:
    source = sys.stdin.read()
    if not source.strip():
        _fail(4, "EmptyScript", "The model returned no code.")

    try:
        tree = ast.parse(source, filename="<code_mode_script>")
    except SyntaxError as exc:
        _fail(4, "SyntaxError", f"line {exc.lineno}: {exc.msg}")

    try:
        _validate(tree)
    except SecurityViolation as exc:
        _fail(3, "SecurityViolation", str(exc))

    # sandbox_sdk lives next to this file; -I removes the script dir from sys.path.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sandbox_sdk  # noqa: F401  (pre-load while real import machinery is intact)

    _apply_rlimits()

    safe_builtins = {n: getattr(builtins, n) for n in SAFE_BUILTIN_NAMES}
    safe_builtins["__import__"] = _guarded_import
    namespace = {"__builtins__": safe_builtins, "__name__": "__code_mode__"}

    try:
        exec(compile(tree, "<code_mode_script>", "exec"), namespace)
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - report everything to the parent
        tb = traceback.extract_tb(exc.__traceback__)
        line = next((f.lineno for f in reversed(tb) if f.filename == "<code_mode_script>"), None)
        loc = f" (line {line})" if line else ""
        _fail(1, type(exc).__name__, f"{exc}{loc}")


if __name__ == "__main__":
    main()
