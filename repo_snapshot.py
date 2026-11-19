#!/usr/bin/env python3
"""Generate a high-signal, low-noise codebase snapshot for LLM handoffs."""
import argparse
import ast
import hashlib
import os
import re
import subprocess
from pathlib import Path

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "env", "node_modules", "dist", "build",
    "site", "release", ".next", ".nuxt", "target", "out", "coverage",
    ".idea", ".vscode", ".tox", ".nox", ".eggs", ".uv-cache",
}
IGNORE_DIR_SUFFIXES = (".egg-info", ".dist-info")
IGNORE_FILES = {"repo_snapshot.txt", "repo_snapshot.md", ".DS_Store", "Thumbs.db"}
IGNORE_EXTS = {
    # Bytecode, compiled objects & native libs
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".o", ".a", ".lib", ".obj", ".wasm", ".class", ".jar",
    # Archives & packages
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".whl", ".egg",
    # Images, audio, video & fonts
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".svg",
    ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    # Documents, databases & serialized binary blobs
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".db", ".sqlite", ".sqlite3", ".parquet", ".feather", ".arrow",
    ".pkl", ".pickle", ".npy", ".npz", ".pt", ".pth", ".safetensors", ".onnx",
    # Lockfiles & source maps
    ".lock", ".map",
}
HEADER_SKIP_EXTS = {".css", ".js", ".html", ".htm", ".xml", ".gz", ".txt", ".csv"}
PRIORITY_KEYWORDS = ("pyproject.toml", "package.json", "readme", "server", "main", "app", "schema", "model", "config")

MAX_FILE_BYTES = 200_000
MAX_PREVIEW_LINE_CHARS = 200


def run_git(cmd: list[str], root: Path) -> str:
    try:
        res = subprocess.run(["git", *cmd], cwd=root, capture_output=True, text=True, timeout=5)
        return res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        return ""


def get_gitignored(root: Path, rel_paths: list[str]) -> set[str]:
    if not rel_paths:
        return set()
    ignored: set[str] = set()
    # Chunk inputs to stay well below OS pipe/buffer limits
    for i in range(0, len(rel_paths), 500):
        chunk = rel_paths[i : i + 500]
        try:
            res = subprocess.run(
                ["git", "check-ignore", "--stdin"],
                input="\n".join(chunk),
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode in (0, 1):
                ignored.update(res.stdout.splitlines())
        except Exception:
            pass
    return ignored


def is_minified(name: str) -> bool:
    low = name.lower()
    return low.endswith((".min.js", ".min.css", ".bundle.js", ".chunk.js"))


def is_binary_file(path: Path, chunk_size: int = 8192) -> bool:
    """Detect NUL bytes or high ratios of non-text control characters."""
    try:
        with path.open("rb") as f:
            chunk = f.read(chunk_size)
    except OSError:
        return True

    if not chunk:
        return False
    if b"\x00" in chunk:
        return True

    text_controls = {7, 8, 9, 10, 12, 13, 27}
    non_text = sum(1 for b in chunk if b < 32 and b not in text_controls)
    return (non_text / len(chunk)) > 0.30


def iter_files(root: Path, include_tests: bool = True):
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.endswith(IGNORE_DIR_SUFFIXES)
        )
        for fn in sorted(filenames):
            if fn in IGNORE_FILES or is_minified(fn):
                continue
            p = Path(dirpath) / fn
            if p.suffix.lower() in IGNORE_EXTS:
                continue
            if fn.startswith(".") and fn not in {".env.example", ".gitignore", ".github"}:
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if is_binary_file(p):
                continue
            candidates.append(p)

    rel_map = {p.relative_to(root).as_posix(): p for p in candidates}
    ignored = get_gitignored(root, list(rel_map.keys()))

    for rel, p in rel_map.items():
        if rel in ignored:
            continue
        if not include_tests and (rel.startswith("tests/") or Path(rel).name.startswith("test_")):
            continue
        yield p


def _decorator_name(dec: ast.expr) -> str:
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Attribute):
        return f"@{dec.attr}"
    if isinstance(dec, ast.Name):
        return f"@{dec.id}"
    return ""


