# CLAUDE.md — CellBlender codebase wiki & maintenance

Portable, in-tree guidance for working on **CellBlender** and on this wiki. It travels with the
`cellblender_codebase_wiki/` folder to any machine (unlike `~/.claude/.../memory/`, which is
machine-local).

> **This wiki is self-contained.** It documents the `cellblender/` repo only and intentionally does
> **not** touch the build root's `CLAUDE.md` (that signpost is for MCell). Everything CellBlender
> lives here.

## `$ROOT` — resolving paths on your machine (read first)

The wiki is portable: it carries **no machine-specific absolute paths**. Every source citation in
every doc is written **relative to a single anchor, `$ROOT`**, e.g. `cellblender/cellblender_main.py:894`.

**`$ROOT` is self-locating — it is the directory that contains both `cellblender/` and
`cellblender_codebase_wiki/`, i.e. the parent of the folder this file lives in.** There is nothing
to configure and no need to ask anyone: wherever the folder is cloned, `$ROOT` is "one level up"
from this wiki directory. (On the machine these docs were authored, `$ROOT` happened to be a folder
named `mcell_p313`, but the name is irrelevant — do not rely on it.)

At the start of a session, resolve it once. From the wiki directory:

```sh
ROOT=$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)   # inside a script
# …or interactively, from within cellblender_codebase_wiki/:
ROOT=$(cd .. && pwd)
```

Then `cellblender/<file>.py:line` citations resolve as `$ROOT/cellblender/<file>.py`. In a Claude
Code session whose working directory is `$ROOT`, the `cellblender/...` paths are already clickable
as-is. The wiki docs referenced as `NN_*.md` are siblings of this file.

## What CellBlender is

CellBlender is a **Blender add-on** (pure Python, ~34 k lines of top-level `cellblender_*.py` plus
domain subpackages) that is the graphical front-end for the **MCell** spatial reaction–diffusion
simulator. You build geometry with Blender's mesh tools, define molecules/reactions/releases/
surface properties/run settings through CellBlender's panels, run MCell, and visualize results back
in the 3-D viewport. It is its own git repo (`github.com/mcellteam/cellblender`), a sibling of
`mcell/` under the (non-git) build root. It ships as a **Blender 4.x extension**
(`blender_manifest.toml`, not legacy `bl_info`).

> **Watch out for the `cellblender -> .` self-symlink** inside the repo. Always reference the real
> path (`cellblender/cellblender_main.py`), never the doubled `cellblender/cellblender/...`.

## The wiki — start here for any structural question

Entry point: **`00_overview.md`** (architecture, boot/registration, the data-model hub, integration
map, reading guide). Then:
- `01_addon_core_and_ui_framework.md` — `__init__.py` registration, the root `MCellPropertyGroup`,
  the single host panel + draw-dispatch, preferences/utils/scripting, the build-id SHA.
- `02_chemistry_molecules_reactions.md` — molecules, reactions, release, surface classes, molmaker,
  glyphs.
- `03_geometry_objects_regions.md` — model objects, surface regions, partitions, meshalyzer, PBC.
- `04_parameter_system.md` — general vs panel parameters, expression eval + dependency graph.
- `05_data_model_and_mdl_io.md` — the dict-tree interchange format + version-upgrade chain, MDL I/O.
- `06_simulation_run_and_engines.md` — the export→engine→runner→output run pipeline, BNGL/SBML.
- `07_visualization_and_reaction_output.md` — molecule viz (frame handlers) + reaction count output.

Every doc carries `file_path:line` citations. **Prefer reading the relevant wiki doc before
re-deriving structure from source.**

Key facts worth holding (details + citations in the wiki):
- **Classic Blender add-on shape:** PropertyGroups (data on the `.blend`), `MCELL_OT_*` Operators,
  `MCELL_PT_*`/`MCELL_UL_*` UI. `register()` in `__init__.py` loops the `IMPORT_MODULE_NAMES` tuple;
  `cellblender_main` registers **last**. Root context is **`MCellPropertyGroup`** on
  `bpy.context.scene.mcell`; every domain hangs off it via `PointerProperty` and there is **one**
  host panel that dispatches to each group's `draw_layout`. (doc 01)
- **The data model is the architectural hub.** A pure nested dict/list (no `bpy` types), versioned,
  stored in the `.blend` and exportable as JSON. Every domain implements the five-method contract
  (`init_properties`, `build_data_model_from_properties`, `upgrade_data_model`,
  `build_properties_from_data_model`, `check_properties_after_building`). Saved models carry
  `DM_YYYY_MM_DD_HHMM` stamps and upgrade forward via per-domain `if`-cascades. (doc 05)
