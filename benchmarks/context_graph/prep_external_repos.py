from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "external_repos.json"


def run_git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout.strip()


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "repos" not in data or not isinstance(data["repos"], list):
        raise ValueError("external repo manifest must contain a repos array")
    return data


def resolve_workspace_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT.parent.parent / path
    return path.resolve()


def clone_or_update(repo: dict, cache_dir: Path, force_fetch: bool) -> dict:
    repo_id = repo["id"]
    url = repo["url"]
    ref = repo["ref"]
    target = cache_dir / repo_id

    if target.exists():
        if force_fetch:
            run_git(["fetch", "--tags", "--prune", "origin"], cwd=target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        run_git(["clone", "--filter=blob:none", "--no-checkout", url, str(target)])
        run_git(["fetch", "--tags", "origin"], cwd=target)

    run_git(["checkout", "--detach", ref], cwd=target)
    commit = run_git(["rev-parse", "HEAD"], cwd=target)
    tracked_files = int(run_git(["ls-files"], cwd=target).count("\n") + 1)
    if tracked_files == 1 and not run_git(["ls-files"], cwd=target):
        tracked_files = 0

    return {
        "id": repo_id,
        "url": url,
        "ref": ref,
        "commit": commit,
        "path": str(target),
        "size_tier": repo.get("size_tier", ""),
        "primary_language": repo.get("primary_language", ""),
        "purpose": repo.get("purpose", ""),
        "tracked_files": tracked_files,
    }


def write_lockfile(lockfile: Path, manifest_path: Path, locked_repos: list[dict]) -> None:
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "repos": locked_repos,
    }
    lockfile.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def print_plan(manifest: dict, cache_dir: Path, lockfile: Path) -> None:
    print("External repo benchmark plan")
    print(f"cache_dir: {cache_dir}")
    print(f"lockfile:  {lockfile}")
    print("")
    for repo in manifest["repos"]:
        print(
            f"- {repo['id']}: {repo['url']} @ {repo['ref']} "
            f"({repo.get('primary_language', 'unknown')}, {repo.get('size_tier', 'unknown')})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone and lock external repos for context-graph benchmarks.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run", action="store_true", help="Print the repo set without cloning.")
    parser.add_argument("--force-fetch", action="store_true", help="Fetch tags/prune existing clones before checkout.")
    parser.add_argument("--only", action="append", default=[], help="Repo id to clone. May be repeated.")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    cache_dir = resolve_workspace_path(manifest["cache_dir"])
    lockfile = resolve_workspace_path(manifest["lockfile"])

    selected = manifest["repos"]
    if args.only:
        wanted = set(args.only)
        selected = [repo for repo in selected if repo["id"] in wanted]
        missing = sorted(wanted - {repo["id"] for repo in selected})
        if missing:
            raise SystemExit(f"Unknown repo id(s): {', '.join(missing)}")

    manifest = {**manifest, "repos": selected}
    if args.dry_run:
        print_plan(manifest, cache_dir, lockfile)
        return

    locked = []
    for repo in selected:
        print(f"Preparing {repo['id']}...", flush=True)
        locked.append(clone_or_update(repo, cache_dir, args.force_fetch))

    write_lockfile(lockfile, manifest_path, locked)
    print("")
    print(f"Wrote {lockfile}")
    for repo in locked:
        print(f"- {repo['id']}: {repo['commit']} ({repo['tracked_files']} tracked files)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or str(exc))
        raise SystemExit(exc.returncode)
