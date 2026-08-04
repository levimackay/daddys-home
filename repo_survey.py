#!/usr/bin/env python3
"""Survey git repositories under a directory for the daddyshome standup.

Read-only by construction: only `git log`, `git status --short`,
`git rev-list` and `git branch` are ever run, always via `git -C`.

    python3 repo_survey.py [ROOT] [--days N]
"""

import argparse
import os
import subprocess
import sys

READ_ONLY = ("log", "status", "rev-list", "branch", "remote")


def git(repo, *args):
    """Run one read-only git subcommand in repo. Returns stdout, or None."""
    if not args or args[0] not in READ_ONLY:
        raise ValueError(f"refusing non-read-only git subcommand: {args[:1]}")
    try:
        proc = subprocess.run(["git", "-C", repo, *args],
                              capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def survey(root, days):
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        sys.exit(f"not a directory: {root}")

    repos = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isdir(os.path.join(path, ".git")):
            repos.append((name, path))

    print(f"REPO SURVEY - {len(repos)} repos under {root}, window {days} days")
    print("=" * 72)
    if not repos:
        return

    print(f"{'repo':<34}{'commits':>9}{'uncommitted':>13}{'unpushed':>10}  last commit")
    print("-" * 88)

    for name, path in repos:
        log = git(path, "log", f"--since={days} days ago", "--oneline")
        commits = len([l for l in (log or "").splitlines() if l.strip()])

        status = git(path, "status", "--short")
        dirty = len([l for l in (status or "").splitlines() if l.strip()])

        ahead = git(path, "rev-list", "--count", "@{upstream}..HEAD")
        unpushed = ahead.strip() if ahead and ahead.strip().isdigit() else "-"

        last = git(path, "log", "-1", "--format=%cr")
        last = last.strip() if last else "no commits"

        print(f"{name[:33]:<34}{commits:>9}{dirty:>13}{unpushed:>10}  {last}")

    print()
    print("commits     = commits in the window")
    print("uncommitted = changed files not committed")
    print("unpushed    = commits ahead of upstream ('-' means no upstream set)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="~/Developer")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    survey(args.root, args.days)


if __name__ == "__main__":
    main()
