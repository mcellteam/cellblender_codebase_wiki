#!/usr/bin/env python3
"""wiki_check.py — keep the CellBlender codebase wiki in sync with the source.

Standalone and stdlib-only. This script lives *inside* `cellblender_codebase_wiki/`
and travels with it. It NEVER writes to a source git repo's tracked files, so it is
safe to use on a tree shared by several maintainers — nothing gets committed into
`cellblender/` by running it.

It does what a pre-commit reminder hook would do, but parametrized — no paths are
hardcoded. You pass (or let it derive) the wiki directory and the CellBlender repo;
everything else follows.

JOBS
  check        (default) read-only report:
                 * cited file paths in the wiki that no longer exist
                 * cited `path:line` refs whose line number is now out of range
                 * sensitive source changes (staged / since a ref) mapped to the
                   wiki docs that probably need updating (the MAINTENANCE §2 map)
  --mark-stale MODIFY the implicated wiki docs by inserting/refreshing a visible
                 "possibly stale" banner (idempotent; lives between HTML markers)
  --clear-stale MODIFY: remove all stale banners (run after you've updated docs)

PATHS (nothing hardcoded)
  --wiki DIR   wiki directory                 (default: this script's directory)
  --root DIR   project root                    (default: parent of --wiki, so that
               root-relative citations like `cellblender/cellblender_main.py` resolve)
  --repo DIR   a source git repo to inspect; repeatable
               (default: the `cellblender/` repo under --root, else every immediate
               subdir of --root that has a .git)

CHANGE SOURCE (for the change->doc reminder)
  --staged     only staged changes            (use this from a pre-commit hook)
  --since REF  changes since REF (REF..worktree)
  (default)    working-tree + staged vs HEAD

EXIT CODE
  0 by default (advisory — safe as a non-blocking hook).
  Pass --strict to exit 1 when any drift or pending-update is found
  (turns it into a gate).

Examples
  ./wiki_check.py                          # audit from the wiki dir, report
  ./wiki_check.py --staged --strict        # as a blocking pre-commit gate
  ./wiki_check.py --since origin/master    # what changed on this branch vs master
  ./wiki_check.py --mark-stale --staged    # flag docs touched by this commit
  ./wiki_check.py --clear-stale            # clear flags once docs are updated
"""

from __future__ import annotations
import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

# --- the MAINTENANCE.md §2 "change -> document" map, as data --------------
# Each rule: (repo_basename or None=any, path-regex, [doc-number-prefixes], reason)
# Paths are CellBlender-repo-relative (what `git diff --name-only` prints, e.g.
# "cellblender_main.py", "bng/net.py"). Doc prefixes are resolved to real files
# by globbing "<prefix>_*.md" in the wiki dir, so renaming a doc's title does not
# break this. Rules are most-specific-first; the FIRST matching rule wins.
RULES = [
    # add-on core, registration, UI framework, preferences, scripting, build-id
    ("cellblender",
     r"^(__init__|cellblender_main|cellblender_initialization|cellblender_preferences|"
     r"cellblender_utils|cellblender_project|cellblender_scripting|cellblender_examples|"
     r"cellblender_legacy|cellblender_source_info|cellblender_id|update_cellblender_id)\.py$",
     ["01", "00"], "add-on core / UI framework / build-id"),
    # chemistry domains
    ("cellblender",
     r"^cellblender_(molecules|reactions|release|surface_classes|molmaker|glyphs)\.py$",
     ["02", "00"], "chemistry (molecules/reactions/release/surf-classes)"),
    # geometry domains
    ("cellblender",
     r"^(cellblender_(objects|surface_regions|partitions|meshalyzer|pbc)|object_surface_regions)\.py$",
     ["03", "00"], "geometry (objects/regions/partitions/mesh)"),
    # parameter system
    ("cellblender", r"^(parameter_system|ParameterSpace)\.py$",
     ["04", "00"], "parameter system"),
    # data model + MDL/file I/O + plotters
    ("cellblender", r"^data_model\.py$|^io_mesh_mcell_mdl/|^mdl/|^data_plotters/",
     ["05", "00"], "data model / MDL I/O"),
    # run pipeline, engines, runners, BNG
    ("cellblender",
     r"^cellblender_simulation\.py$|^sim_engine_manager/|^sim_runner_manager/|"
     r"^run_simulations\.py$|^run_wrapper\.py$|^sim_runner_queue\.py$|"
     r"^old_sim_engines/|^mcell4/|^bng/",
     ["06", "00"], "simulation run / engines / runners / BNG"),
    # visualization + reaction output
    ("cellblender", r"^cellblender_(mol_viz|reaction_output)\.py$",
     ["07", "00"], "visualization / reaction output"),
    # packaging / manifest / build
    ("cellblender", r"blender_manifest\.toml$|^make_bundle\.sh$|^makefile$|^CHANGELOG\.md$",
     ["00"], "packaging / manifest"),
]

