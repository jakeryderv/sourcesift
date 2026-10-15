"""Bounded file discovery and fuzzy matching for the interactive composer."""

import json
import os
import re
import stat
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from pathspec import GitIgnoreSpec

from sourcesift.errors import InputError

COMMANDS = {
    "/new": "Start fresh and reload context",
    "/context": "Inspect loaded personal context",
    "/model": "Choose model and reasoning effort",
    "/cancel": "Stop the active research turn",
    "/help": "Show controls and commands",
    "/quit": "Exit chat",
}
MENTION = re.compile(r'(?<!\S)@("(?:[^"\\\n]|\\.)*"|[^\s"]+)(?=\s|$)')
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}


def mention(path: str) -> str:
    """Quote a selected relative path so spaces and punctuation stay unambiguous."""
    return "@" + json.dumps(path, ensure_ascii=False)


def mentioned_paths(text: str) -> set[str]:
    """Read literal file mentions; discovery alone never attaches a document."""
    paths = set()
    for match in MENTION.finditer(text):
        token = match[1]
        if token.startswith('"'):
            try:
                token = json.loads(token)
            except ValueError:
                continue
        paths.add(token)
    return paths


def fuzzy_matches(
    query: str, candidates: list[str]
) -> list[tuple[str, tuple[int, ...]]]:
    """Rank case-insensitive subsequences in linear time per candidate."""
    ranked = []
    query = query.lower()
    for candidate in candidates:
        lowered = candidate.lower()
        offsets = []
        start = 0
        for letter in query:
            found = lowered.find(letter, start)
            if found < 0:
                break
            offsets.append(found)
            start = found + 1
        else:
            gaps = sum(b - a - 1 for a, b in pairwise(offsets))
            score = (
                not lowered.startswith(query),
                gaps,
                offsets[0] if offsets else 0,
                len(candidate),
                lowered,
            )
            ranked.append((score, candidate, tuple(offsets)))
    ranked.sort()
    return [(name, offsets) for _, name, offsets in ranked[:30]]


@dataclass(frozen=True)
class FileIndex:
    paths: tuple[str, ...]
    limited: bool = False


def discover_files(
    root: Path, *, max_entries: int = 20000, seconds: float = 2
) -> FileIndex:
    """List visible regular files without reading contents or following symlinks.

    Respect .gitignore files from the repository root down, including nested
    rules. Bound entry count, elapsed time, and depth even in large workspaces.
    """
    root = root.resolve()
    found: list[str] = []
    deadline = time.monotonic() + seconds
    visited = 0
    limited = False

    def rules(directory: Path) -> GitIgnoreSpec:
        try:
            path = directory / ".gitignore"
            if path.is_symlink():
                return GitIgnoreSpec.from_lines([])
            if not stat.S_ISREG(path.stat().st_mode):
                raise InputError(
                    "The file picker requires .gitignore to be a regular text file."
                )
            with path.open("rb") as stream:
                text = stream.read(65537)
            if len(text) > 65536:
                raise InputError("A .gitignore file exceeds the 64 KiB picker limit.")
            return GitIgnoreSpec.from_lines(text.decode("utf-8").splitlines())
        except FileNotFoundError:
            return GitIgnoreSpec.from_lines([])

    def walk(
        directory: Path, specs: list[tuple[Path, GitIgnoreSpec]], depth: int
    ) -> None:
        nonlocal visited, limited
        specs = [*specs, (directory, rules(directory))]
        with os.scandir(directory) as entries:
            for entry in entries:
                visited += 1
                if visited > max_entries or time.monotonic() > deadline:
                    limited = True
                    return
                if (
                    entry.name.startswith(".")
                    or entry.is_symlink()
                    or not all(c.isprintable() for c in entry.name)
                ):
                    continue
                path = Path(entry.path)
                is_dir = entry.is_dir(follow_symlinks=False)
                ignored = False
                for base, spec in specs:
                    match = spec.check_file(
                        path.relative_to(base).as_posix() + ("/" if is_dir else "")
                    )
                    if match.include is not None:
                        ignored = match.include
                if ignored:
                    continue
                if is_dir:
                    if entry.name in SKIP_DIRS:
                        continue
                    if depth >= 20:
                        limited = True
                        continue
                    walk(path, specs, depth + 1)
                    if visited > max_entries or time.monotonic() > deadline:
                        return
                elif entry.is_file(follow_symlinks=False):
                    found.append(path.relative_to(root).as_posix())

    try:
        inherited = []
        for parent in root.parents:
            if (parent / ".git").exists():
                chain = list(root.parents)
                inherited = [
                    (base, rules(base))
                    for base in reversed(chain[: chain.index(parent) + 1])
                ]
                break
        walk(root, inherited, 0)
    except (OSError, ValueError):
        raise InputError(
            "Cannot list workspace files; check directory and .gitignore permissions."
        ) from None
    return FileIndex(tuple(sorted(found)), limited)


def attachment_path(root: Path, relative: str) -> Path:
    """Recheck selected files at send time, including symlink swaps and traversal."""
    path = root / relative
    try:
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError
        current = root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError
        if not path.resolve().is_relative_to(root.resolve()) or not stat.S_ISREG(
            path.stat().st_mode
        ):
            raise ValueError
    except (OSError, RuntimeError, ValueError):
        raise InputError(
            "An attachment is missing, outside the workspace, or no longer a regular file. Remove it and select again."
        ) from None
    return path
