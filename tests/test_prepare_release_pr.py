"""Exercise discovery and lockfile refresh using the observed bot PR shape."""

import json

from scripts import prepare_release_pr


def test_prepares_component_release_branch(monkeypatch) -> None:
    repository = "jakeryderv/sourcesift"
    branch = "release-please--branches--main--components--sourcesift"
    pr = {
        "number": 2,
        "user": {"login": "github-actions[bot]"},
        "head": {"sha": "head-sha", "repo": {"full_name": repository}},
        "base": {"ref": "main"},
        "labels": [{"name": "autorelease: pending"}],
    }
    responses = {
        (
            "gh",
            "api",
            f"repos/{repository}/pulls?state=open&head=jakeryderv:{branch}",
        ): json.dumps([pr]),
        ("git", "rev-parse", "HEAD"): "head-sha",
        ("git", "diff", "--name-only"): "uv.lock",
    }
    commands = []
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    monkeypatch.setattr(prepare_release_pr, "output", lambda *args: responses[args])
    monkeypatch.setattr(prepare_release_pr, "run", lambda *args: commands.append(args))

    prepare_release_pr.main()

    assert ("git", "fetch", "origin", branch) in commands
    assert ("uv", "lock") in commands
    assert ("git", "push", "origin", f"HEAD:refs/heads/{branch}") in commands
    assert commands[-1] == (
        "gh",
        "workflow",
        "run",
        "ci.yml",
        "--ref",
        branch,
        "-f",
        "pr_number=2",
    )