- **Everything numeric is parameter-backed.** Rates, diffusion constants, counts, coordinates embed
  a `Parameter_Reference` holding an expression string; `parameter_system.py` evaluates expressions
  with **unsandboxed `eval()`** over a topologically-sorted dependency graph. `ParameterSpace.py` is
  dead code. (doc 04)
- **Cross-references are by name string, not pointer** (species in reactions/releases/surf-classes;
  surface classes on regions) — renames don't cascade. (doc 02/03)
- **Run pipeline:** export the data model to **MDL** (MCell3) or an **MCell4 Python** script,
  enqueue on a `SimQueue`, run one `run_wrapper.py` shim per job; a pluggable engine/runner system
  backs the experimental dynamic path. (doc 06)
- **Build identity:** `cellblender_id.py` is a SHA over the source file list; a mismatch triggers
  data-model upgrades. **Run `python3 update_cellblender_id.py` before any pushed commit** (the
  repo's own standing rule — see `cellblender/CLAUDE.md`). (doc 01/05)

## Keeping the wiki in sync (after changing code, or before trusting the wiki)

`MAINTENANCE.md` is the full playbook (change→doc map in §2, data-model trigger in §4, drift
checklist in §5, the helper in §6). The helper is **`wiki_check.py`** — stdlib-only, lives in this
dir, **never writes to the source repo's tracked files**, and hardcodes no paths.

```sh
cd cellblender_codebase_wiki
./wiki_check.py                       # audit: citation drift + which docs changed source maps to
./wiki_check.py --since origin/master # what changed on this branch vs master → docs to update
./wiki_check.py --staged --strict     # gate mode (nonzero exit) — for a local pre-commit hook
./wiki_check.py --mark-stale --staged # flag implicated docs with a "possibly stale" banner
./wiki_check.py --clear-stale         # remove the banners once docs are updated
```

After editing a domain module, re-check the wiki doc(s) the helper names and refresh their prose +
`file_path:line` citations. For a subsystem-level rewrite, re-running the multi-agent mapping pass
for the affected doc is cleaner than hand-patching (see MAINTENANCE.md §1 and §7).

### CAVEAT — how the citation check behaves (don't over-trust it)
`wiki_check.py`'s citation check is deliberately **conservative to avoid false positives**: it flags
a cited file as `MISSING` only when that **basename exists nowhere** in the tree. A citation that
points at the *wrong directory* but whose filename still exists somewhere is **not** flagged. So it
reliably catches deleted/renamed files and out-of-range line numbers, but will **not** catch a
path-prefix mistake (right filename, wrong folder) — use the MAINTENANCE.md §5 spot-check for those.
The index walk deliberately does **not** follow the `cellblender -> .` self-symlink.

## How to modify the tooling (when docs or watched areas change)

- **Add / rename a wiki doc, or watch a new source area:** edit the **`RULES`** list near the top of
  `wiki_check.py` (the `(repo, path-regex, [doc-prefixes], reason)` rows) **and** the §2 change→doc
  table in `MAINTENANCE.md` together — they are intentional mirrors. Doc prefixes (`"01"`, `"02"`, …)
  are resolved by globbing `NN_*.md`, so renaming a doc's *title* is fine; renaming its *number
  prefix* means updating `RULES`.
- **Change the stale-banner text/markers:** edit `banner_text()` / `BANNER_START` / `BANNER_END`.
  Keep insert/remove symmetric — `--mark-stale` then `--clear-stale` must leave docs byte-identical.
- **Tune what counts as a citation:** `CITATION_RE` / `SRC_EXT` / `_is_placeholder()` / `PRUNE_DIRS`.
- The script is intentionally dependency-free (Python 3 stdlib only). Keep it that way.

## Conventions

- Treat a wiki update as part of "done" for any change touching a documented module or the data
  model — same as updating a changelog.
- Don't commit anything into `cellblender/` for wiki/tooling purposes; the wiki and its helper live
  at the build-root level on purpose. A pre-commit hook, if wanted, goes in a maintainer's local
  `.git/hooks/` (uncommitted) — see MAINTENANCE.md §6.
- The CellBlender repo has its **own** `cellblender/CLAUDE.md` with one standing rule (refresh
  `cellblender_id.py` before commits). That rule is real and orthogonal to this wiki — honor both.
- This wiki folder is self-contained; if you move/rename it, nothing at the build root needs
  updating (no signpost points here by design).
