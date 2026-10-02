"""Automated zero-emoji verification and repository hygiene audit script."""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Emoji and pictogram Unicode ranges per AGENTS.md Rule 1 and GEMINI.md Rule 1
EMOJI_RANGES = [
    (0x1F000, 0x1FFFF),
    (0x2600, 0x27BF),
    (0x2B50, 0x2B55),
    (0x2300, 0x23FF),
    (0x2B05, 0x2B07),
    (0x2934, 0x2935),
    (0x3297, 0x3299),
    (0xFE00, 0xFE0F),
    (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
]

PROHIBITED_EXTENSIONS = {
    ".rom",
    ".nes",
    ".sfc",
    ".smc",
    ".gba",
    ".gb",
    ".iso",
    ".cue",
    ".chd",
    ".pyc",
    ".pyo",
    ".pyd",
}

IGNORED_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
}


def is_emoji_codepoint(cp: int) -> bool:
    """Check if Unicode codepoint falls within disallowed emoji or pictogram ranges."""
    return any(start <= cp <= end for start, end in EMOJI_RANGES)


def verify_zero_emojis_in_files() -> tuple[int, list[dict[str, str | int]]]:
    """Scan all non-ignored files in the repository for emoji characters."""
    infractions: list[dict[str, str | int]] = []
    scanned_count = 0

    for root, dirs, files in os.walk(REPO_ROOT):
        # Prune ignored directories in-place
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for file_name in files:
            file_path = Path(root) / file_name
            # Skip git internal files or coverage databases
            if file_name in {".coverage"} or file_name.endswith(".pyc"):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # Binary file, skip text scan
                continue
            except Exception:
                continue

            scanned_count += 1
            rel_path = file_path.relative_to(REPO_ROOT).as_posix()
            for line_idx, line in enumerate(content.splitlines(), start=1):
                for col_idx, char in enumerate(line, start=1):
                    cp = ord(char)
                    if is_emoji_codepoint(cp):
                        infractions.append(
                            {
                                "file": rel_path,
                                "line": line_idx,
                                "column": col_idx,
                                "char": char,
                                "codepoint": f"U+{cp:04X}",
                            }
                        )

    return scanned_count, infractions


def verify_zero_emojis_in_git_log() -> tuple[int, list[dict[str, str | int]]]:
    """Scan all commit messages in the git log for emoji characters."""
    infractions: list[dict[str, str | int]] = []
    try:
        log_output = subprocess.check_output(
            ["git", "log", "--format=%H%x09%s%n%b"],
            cwd=str(REPO_ROOT),
            text=True,
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"Error reading git log: {exc}", file=sys.stderr)
        return 0, []

    lines = log_output.splitlines()
    for line_idx, line in enumerate(lines, start=1):
        for col_idx, char in enumerate(line, start=1):
            cp = ord(char)
            if is_emoji_codepoint(cp):
                infractions.append(
                    {
                        "line": line_idx,
                        "column": col_idx,
                        "char": char,
                        "codepoint": f"U+{cp:04X}",
                        "context": line[:80],
                    }
                )

    return len(lines), infractions


def audit_repository_hygiene() -> tuple[int, list[str]]:
    """Audit repository for prohibited secrets, ROMs, build caches, and sensitive files."""
    hygiene_violations: list[str] = []
    scanned_count = 0

    sensitive_patterns = [
        re.compile(r"^\.env(\..+)?$", re.IGNORECASE),
        re.compile(r"^id_rsa.*$", re.IGNORECASE),
        re.compile(r".*\.pem$", re.IGNORECASE),
        re.compile(r".*\.key$", re.IGNORECASE),
    ]

    # 1. Check tracked files in git index to guarantee no build artifacts or secrets are tracked
    try:
        tracked_files = subprocess.check_output(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            text=True,
            encoding="utf-8",
        ).splitlines()
    except Exception as exc:
        print(f"Error querying git ls-files: {exc}", file=sys.stderr)
        tracked_files = []

    for rel_path_str in tracked_files:
        scanned_count += 1
        p = Path(rel_path_str)
        ext = p.suffix.lower()
        if ext in PROHIBITED_EXTENSIONS:
            hygiene_violations.append(f"Prohibited tracked file extension '{ext}': {rel_path_str}")
        for pattern in sensitive_patterns:
            if pattern.match(p.name):
                hygiene_violations.append(f"Sensitive file pattern tracked in git: {rel_path_str}")

    # 2. Check for untracked forbidden files in workspace
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file_name in files:
            p = Path(root) / file_name
            rel_str = p.relative_to(REPO_ROOT).as_posix()
            ext = p.suffix.lower()
            if ext in {".rom", ".nes", ".sfc", ".smc", ".gba", ".gb", ".iso", ".cue", ".chd"}:
                hygiene_violations.append(f"Prohibited ROM / game image present: {rel_str}")
            for pattern in sensitive_patterns:
                if pattern.match(file_name):
                    hygiene_violations.append(f"Sensitive credentials file present: {rel_str}")

    return scanned_count, hygiene_violations


def main() -> int:
    """Run full hygiene and zero-emoji verification suite."""
    print("=" * 80)
    print("GAMING-MCP: REPOSITORY HYGIENE AND ZERO-EMOJI VERIFICATION AUDIT")
    print("=" * 80)

    # Step 1: Zero-emoji file scan
    file_count, file_infractions = verify_zero_emojis_in_files()
    print(f"\n[1/3] File Emoji Audit: Scanned {file_count} files.")
    if file_infractions:
        print(f"FAILED: Found {len(file_infractions)} emoji infractions in files:")
        for inf in file_infractions[:20]:
            print(f"  - {inf['file']}:{inf['line']}:{inf['column']} ({inf['codepoint']})")
    else:
        print("PASSED: 0 emoji infractions found across all repository files.")

    # Step 2: Zero-emoji git log scan
    log_lines, log_infractions = verify_zero_emojis_in_git_log()
    print(f"\n[2/3] Git Log Emoji Audit: Scanned {log_lines} log lines.")
    if log_infractions:
        print(f"FAILED: Found {len(log_infractions)} emoji infractions in git log:")
        for inf in log_infractions[:20]:
            print(f"  - Line {inf['line']}:{inf['column']} ({inf['codepoint']}): {inf['context']}")
    else:
        print("PASSED: 0 emoji infractions found across entire git commit history.")

    # Step 3: Repository Hygiene Audit
    tracked_count, hygiene_issues = audit_repository_hygiene()
    print(f"\n[3/3] Repository Hygiene Audit: Verified {tracked_count} tracked files.")
    if hygiene_issues:
        print(f"FAILED: Found {len(hygiene_issues)} hygiene violations:")
        for issue in hygiene_issues:
            print(f"  - {issue}")
    else:
        print("PASSED: 0 hygiene violations found (no secrets, no ROMs, no cache leaks).")

    print("\n" + "=" * 80)
    total_failures = len(file_infractions) + len(log_infractions) + len(hygiene_issues)
    if total_failures == 0:
        print("OVERALL AUDIT RESULT: PASSED (Strict zero-emoji and hygiene conformance)")
        print("=" * 80)
        return 0
    else:
        print(f"OVERALL AUDIT RESULT: FAILED ({total_failures} total issues detected)")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
