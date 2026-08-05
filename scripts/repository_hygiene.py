from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pnpm-store",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "node_modules",
}
IGNORED_PATHS = {
    Path("vendor/downloads"),
    Path("vendor/llama.cpp"),
}
IGNORED_FILES = {"catalyst-preflight-probe.spec"}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".pyi",
    ".spec",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {".editorconfig", ".gitattributes", ".gitignore", "LICENSE"}
REQUIRED_FILES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "PRD.md",
    "README.md",
    "SECURITY.md",
    "TECHNICAL_DESIGN.md",
    "docs/DEVELOPMENT.md",
    "docs/README.md",
    "docs/RELEASE.md",
}
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
PRIVATE_KEY = re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")
ASSIGNED_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*"
    r"[\"'][A-Za-z0-9._-]{16,}[\"']"
)


def _is_ignored(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if path.name in IGNORED_FILES or any(part in IGNORED_PARTS for part in relative.parts):
        return True
    return any(relative == ignored or ignored in relative.parents for ignored in IGNORED_PATHS)


def _candidate_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for directory, directory_names, file_names in root.walk(top_down=True):
        directory_names[:] = [
            name
            for name in directory_names
            if not _is_ignored(root, directory / name)
        ]
        candidates.extend(
            directory / name
            for name in file_names
            if not _is_ignored(root, directory / name)
        )
    return candidates


def _link_target(markdown: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>")
    if not target or target.startswith(("#", "/", "http://", "https://", "mailto:")):
        return None
    target = target.split("#", maxsplit=1)[0]
    if " \"" in target:
        target = target.split(" \"", maxsplit=1)[0]
    return (markdown.parent / unquote(target)).resolve()


def collect_issues(root: Path) -> list[str]:
    root = root.resolve()
    issues: list[str] = []
    candidates = _candidate_files(root)
    for required in sorted(REQUIRED_FILES):
        if not (root / required).is_file():
            issues.append(f"missing required repository file: {required}")
    license_path = root / "LICENSE"
    if license_path.is_file():
        license_text = license_path.read_text(encoding="utf-8")
        apache_markers = (
            "Apache License",
            "Version 2.0, January 2004",
            "1. Definitions.",
            "2. Grant of Copyright License.",
            "3. Grant of Patent License.",
            "4. Redistribution.",
            "5. Submission of Contributions.",
            "6. Trademarks.",
            "7. Disclaimer of Warranty.",
            "8. Limitation of Liability.",
            "9. Accepting Warranty or Additional Liability.",
            "END OF TERMS AND CONDITIONS",
        )
        if len(license_text) < 10_000 or any(
            marker not in license_text for marker in apache_markers
        ):
            issues.append("LICENSE is not the complete Apache License 2.0 text")

    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if path.stat().st_size > MAX_SOURCE_BYTES:
            issues.append(f"source candidate exceeds 25 MiB: {relative}")
        lowered = path.name.lower()
        if lowered == ".env" or (lowered.startswith(".env.") and lowered != ".env.example"):
            issues.append(f"credential environment file must not be committed: {relative}")
        if path.suffix.lower() in {".key", ".p12", ".pem", ".pfx"}:
            issues.append(f"private credential file must not be committed: {relative}")

    for path in candidates:
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(f"text file is not UTF-8: {relative}")
            continue
        if content and not content.endswith("\n"):
            issues.append(f"text file has no final newline: {relative}")
        if "\ufffd" in content:
            issues.append(f"text file contains a replacement character: {relative}")
        if PRIVATE_KEY.search(content) or ASSIGNED_SECRET.search(content):
            issues.append(f"possible embedded credential: {relative}")
        if path.suffix.lower() != ".md":
            continue
        for match in MARKDOWN_LINK.finditer(content):
            target = _link_target(path, match.group(1))
            if target is not None and not target.exists():
                issues.append(
                    f"broken relative Markdown link in {relative}: {match.group(1).strip()}"
                )
    return sorted(set(issues))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = collect_issues(root)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print("Repository hygiene passed: docs, links, size limits, and credential guards.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
