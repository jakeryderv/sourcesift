"""Refresh the bot's release lockfile and explicitly start CI with GITHUB_TOKEN."""

import json
import os
import subprocess

from scripts.release_checks import RELEASE_BRANCH


def output(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    prs = json.loads(
        output(
            "gh",
            "api",
            f"repos/{repository}/pulls?state=open&head={repository.split('/')[0]}:{RELEASE_BRANCH}",
        )
    )
    if not prs:
        print("No pending release PR")
        return
    if len(prs) != 1:
        raise ValueError("Expected one release PR")
    pr = prs[0]
    if (
        pr["user"]["login"] != "github-actions[bot]"
        or pr["head"]["repo"]["full_name"] != repository
        or pr["base"]["ref"] != "main"
        or "autorelease: pending" not in {label["name"] for label in pr["labels"]}
    ):
        raise ValueError("Refusing to modify a PR not owned by release automation")
    run("git", "fetch", "origin", RELEASE_BRANCH)
    run("git", "checkout", "-B", RELEASE_BRANCH, "FETCH_HEAD")
    if output("git", "rev-parse", "HEAD") != pr["head"]["sha"]:
        raise ValueError("Release PR changed during preparation; rerun automation")
    run("uv", "lock")
    changed = output("git", "diff", "--name-only").splitlines()
    if changed:
        if changed != ["uv.lock"]:
            raise ValueError(f"Unexpected changes from uv lock: {changed}")
        run("git", "config", "user.name", "github-actions[bot]")
        run(
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        )
        run("git", "add", "uv.lock")
        run("git", "commit", "-m", "chore: refresh release lockfile")
        run("git", "push", "origin", f"HEAD:refs/heads/{RELEASE_BRANCH}")
    run(
        "gh",
        "workflow",
        "run",
        "ci.yml",
        "--ref",
        RELEASE_BRANCH,
        "-f",
        f"pr_number={pr['number']}",
    )
    print(f"Started CI for release PR #{pr['number']}")


if __name__ == "__main__":
    main()