# Source-citation regex. CellBlender is mostly Python; also cite MDL, the vendored
# SWIG C parser, manifests, and JSON/text data. Extensions are ordered so longer
# tokens win and the trailing lookahead stops `.c` matching inside `.cfg`.
SRC_EXT = r"(?:toml|json|yaml|yml|mdl|cpp|cfg|sh|py|txt|c|h|i)"
CITATION_RE = re.compile(
    r"([A-Za-z0-9_][\w./+-]*\." + SRC_EXT + r")(?![A-Za-z0-9_])(?::(\d+))?"
)

# directories never worth indexing (build output, vcs, venvs, IDE, big bundles)
PRUNE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "node_modules",
    ".idea", ".settings", "build", "work", "dist", "META-INF",
    "cmake-build-debug", "cmake-build-release", "cmake-build-relwithdebinfo",
}

BANNER_START = "<!-- wiki-check:stale -->"
BANNER_END = "<!-- /wiki-check:stale -->"


def sh(repo: Path, *args: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def discover_repos(root: Path) -> list[Path]:
    # Prefer the CellBlender repo itself; fall back to every immediate sub-repo.
    cb = root / "cellblender"
    if (cb / ".git").exists():
        return [cb]
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())


def changed_files(repo: Path, staged: bool, since: str | None) -> list[str]:
    if since:
        return sh(repo, "diff", "--name-only", f"{since}", "--")
    if staged:
        return sh(repo, "diff", "--cached", "--name-only")
    # default: anything different from HEAD (staged + unstaged), plus untracked
    files = sh(repo, "diff", "--name-only", "HEAD")
    files += sh(repo, "ls-files", "--others", "--exclude-standard")
    return files


def resolve_doc_files(wiki: Path, prefixes: list[str]) -> list[Path]:
    found: list[Path] = []
    for pre in prefixes:
        hits = sorted(wiki.glob(f"{pre}_*.md")) or sorted(wiki.glob(f"{pre}*.md"))
        found.extend(hits)
    return found


# ---------------------------------------------------------------------------
# file index (root-relative posix paths), grouped by basename for fast lookup
# ---------------------------------------------------------------------------
def build_index(root: Path) -> dict[str, list[str]]:
    import os
    by_base: dict[str, list[str]] = {}
    # followlinks=False (default) so the `cellblender -> .` self-symlink inside the
    # repo is NOT descended — otherwise os.walk would re-index the tree under a
    # bogus `cellblender/cellblender/...` prefix (or loop).
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        rel_dir = Path(dirpath).relative_to(root)
        for fn in filenames:
            rel = (rel_dir / fn).as_posix()
            by_base.setdefault(fn, []).append(rel)
    return by_base


def _is_placeholder(rel: str) -> bool:
    # skip shorthand/placeholders, not real files:
    #   foo.py/.json (a slash right after a dot), src/.../x.py, gen_x.py, x.py
    if "/." in rel or "..." in rel:
        return True
    base = rel.rsplit("/", 1)[-1]
    if base.startswith("."):           # hidden / empty-stem like ".py"
        return True
    stem = base.rsplit(".", 1)[0]
    if stem == "x" or stem.endswith("_x"):   # x.py, gen_x.py
        return True
    return False


