"""Publish accio into the release marketplace: a clean copy of the plugin parts plus a marketplace entry.

It ships exactly the committed files git tracks (never ignored or untracked files, never symlinks), checks
everything before it changes anything, and never commits or pushes in the release repo; that stays the user's step.
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

PLUGIN_NAME = "accio"
DEFAULT_SOURCE = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DEST = pathlib.Path.home() / "Workspace" / "claude-plugins-release"
SHIPPED = (".claude-plugin", "agents", "skills", "workflows", "hooks", "bin", "README.md")
MARKETPLACE = pathlib.Path(".claude-plugin") / "marketplace.json"
REQUIRED_MANIFEST_KEYS = ("version", "description")
REGULAR_FILE_MODES = ("100644", "100755")
KIND_BY_MODE = {"120000": "a symlink", "160000": "a git submodule"}


class PublishError(Exception):
    """A reason to stop, written for the user."""


def run_git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def check_clean(source):
    result = run_git(source, "status", "--porcelain")
    if result.returncode != 0:
        raise PublishError(f"{source} is not a git checkout: {result.stderr.strip()}")
    if result.stdout.strip():
        raise PublishError("the working tree has uncommitted changes; commit them first, so the release matches a commit")


def check_release_clean(dest):
    result = run_git(dest, "status", "--porcelain", "--", PLUGIN_NAME, str(MARKETPLACE))
    if result.returncode != 0:
        raise PublishError(f"{dest} is not a git checkout: {result.stderr.strip()}")
    if result.stdout.strip():
        raise PublishError(
            f"{dest} has uncommitted changes in {PLUGIN_NAME}/ or {MARKETPLACE}; commit or discard them there first"
        )


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PublishError(f"{path} is missing") from error
    except json.JSONDecodeError as error:
        raise PublishError(f"{path} is not valid JSON: {error}") from error


def read_manifest(source):
    manifest = load_json(source / ".claude-plugin" / "plugin.json")
    if manifest.get("name") != PLUGIN_NAME:
        raise PublishError(f"the manifest is named {manifest.get('name')!r}, not {PLUGIN_NAME!r}; check --source")
    missing = [key for key in REQUIRED_MANIFEST_KEYS if not str(manifest.get(key, "")).strip()]
    if missing:
        raise PublishError(f"the manifest has no {', '.join(missing)}")
    return manifest


def read_marketplace(dest):
    marketplace = load_json(dest / MARKETPLACE)
    plugins = marketplace.get("plugins", [])
    if not isinstance(plugins, list) or not all(isinstance(plugin, dict) for plugin in plugins):
        raise PublishError(f"{dest / MARKETPLACE} has a 'plugins' value that is not a list of objects")
    return marketplace


def shipped_files(source):
    """The committed paths to ship, from git's index; refuses anything but regular files."""
    result = run_git(source, "ls-files", "-s", "-z", "--", *SHIPPED)
    if result.returncode != 0:
        raise PublishError(f"git could not list the files to ship: {result.stderr.strip()}")
    files = []
    for record in filter(None, result.stdout.split("\0")):
        meta, path = record.split("\t", 1)
        mode = meta.split(" ", 1)[0]
        if mode not in REGULAR_FILE_MODES:
            kind = KIND_BY_MODE.get(mode, f"not a regular file (git mode {mode})")
            raise PublishError(f"{path} is {kind}; accio ships only regular files")
        files.append(path)
    return tuple(files)


def check_target(target):
    if target.is_symlink():
        raise PublishError(f"{target} is a symlink; replace it with a plain folder first")
    if target.exists() and not target.is_dir():
        raise PublishError(f"{target} exists and is not a folder")


def head_sha(source):
    result = run_git(source, "rev-parse", "--short", "HEAD")
    if result.returncode != 0:
        raise PublishError(f"git could not read HEAD: {result.stderr.strip()}")
    return result.stdout.strip()


def copy_files(source, target, files):
    if target.exists():
        shutil.rmtree(target)
    for relative in files:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination, follow_symlinks=False)


def with_entry(marketplace, entry):
    """Return a copy of the marketplace with entry merged into its namesake (keeping extra fields), or appended."""
    plugins = marketplace.get("plugins", [])
    if any(plugin.get("name") == entry["name"] for plugin in plugins):
        plugins = [{**plugin, **entry} if plugin.get("name") == entry["name"] else plugin for plugin in plugins]
    else:
        plugins = [*plugins, entry]
    return {**marketplace, "plugins": plugins}


def publish(source, dest):
    check_clean(source)
    check_release_clean(dest)
    manifest = read_manifest(source)
    marketplace = read_marketplace(dest)
    files = shipped_files(source)
    target = dest / PLUGIN_NAME
    check_target(target)
    sha = head_sha(source)

    copy_files(source, target, files)
    entry = {"name": PLUGIN_NAME, "source": f"./{PLUGIN_NAME}", "description": manifest["description"]}
    text = json.dumps(with_entry(marketplace, entry), indent=2, ensure_ascii=False) + "\n"
    (dest / MARKETPLACE).write_text(text, encoding="utf-8")
    return manifest["version"], sha


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dest", type=pathlib.Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    try:
        version, sha = publish(args.source.resolve(), args.dest.resolve())
    except PublishError as error:
        print(f"publish stopped: {error}", file=sys.stderr)
        return 1
    print(f"Published {PLUGIN_NAME} {version} (commit {sha}) to {args.dest / PLUGIN_NAME}.")
    print(f"Next: review, commit and push in {args.dest} yourself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
