"""Fail safely when public files resemble secrets or private infrastructure."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__"}
SKIP_FILES = {Path(__file__).resolve(), ROOT / ".privacy-denylist"}
MAX_BYTES = 2_000_000

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "api_secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "oauth_code": re.compile(r"\b4/0A[A-Za-z0-9_-]{20,}\b"),
    "discord_token": re.compile(r"\b\d{17,20}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{20,}\b"),
    "credential_in_url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
    "windows_user_path": re.compile(r"[A-Za-z]:\\Users\\(?!example\\|yourname\\)[^\\\s]+\\", re.I),
    "unix_home_path": re.compile(r"/(?:home|Users)/(?!example/|user/)[^/\s]+/"),
    "public_ipv4": re.compile(
        r"\b(?!(?:127|10|0)\.)(?!(?:192\.168|169\.254)\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)"
        r"(?!(?:192\.0\.2|198\.51\.100|203\.0\.113)\.)"
        r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"
    ),
}

LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.resolve() in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        yield path, text


def load_private_denylist() -> list[str]:
    path = ROOT / ".privacy-denylist"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def scan() -> list[str]:
    findings: list[str] = []
    denylist = load_private_denylist()
    for path, content in text_files():
        rel = path.relative_to(ROOT).as_posix()
        for line_number, line in enumerate(content.splitlines(), 1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{rel}:{line_number}: {name}")
            for private_term in denylist:
                if private_term.casefold() in line.casefold():
                    findings.append(f"{rel}:{line_number}: private_denylist")

        if path.suffix.lower() == ".md":
            for target in LINK.findall(content):
                target = target.strip().split("#", 1)[0]
                if not target or "://" in target or target.startswith(("mailto:", "#", "<")):
                    continue
                if not (path.parent / target).resolve().exists():
                    findings.append(f"{rel}: broken_local_link")
    return sorted(set(findings))


def self_test() -> int:
    samples = {
        "private_key": "-----BEGIN PRIVATE KEY-----",
        "github_token": "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "api_secret": "sk-abcdefghijklmnopqrstuvwxyz123456",
        "oauth_code": "4/0AXabcdefghijklmnopqrstuvwxyz123456",
        "public_ipv4": "8.8.8.8",
    }
    missed = [name for name, sample in samples.items() if not PATTERNS[name].search(sample)]
    if missed:
        print("privacy scanner self-test failed: " + ", ".join(missed))
        return 1
    print("privacy scanner self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    findings = scan()
    if findings:
        print("Public-safety check failed (matched values are intentionally not printed):")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Public-safety check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
