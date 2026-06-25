# CellBlender Codebase Wiki

A maintainer-oriented **codebase wiki** for [CellBlender](https://github.com/mcellteam/cellblender)
— the Blender add-on (pure Python) that is the graphical front-end for the
[MCell](https://mcell.org) spatial reaction–diffusion simulator.

It maps how the ~34k-line add-on is structured: how it boots and registers, the per-domain
PropertyGroup/Operator/Panel modules, the central **data model** interchange format, the parameter
system, and the export→run→visualize pipeline — so you don't have to re-read the whole tree each
time. Every structural claim carries a `file_path:line` citation into the real source.

It was produced by a multi-agent mapping pass (one agent per domain document) and is kept in sync
with the code via the maintenance workflow below.

## Documents

Start with **`00_overview.md`** — the architecture overview, integration map, and reading guide.

| # | Document | Scope |
|---|----------|-------|
| **00** | [`00_overview.md`](00_overview.md) | Whole add-on architecture, boot/registration, the data-model hub, integration map, reading guide |
| 01 | [`01_addon_core_and_ui_framework.md`](01_addon_core_and_ui_framework.md) | `__init__.py` registration, the root `MCellPropertyGroup`, the host panel + draw-dispatch framework, preferences, the build-id SHA, scripting |
| 02 | [`02_chemistry_molecules_reactions.md`](02_chemistry_molecules_reactions.md) | Molecules, reactions, release sites, surface classes, MolMaker, display glyphs |
| 03 | [`03_geometry_objects_regions.md`](03_geometry_objects_regions.md) | Model objects, surface regions (face sets), partitions, meshalyzer, periodic boundary conditions |
| 04 | [`04_parameter_system.md`](04_parameter_system.md) | General vs panel parameters, expression eval, the dependency graph, `Parameter_Reference`, sweeps |
| 05 | [`05_data_model_and_mdl_io.md`](05_data_model_and_mdl_io.md) | The dict-tree interchange format + version-upgrade chain, MDL import/export, `data_model_to_mdl` |
| 06 | [`06_simulation_run_and_engines.md`](06_simulation_run_and_engines.md) | Run settings, the export→engine→runner→output pipeline, pluggable engine/runner managers, BNGL/SBML import |
| 07 | [`07_visualization_and_reaction_output.md`](07_visualization_and_reaction_output.md) | Molecule visualization (frame handlers) and reaction count output (+ external plotters) |

Plus:
- [`MAINTENANCE.md`](MAINTENANCE.md) — how to keep the wiki current (change→doc map, drift checklist, the helper).
- [`CLAUDE.md`](CLAUDE.md) — in-tree operating guide (also read by AI coding assistants); defines the `$ROOT` convention.
- [`wiki_check.py`](wiki_check.py) — stdlib-only drift checker (citation resolution + change→doc reminder).

## Using it — the `$ROOT` convention & placement

The wiki carries **no machine-specific absolute paths**. Every citation is written relative to a
single anchor, **`$ROOT`** — the directory that contains both `cellblender/` and this
`cellblender_codebase_wiki/` folder. So a citation like `cellblender/cellblender_main.py:894` means
`$ROOT/cellblender/cellblender_main.py`.

`$ROOT` is **self-locating**: it is always the parent of this wiki folder. To make the citations
resolve (and for `wiki_check.py` to find the source), check this repo out **next to a CellBlender
checkout** so they share a parent:

```
$ROOT/
├── cellblender/                 # github.com/mcellteam/cellblender
└── cellblender_codebase_wiki/   # this repo
```

```sh
# from inside cellblender_codebase_wiki/
ROOT=$(cd .. && pwd)
```

(The repo is fully readable on its own; the placement only matters when you want to follow the
`file_path:line` citations into the actual source or run the drift checker.)

## Keeping it in sync

The wiki is a *derived artifact* of the source, and line numbers drift on almost any edit. After
changing CellBlender, update the implicated doc(s) — see [`MAINTENANCE.md`](MAINTENANCE.md) for the
change→document map and drift checklist. The helper automates it:

```sh
cd cellblender_codebase_wiki
./wiki_check.py                       # audit: citation drift + which docs changed source maps to
./wiki_check.py --since origin/master # what changed on the CellBlender branch vs master → docs to update
./wiki_check.py --staged --strict     # gate mode (nonzero exit) — for a local pre-commit hook
```

`wiki_check.py` is stdlib-only (no dependencies) and never writes to the CellBlender repo's tracked
files. It reports cited paths that no longer exist or whose line numbers are out of range, and maps
changed source files to the wiki docs that likely need updating.

## License

The wiki documents the CellBlender source; CellBlender is licensed GPL-2.0-or-later.
