#!/usr/bin/env python3
import ast
import os
import re
import subprocess
from pathlib import Path

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "env", "node_modules", "dist", "build",
    ".next", ".nuxt", "target", "out", "coverage", ".idea", ".vscode"
}
IGNORE_EXTS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".mp3",
    ".flac", ".wav", ".ogg", ".mp4", ".mov", ".zip", ".tar", ".gz",
    ".lock", ".db", ".sqlite", ".sqlite3", ".woff", ".woff2", ".ttf"
}
CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".ps1", ".sh", ".json", ".toml", ".yaml", ".yml", ".md"}

MAX_FILE_BYTES = 200_000
MAX_HEAD_LINES = 45


def run_git(cmd: list[str], root: Path) -> str:
    try:
        res = subprocess.run(["git", *cmd], cwd=root, capture_output=True, text=True, timeout=5)
        return res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        return ""


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".tox"))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.suffix.lower() in IGNORE_EXTS or fn.startswith(".") and fn not in {".env.example", ".gitignore"}:
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield p


def extract_python_symbols(text: str) -> list[str]:
    symbols = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ["<syntax-error>"]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            m_str = f" [{', '.join(methods[:8])}{'...' if len(methods) > 8 else ''}]" if methods else ""
            symbols.append(f"class {node.name}{m_str} (L{node.lineno})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            args = [a.arg for a in node.args.args[:6]]
            symbols.append(f"{prefix} {node.name}({', '.join(args)}) (L{node.lineno})")
    return symbols


def extract_js_ts_symbols(text: str) -> list[str]:
    pattern = re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+([A-Za-z0-9_]+)|class\s+([A-Za-z0-9_]+)|(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=)",
        re.MULTILINE,
    )
    found = []
    for idx, m in enumerate(pattern.finditer(text), start=1):
        name = m.group(1) or m.group(2) or m.group(3)
        line_no = text.count("\n", 0, m.start()) + 1
        found.append(f"sym {name} (L{line_no})")
    return found[:25]


def main():
    root = Path.cwd().resolve()
    files = list(iter_files(root))

    print(f"# REPO SNAPSHOT: {root.name}")
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    status = run_git(["status", "--short"], root)
    recent_log = run_git(["log", "-n", "5", "--oneline"], root)
    if branch:
        print(f"Branch: {branch}")
    if recent_log:
        print("Recent commits:\n" + "\n".join(f"  {line}" for line in recent_log.splitlines()))
    print(f"Dirty files: {len(status.splitlines()) if status else 0}")
    if status:
        print("\n".join(f"  {line}" for line in status.splitlines()[:25]))

    print("\n## FILE TREE & SYMBOLS")
    for p in files:
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        line_count = text.count("\n") + (1 if text else 0)
        ext = p.suffix.lower()
        syms = []
        if ext == ".py":
            syms = extract_python_symbols(text)
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            syms = extract_js_ts_symbols(text)

        sym_part = f" -> {'; '.join(syms[:12])}{' ...' if len(syms) > 12 else ''}" if syms else ""
        print(f"- {rel} ({line_count}L){sym_part}")

    print("\n## KEY FILE HEADERS (TOP LINES)")
    priority_hits = 0
    for p in files:
        rel = p.relative_to(root).as_posix()
        if not any(k in rel.lower() for k in ("server", "app", "main", "tool", "schema", "readme", "pyproject", "package.json")):
            continue
        if priority_hits >= 10:
            break
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        priority_hits += 1
        print(f"\n### {rel} (showing first {min(len(lines), MAX_HEAD_LINES)}/{len(lines)} lines)")
        for i, line in enumerate(lines[:MAX_HEAD_LINES], start=1):
            print(f"{i:3d}: {line}")


if __name__ == "__main__":
    main()