def extract_python_info(text: str) -> tuple[list[str], list[str]]:
    """Return (symbols_and_decorated_endpoints, internal_imports)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ["<syntax-error>"], []

    symbols: list[str] = []
    internal_imports: set[str] = set()
    seen_funcs: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level > 0 and node.module:
            internal_imports.add(f".{node.module}")
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            m_str = f" [{', '.join(methods[:8])}{'...' if len(methods) > 8 else ''}]" if methods else ""
            symbols.append(f"class {node.name}{m_str} (L{node.lineno})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seen_funcs.add(node.name)
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            args = [a.arg for a in node.args.args[:6]]
            decs = [d for d in (_decorator_name(x) for x in node.decorator_list) if d]
            dec_str = f"{' '.join(decs)} " if decs else ""
            symbols.append(f"{dec_str}{prefix} {node.name}({', '.join(args)}) (L{node.lineno})")

            # Surface nested decorated handlers (e.g. @mcp.tool() inside register_tools())
            for sub in ast.walk(node):
                if (
                    sub is not node
                    and isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and sub.decorator_list
                    and sub.name not in seen_funcs
                ):
                    sub_decs = [d for d in (_decorator_name(x) for x in sub.decorator_list) if d]
                    if sub_decs:
                        seen_funcs.add(sub.name)
                        sub_args = [a.arg for a in sub.args.args[:5]]
                        symbols.append(f"  {' '.join(sub_decs)} {sub.name}({', '.join(sub_args)}) (L{sub.lineno})")

    return symbols, sorted(internal_imports)


def extract_js_ts_symbols(text: str) -> list[str]:
    pattern = re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+([A-Za-z0-9_]+)|class\s+([A-Za-z0-9_]+)|(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=)",
        re.MULTILINE,
    )
    return [
        f"sym {m.group(1) or m.group(2) or m.group(3)} (L{text.count(chr(10), 0, m.start()) + 1})"
        for m in list(pattern.finditer(text))[:25]
    ]


def header_priority(rel: str) -> tuple[int, str]:
    p = Path(rel)
    low = rel.lower()
    if p.suffix.lower() in HEADER_SKIP_EXTS or is_minified(p.name):
        return (99, low)
    if low.startswith(("tests/", "test/", "release/")) or p.name.startswith("test_"):
        return (99, low)
    for idx, kw in enumerate(PRIORITY_KEYWORDS):
        if kw in low:
            return (idx, low)
    if low.startswith("src/"):
        return (len(PRIORITY_KEYWORDS), low)
    return (50, low)


def build_snapshot(root: Path, max_head_lines: int, max_header_files: int, include_tests: bool) -> str:
    out: list[str] = []
    files = list(iter_files(root, include_tests=include_tests))

    out.append(f"# REPO SNAPSHOT: {root.name}")
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    status = [line for line in run_git(["status", "--short"], root).splitlines() if not any(f in line for f in IGNORE_FILES)]
    recent_log = run_git(["log", "-n", "5", "--oneline"], root)

    if branch:
        out.append(f"Branch: {branch}")
    if recent_log:
        out.append("Recent commits:\n" + "\n".join(f"  {line}" for line in recent_log.splitlines()))
    out.append(f"Dirty files: {len(status)}")
    if status:
        out.extend(f"  {line}" for line in status[:25])

    out.append("\n## FILE TREE, IMPORTS & SYMBOLS")
    shim_groups: dict[str, list[str]] = {}

    for p in files:
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        line_count = text.count("\n") + (1 if text else 0)
        ext = p.suffix.lower()
        syms, imports = [], []
        if ext == ".py":
            syms, imports = extract_python_info(text)
            # Collapse thin re-export alias shims (<= 8 lines, no classes/funcs, internal import only)
            if line_count <= 8 and not syms and imports and p.name != "__init__.py":
                target = ", ".join(imports)
                shim_groups.setdefault(target, []).append(rel)
                continue
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            syms = extract_js_ts_symbols(text)

        imp_part = f" [imports: {', '.join(imports)}]" if imports else ""
        sym_part = f" -> {'; '.join(syms[:20])}{' ...' if len(syms) > 20 else ''}" if syms else ""
        out.append(f"- {rel} ({line_count}L){imp_part}{sym_part}")

    if shim_groups:
        out.append("\n### Re-export Alias Shims")
        for target, shims in sorted(shim_groups.items()):
            out.append(f"- {', '.join(shims)} -> [{target}]")

    out.append("\n## KEY SOURCE & CONFIG HEADERS")
    ranked = sorted(files, key=lambda p: header_priority(p.relative_to(root).as_posix()))
    candidates = [p for p in ranked if header_priority(p.relative_to(root).as_posix())[0] < 50]

    seen_hashes: dict[str, str] = {}
    shown = 0
    for p in candidates:
        if shown >= max_header_files:
            break
        rel = p.relative_to(root).as_posix()
        try:
            raw_text = p.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue

        lines = raw_text.splitlines()
        limit = max_head_lines * 2 if rel in {"pyproject.toml", "package.json"} else max_head_lines
        preview_slice = lines[:limit]
        digest = hashlib.sha256("\n".join(preview_slice).encode("utf-8")).hexdigest()

        if digest in seen_hashes:
            out.append(f"\n### {rel} (identical header to {seen_hashes[digest]})")
            continue

        seen_hashes[digest] = rel
        shown += 1
        out.append(f"\n### {rel} (showing first {min(len(lines), limit)}/{len(lines)} lines)")
        for i, line in enumerate(preview_slice, start=1):
            if len(line) > MAX_PREVIEW_LINE_CHARS:
                line = line[:MAX_PREVIEW_LINE_CHARS] + " ...[truncated]"
            out.append(f"{i:3d}: {line}")

    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Generate a compact codebase snapshot for AI agents.")
    parser.add_argument("-o", "--out", type=Path, help="Write snapshot directly to a file instead of stdout.")
    parser.add_argument("-r", "--root", type=Path, default=Path("."), help="Repository root directory.")
    parser.add_argument("--head-lines", type=int, default=40, help="Max preview lines per priority file.")
    parser.add_argument("--max-headers", type=int, default=15, help="Max number of file headers to include.")
    parser.add_argument("--no-tests", action="store_true", help="Exclude test files from the snapshot.")
    args = parser.parse_args()

    root = args.root.resolve()
    snapshot = build_snapshot(
        root=root,
        max_head_lines=args.head_lines,
        max_header_files=args.max_headers,
        include_tests=not args.no_tests,
    )
    if args.out:
        args.out.write_text(snapshot, encoding="utf-8")
    else:
        print(snapshot, end="")


if __name__ == "__main__":
    main()
