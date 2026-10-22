#!/usr/bin/env python3
"""Sync Surge rule files listed in sources.json from their upstream sources.

Each source is synced on its own. A source that fails to download, returns a
web page, contains no rules, or shrinks by more than half keeps its previous
file, and the run exits with code 2 so CI can flag it.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = "rules"
DEFAULT_REPO = "hypsoma/Surge"
DEFAULT_BRANCH = "main"
USER_AGENT = "surge-rules-sync/1.0 (+https://github.com/hypsoma/Surge)"
SHRINK_RATIO = 0.5
SHRINK_MIN_RULES = 20
README_START = "<!-- sources:start -->"
README_END = "<!-- sources:end -->"


class SourceError(Exception):
    """A single source could not be synced; its previous file is kept."""


@dataclass(frozen=True)
class Source:
    url: str
    path: str
    convert: str | None = None
    license: str | None = None
    note: str | None = None

    @property
    def upstream_repo(self) -> str | None:
        parsed = urllib.parse.urlparse(self.url)
        if parsed.netloc != "raw.githubusercontent.com":
            return None
        parts = parsed.path.strip("/").split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else None


# ---------- sources.json ----------


def load_sources(manifest: Path) -> list[Source]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"{manifest.name} must be a non-empty JSON array")

    sources: list[Source] = []
    seen: set[str] = set()
    for index, item in enumerate(data, 1):
        url = item.get("url")
        path = item.get("path")
        if not url or not path:
            raise ValueError(f"entry {index} needs both url and path")
        target = Path(path)
        if target.is_absolute() or ".." in target.parts or target.parts[0] != RULES_DIR:
            raise ValueError(f"entry {index}: path must be inside {RULES_DIR}/: {path}")
        key = target.as_posix().lower()
        if key in seen:
            raise ValueError(f"entry {index}: duplicate path {path}")
        seen.add(key)
        convert = item.get("convert")
        if convert is not None and convert not in CONVERTERS:
            raise ValueError(f"entry {index}: unknown convert {convert!r}")
        sources.append(
            Source(
                url=url,
                path=target.as_posix(),
                convert=convert,
                license=item.get("license"),
                note=item.get("note"),
            )
        )
    return sources


# ---------- download ----------


def fetch(url: str, timeout: int, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain, */*"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            # 4xx other than 429 will not fix itself on retry
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(5 * attempt)
    raise SourceError(f"download failed: {last_error}")


# ---------- conversion ----------


def convert_cidr(text: str, source: Source) -> tuple[str, int]:
    """Turn a bare CIDR list into IP-CIDR / IP-CIDR6 rules."""
    lines = [
        "# Converted to Surge rule format by hypsoma/Surge",
        f"# Source: {source.url}",
    ]
    invalid = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            lines.append(line)
            continue
        if "," in line:  # already a rule line
            lines.append(line)
            continue
        try:
            network = ipaddress.ip_network(line, strict=False)
        except ValueError:
            invalid += 1
            continue
        rule_type = "IP-CIDR6" if network.version == 6 else "IP-CIDR"
        lines.append(f"{rule_type},{network.with_prefixlen}")
    return "\n".join(lines) + "\n", invalid


CONVERTERS = {"cidr": convert_cidr}


# ---------- validation ----------


def count_rules(text: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//", ";"))
    )


def validate(new_text: str, old_text: str | None, force: bool) -> int:
    head = new_text.lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html") or "<head>" in head:
        raise SourceError("upstream returned a web page instead of a rule list")
    new_count = count_rules(new_text)
    if new_count == 0:
        raise SourceError("upstream file contains no rules")
    if old_text is not None and not force:
        old_count = count_rules(old_text)
        if old_count >= SHRINK_MIN_RULES and new_count < old_count * SHRINK_RATIO:
            raise SourceError(
                f"rule count dropped from {old_count} to {new_count}; "
                "kept the old file (run manually with force to accept)"
            )
    return new_count


# ---------- sync ----------


def sync_one(source: Source, timeout: int, force: bool) -> tuple[bytes, int, list[str]]:
    raw = fetch(source.url, timeout)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError(f"upstream file is not UTF-8 text: {exc}") from exc

    warnings: list[str] = []
    if source.convert:
        text, invalid = CONVERTERS[source.convert](text, source)
        if invalid:
            warnings.append(f"skipped {invalid} invalid line(s) during conversion")
        content = text.encode("utf-8")
    else:
        content = raw  # keep upstream bytes untouched

    target = REPO_ROOT / source.path
    old_text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
    count = validate(text, old_text, force)
    return content, count, warnings


def remove_stale(managed: set[str]) -> list[str]:
    removed: list[str] = []
    rules_root = REPO_ROOT / RULES_DIR
    if not rules_root.exists():
        return removed
    for file in sorted(p for p in rules_root.rglob("*") if p.is_file()):
        relative = file.relative_to(REPO_ROOT).as_posix()
        if relative in managed or file.name == ".gitkeep":
            continue
        file.unlink()
        removed.append(relative)
    for directory in sorted((p for p in rules_root.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return removed


# ---------- README ----------


def render_table(sources: list[Source], repo: str, branch: str) -> str:
    rows = [
        "| 文件 | 规则数 | 源头 | 许可证 | 说明 |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for source in sources:
        target = REPO_ROOT / source.path
        count = (
            str(count_rules(target.read_text(encoding="utf-8", errors="replace")))
            if target.exists()
            else "-"
        )
        name = Path(source.path).name
        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{source.path}"
        upstream = source.upstream_repo or urllib.parse.urlparse(source.url).netloc
        rows.append(
            f"| [{name}]({raw_url}) | {count} | [{upstream}]({source.url}) "
            f"| {source.license or '-'} | {source.note or ''} |"
        )
    return "\n".join(rows)


def update_readme(sources: list[Source], repo: str, branch: str) -> bool:
    readme = REPO_ROOT / "README.md"
    if not readme.exists():
        return False
    text = readme.read_text(encoding="utf-8")
    start = text.find(README_START)
    end = text.find(README_END)
    if start < 0 or end < start:
        return False
    table = render_table(sources, repo, branch)
    new_text = text[: start + len(README_START)] + "\n" + table + "\n" + text[end:]
    if new_text == text:
        return False
    readme.write_text(new_text, encoding="utf-8")
    return True


# ---------- reporting ----------


def write_commit_message(path: Path, report: dict) -> None:
    lines = ["chore: sync surge rules", ""]
    for title, key in (("Updated files:", "updated"), ("Removed files:", "removed")):
        if report[key]:
            lines.append(title)
            lines.extend(f"- {item}" for item in report[key])
            lines.append("")
    if report["failed"]:
        lines.append("Failed sources:")
        lines.extend(f"- {item['path']} <- {item['url']} ({item['error']})" for item in report["failed"])
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def set_github_output(**values: object) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default="sources.json")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds")
    parser.add_argument("--force", action="store_true", help="accept large rule count drops")
    parser.add_argument("--report", default=".sync-report.json")
    parser.add_argument("--commit-message", default=".sync-commit-msg")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    branch = os.environ.get("GITHUB_REF_NAME", DEFAULT_BRANCH)

    try:
        sources = load_sources(REPO_ROOT / args.manifest)
    except (OSError, ValueError) as exc:
        print(f"::error::invalid {args.manifest}: {exc}")
        set_github_output(failed=1)
        return 1

    report: dict = {"updated": [], "unchanged": [], "removed": [], "failed": [], "warnings": []}
    for source in sources:
        try:
            content, count, warnings = sync_one(source, args.timeout, args.force)
        except SourceError as exc:
            report["failed"].append({"path": source.path, "url": source.url, "error": str(exc)})
            print(f"::warning::{source.path}: {exc}")
            continue

        for warning in warnings:
            report["warnings"].append(f"{source.path}: {warning}")
            print(f"::warning::{source.path}: {warning}")

        target = REPO_ROOT / source.path
        if target.exists() and target.read_bytes() == content:
            report["unchanged"].append(source.path)
            print(f"Unchanged {source.path} ({count} rules)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        report["updated"].append(source.path)
        print(f"Updated   {source.path} ({count} rules)")

    report["removed"] = remove_stale({source.path for source in sources})
    for path in report["removed"]:
        print(f"Removed   {path}")
    readme_changed = update_readme(sources, repo, branch)

    (REPO_ROOT / args.report).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_commit_message(REPO_ROOT / args.commit_message, report)
    set_github_output(failed=len(report["failed"]))

    print(
        f"Synced {len(sources)} sources: {len(report['updated'])} updated, "
        f"{len(report['unchanged'])} unchanged, {len(report['removed'])} removed, "
        f"{len(report['failed'])} failed"
        + ("; README updated" if readme_changed else "")
    )
    return 2 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