# ---------------------------------------------------------------------------
# 1. citation / line-number drift
# ---------------------------------------------------------------------------
def citation_report(wiki: Path, root: Path, index: dict[str, list[str]]) -> list[str]:
    problems: list[str] = []

    def resolve(rel: str) -> Path | None:
        base = rel.rsplit("/", 1)[-1]
        for full in index.get(base, ()):
            if full == rel or full.endswith("/" + rel):
                return root / full
        return None

    for md in sorted(wiki.glob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in CITATION_RE.finditer(line):
                rel, num = m.group(1), m.group(2)
                if "/" not in rel or _is_placeholder(rel):
                    continue
                target = resolve(rel)
                if target is None:
                    base = rel.rsplit("/", 1)[-1]
                    # only a high-confidence MISSING when the basename exists
                    # NOWHERE in the tree; a basename that exists elsewhere is
                    # just an imprecise path prefix, not drift -> stay quiet.
                    if base not in index:
                        problems.append(f"{md.name}:{lineno}  MISSING FILE  -> {rel}")
                    continue
                if num is not None:
                    try:
                        total = sum(1 for _ in target.open("rb"))
                    except OSError:
                        continue
                    if int(num) > total:
                        problems.append(
                            f"{md.name}:{lineno}  LINE OUT OF RANGE  -> "
                            f"{rel}:{num} (file has {total} lines)"
                        )
    return problems


# ---------------------------------------------------------------------------
# 2. sensitive-change -> doc reminder
# ---------------------------------------------------------------------------
def change_report(wiki: Path, repos: list[Path], staged: bool, since: str | None):
    # returns (lines_to_print, set_of_doc_files_implicated)
    lines: list[str] = []
    implicated: dict[Path, set[str]] = {}
    compiled = [(rn, re.compile(rx), docs, why) for rn, rx, docs, why in RULES]

    for repo in repos:
        files = changed_files(repo, staged, since)
        if not files:
            continue
        repo_name = repo.name
        for f in files:
            for rn, rx, docs, why in compiled:
                if rn is not None and rn != repo_name:
                    continue
                if rx.search(f):
                    for doc in resolve_doc_files(wiki, docs):
                        implicated.setdefault(doc, set()).add(why)
                    break  # first matching rule wins (rules are most-specific-first)

    if implicated:
        lines.append("Source changes map to these wiki docs (MAINTENANCE.md §2):")
        for doc in sorted(implicated):
            reasons = ", ".join(sorted(implicated[doc]))
            lines.append(f"  • {doc.name:42s} <- {reasons}")
    return lines, implicated


# ---------------------------------------------------------------------------
# 3. modify: stale banners
# ---------------------------------------------------------------------------
def banner_text(reasons: set[str], today: str) -> str:
    why = ", ".join(sorted(reasons))
    return (
        f"{BANNER_START}\n"
        f"> ⚠️ **Possibly stale** (flagged {today}). Source changes touched: {why}. "
        f"Review against the current code and clear with "
        f"`wiki_check.py --clear-stale`. See MAINTENANCE.md §2.\n"
        f"{BANNER_END}\n"
    )


def strip_banner(text: str) -> str:
    # remove the banner block including the single newline that follows it, then
    # collapse any run of 3+ newlines (which a banner insert/remove cycle could
    # leave behind) back to one blank line so the round-trip is byte-clean.
    pattern = re.compile(
        re.escape(BANNER_START) + r".*?" + re.escape(BANNER_END) + r"\n?",
        re.DOTALL,
    )
    text = pattern.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def mark_stale(implicated: dict[Path, set[str]]) -> int:
    today = datetime.date.today().isoformat()
    n = 0
    for doc, reasons in implicated.items():
        text = doc.read_text(encoding="utf-8", errors="replace")
        text = strip_banner(text)  # idempotent: drop any previous banner first
        lines = text.splitlines(keepends=True)
        # insert right after the first level-1 heading, no surrounding blank
        # lines (so strip_banner restores the file exactly).
        insert_at = 0
        for i, ln in enumerate(lines):
            if ln.startswith("# "):
                insert_at = i + 1
                break
        lines.insert(insert_at, banner_text(reasons, today))
        doc.write_text("".join(lines), encoding="utf-8")
        n += 1
    return n


def clear_stale(wiki: Path) -> int:
    n = 0
    for md in sorted(wiki.glob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        new = strip_banner(text)
        if new != text:
            md.write_text(new, encoding="utf-8")
            n += 1
    return n


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check (and optionally flag) CellBlender wiki drift vs. the source.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    here = Path(__file__).resolve().parent
    ap.add_argument("--wiki", type=Path, default=here, help="wiki directory")
    ap.add_argument("--root", type=Path, default=None, help="project root (default: parent of --wiki)")
    ap.add_argument("--repo", type=Path, action="append", default=[], help="source repo (repeatable)")
    ap.add_argument("--staged", action="store_true", help="only staged changes (for a hook)")
    ap.add_argument("--since", default=None, help="changes since REF")
    ap.add_argument("--mark-stale", action="store_true", help="MODIFY: flag implicated docs")
    ap.add_argument("--clear-stale", action="store_true", help="MODIFY: remove all stale flags")
    ap.add_argument("--no-citations", action="store_true", help="skip the citation/line check")
    ap.add_argument("--no-changes", action="store_true", help="skip the change->doc reminder")
    ap.add_argument("--strict", action="store_true", help="exit 1 if anything is found")
    args = ap.parse_args()

    wiki = args.wiki.resolve()
    if not wiki.is_dir():
        print(f"wiki_check: --wiki is not a directory: {wiki}", file=sys.stderr)
        return 2
    root = (args.root or wiki.parent).resolve()
    repos = [p.resolve() for p in args.repo] or discover_repos(root)

    print(f"wiki_check: wiki={wiki}")
    print(f"wiki_check: root={root}")
    print(f"wiki_check: repos={', '.join(r.name for r in repos) or '(none found)'}")
    print("-" * 72)

    if args.clear_stale:
        n = clear_stale(wiki)
        print(f"cleared stale banners from {n} doc(s).")
        return 0

    found = False

    if not args.no_citations:
        probs = citation_report(wiki, root, build_index(root))
        if probs:
            found = True
            print(f"CITATION DRIFT ({len(probs)}):")
            for p in probs:
                print("  " + p)
        else:
            print("citations: all cited paths resolve and line numbers are in range. ✔")
        print("-" * 72)

    implicated: dict[Path, set[str]] = {}
    if not args.no_changes:
        lines, implicated = change_report(wiki, repos, args.staged, args.since)
        if lines:
            found = True
            for ln in lines:
                print(ln)
        else:
            print("changes: no sensitive source changes detected. ✔")
        print("-" * 72)

    if args.mark_stale and implicated:
        n = mark_stale(implicated)
        print(f"marked {n} doc(s) as possibly stale (banner inserted).")

    if found:
        print("\nwiki may be out of date — see MAINTENANCE.md for how to refresh.")
    else:
        print("\nwiki looks in sync.")

    return 1 if (found and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
