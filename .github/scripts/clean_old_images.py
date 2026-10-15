#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys


def run_cmd(*args: str) -> str:
    res = subprocess.run(args, capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def get_active_shas(image: str) -> set[str]:
    raw = run_cmd("docker", "buildx", "imagetools", "inspect", "--raw", image)
    if not raw:
        sys.exit(f"error: failed to inspect manifest for {image}")

    data = json.loads(raw)
    shas = {m["digest"] for m in data.get("manifests", []) if "digest" in m}
    if not shas:
        sys.exit(f"error: no child manifests found in {image}")
    return shas


def get_obsolete_versions(owner: str, package: str, is_org: bool, keep_shas: set[str]) -> list[tuple[int, str]]:
    base = "orgs" if is_org else "users"
    endpoint = f"/{base}/{owner}/packages/container/{package}/versions"
    obsolete: list[tuple[int, str]] = []
    page = 1

    while True:
        raw = run_cmd("gh", "api", f"{endpoint}?per_page=100&page={page}")
        if not raw:
            break

        versions = json.loads(raw)
        for v in versions:
            tags = v.get("metadata", {}).get("container", {}).get("tags")
            sha = v.get("name", "")
            if not tags and sha not in keep_shas:
                obsolete.append((v["id"], sha))

        if len(versions) < 100:
            break
        page += 1

    return obsolete


def delete_versions(owner: str, package: str, is_org: bool, versions: list[tuple[int, str]]) -> None:
    if not versions:
        print("registry clean: no obsolete images found")
        return

    print(f"deleting {len(versions)} obsolete version(s)...")
    deleted = 0
    del_path = f"/orgs/{owner}" if is_org else "/user"

    for vid, sha in versions:
        cmd = ["gh", "api", "--silent", "-X", "DELETE", f"{del_path}/packages/container/{package}/versions/{vid}"]
        res = subprocess.run(cmd, capture_output=True)

        if res.returncode != 0 and not is_org:
            fallback = ["gh", "api", "--silent", "-X", "DELETE", f"/users/{owner}/packages/container/{package}/versions/{vid}"]
            res = subprocess.run(fallback, capture_output=True)

        if res.returncode == 0:
            deleted += 1
            print(f"deleted {sha[:19]} (id: {vid})")
        else:
            print(f"failed to delete {sha[:19]} (id: {vid})", file=sys.stderr)

    print(f"completed: deleted {deleted}/{len(versions)} version(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge obsolete untagged GHCR images.")
    parser.add_argument("--image", required=True, help="Reference image, e.g. ghcr.io/owner/repo:main")
    args = parser.parse_args()

    image = args.image if ":" in args.image else f"{args.image}:main"
    try:
        owner, package = image.split(":")[0].split("/")[-2:]
    except ValueError:
        sys.exit("error: image must follow 'ghcr.io/<owner>/<package>:<tag>' format")

    owner, package = owner.lower(), package.lower()
    is_org = subprocess.run(["gh", "api", f"/orgs/{owner}", "--silent"]).returncode == 0

    keep_shas = get_active_shas(image)
    obsolete = get_obsolete_versions(owner, package, is_org, keep_shas)
    delete_versions(owner, package, is_org, obsolete)


if __name__ == "__main__":
    main()
