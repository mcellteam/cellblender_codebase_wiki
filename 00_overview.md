# CellBlender Codebase Wiki — Overview & Integration Map

> **Audience:** maintainers and developers of **CellBlender** who need to understand, extend,
> and debug the whole add-on — its boot/registration flow, the per-domain UI modules, the central
> *data model* interchange format, the parameter system, and the export→run→visualize pipeline —
> without re-reading ~34 k lines of `cellblender_*.py` each time.
>
> **Project location:** `$ROOT/cellblender` — where **`$ROOT`** is the directory containing both
> `cellblender/` and this `cellblender_codebase_wiki/` folder (the parent of this wiki dir). All
> source citations below are written relative to `$ROOT`, e.g. `cellblender/cellblender_main.py:894`;
> see `CLAUDE.md` §"`$ROOT`" for how to resolve it on your machine.
> CellBlender is a **Blender add-on** (pure Python) that is the graphical front-end for the
> **MCell** spatial reaction–diffusion simulator. It is its own git repo
> (`github.com/mcellteam/cellblender`), a sibling of `mcell/` under the build root. This wiki is
> **self-contained** in `cellblender_codebase_wiki/` and does not touch the root `CLAUDE.md`
> (which is for MCell).

---

## 1. How to read this wiki

| # | Document | Scope |
|---|----------|-------|
| **00** | `00_overview.md` (this file) | Whole add-on architecture, boot/registration, the data-model hub, integration map, reading guide |
| 01 | [`01_addon_core_and_ui_framework.md`](01_addon_core_and_ui_framework.md) | **Add-on core** — `__init__.py` registration, the root `MCellPropertyGroup`, the single host panel + draw-dispatch framework, preferences, utils, the build-id SHA, scripting, project/examples |
| 02 | [`02_chemistry_molecules_reactions.md`](02_chemistry_molecules_reactions.md) | **Chemistry** — molecules, reactions, release sites/patterns, surface classes, MolMaker, display glyphs |
| 03 | [`03_geometry_objects_regions.md`](03_geometry_objects_regions.md) | **Geometry** — model objects, surface regions (face sets), partitions, the meshalyzer, periodic boundary conditions |
| 04 | [`04_parameter_system.md`](04_parameter_system.md) | **Parameter system** — general vs panel parameters, expression eval + dependency graph, the embedded `Parameter_Reference`, ParameterSpace |
| 05 | [`05_data_model_and_mdl_io.md`](05_data_model_and_mdl_io.md) | **Data model & I/O** — the dict-tree interchange format, the version-upgrade chain, MDL import/export, `data_model_to_mdl`, plotters dir |
| 06 | [`06_simulation_run_and_engines.md`](06_simulation_run_and_engines.md) | **Running simulations** — run settings, export→engine→runner→output pipeline, the pluggable engine/runner managers, BNGL/SBML import |
| 07 | [`07_visualization_and_reaction_output.md`](07_visualization_and_reaction_output.md) | **Results back into Blender** — spatial molecule viz (frame handlers) and reaction count output (+ external plotters) |
| — | [`MAINTENANCE.md`](MAINTENANCE.md) | **How to keep this wiki current** — change→document map, regeneration triggers, drift checklist, the `wiki_check.py` helper |

**Suggested entry paths:**
- *"How does the add-on boot / where is everything attached?"* → **01**.
- *"I need to add or change a molecule/reaction/release field"* → **02**, then **04** (the field is parameter-backed) and **05** (serialize it).
- *"I need to touch meshes, regions, or partitions"* → **03**.
- *"How are expressions / rates / sweeps computed?"* → **04**.
- *"What is the saved/exported format and how do old files upgrade?"* → **05** (the hub doc).
- *"How does Run Simulation actually launch MCell?"* → **06**, then **05** (the MDL/MCell4 export it calls).
- *"How do results show up in the viewport / in plots?"* → **07**.

---

## 2. What CellBlender is, and how it is shaped

**CellBlender** turns Blender into an MCell modeling environment: you build geometry with Blender's
mesh tools, then use CellBlender's panels to define molecules, reactions, release sites, surface
properties, simulation settings, run MCell, and visualize the results back in the 3-D viewport.

Architecturally it is a **classic Blender add-on** built from three kinds of `bpy.types`
subclasses, registered at add-on load:

- **PropertyGroups** — the *data*, stored on the `.blend` file. CellBlender hangs one big tree of
  them off the Blender scene.
- **Operators** (`MCELL_OT_*`) — the *actions* (buttons: add/remove molecule, run simulation, read
  viz data, …).
- **Panels** + **UILists** (`MCELL_PT_*`, `MCELL_UL_*`) — the *UI*.

It is packaged as a **Blender 4.x extension** (`blender_manifest.toml`) rather than a legacy
`bl_info` add-on, and `make_bundle.sh`/`cellblender.zip` produce the distributable.

```
        Blender mesh tools                 CellBlender panels (this codebase)
   (build the cell geometry)        molecules · reactions · release · surf-classes
              │                      geometry · partitions · parameters · run · viz
              ▼                                        │
     bpy.context.scene.mcell  ◄──────────────  one big PropertyGroup tree (doc 01)
        (MCellPropertyGroup)                          │ build_data_model_from_properties
              │                                       ▼
              │                         ┌─────────────────────────────┐
              │   build_properties_     │   THE DATA MODEL (doc 05)    │  pure nested
              └──────from_data_model────│  dict / list / scalar tree  │  dicts, no bpy types
                                        │  versioned, upgrade chain    │  (saved in .blend,
                                        └──────────────┬──────────────┘   export JSON)
                                                       │ export
                          ┌────────────────────────────┼───────────────────────────┐
                          ▼                             ▼                            ▼
                 mdl/data_model_to_mdl           mcell4 python script         BNGL/SBML import
                 → MCell3 / MCell3-R             → import mcell (MCell4)       (bng/, into data model)
                          └──────────── run via engine + runner (doc 06) ──────────┘
                                                       │ output files
                                                       ▼
                                   viz_data/*.dat + reaction *.dat   (doc 07)
                                   → frame-driven viewport particles + external plotters
```

---

## 3. The boot / registration flow (doc 01)

`cellblender/__init__.py` is the hub. Registration is a **fixed-order loop** over the
`IMPORT_MODULE_NAMES` tuple (`__init__.py:34`): `register()` (`__init__.py:323`) imports each named
module and calls its own `register()`, which does `bpy.utils.register_class(...)` over a `classes`
tuple. The order matters — `cellblender_main` registers **last** because the root PropertyGroup
points at the others.

- The **root context PropertyGroup** is `MCellPropertyGroup` (`cellblender_main.py:894`), attached
  as **`bpy.context.scene.mcell`** via `bpy.types.Scene.mcell = PointerProperty(...)`
  (`__init__.py:389`). A smaller `MCellObjectPropertyGroup` attaches per-object as
  `bpy.context.object.mcell`.
- Every subsystem is a PropertyGroup hung off `MCellPropertyGroup` by `PointerProperty`. Each
  implements `draw_layout(self, context, layout)` plus the **five-method data-model contract**
  (see §4) and ends with a `classes` / `register()` / `unregister()` block.
- There is **one** host panel, `MCELL_PT_main_panel` (3-D viewport sidebar), whose `draw`
  delegates to a **selector** PropertyGroup of boolean toggles that dispatches to each sub-group's
  `draw_layout`. Domain modules generally **do not** register their own Panel.
- **Build identity:** `cellblender_id.py` holds a SHA-1 over the source file list
  (`cellblender_source_info.py`), regenerated by `update_cellblender_id.py`. A mismatch between the
  stored ID in a `.blend` and the running add-on is what triggers data-model upgrades. **This ID
  must be refreshed before any pushed commit** (see the repo's own `cellblender/CLAUDE.md`).

> Gotchas (doc 01): the `imp.reload`/`cb_register()` blocks in `__init__.py` are dead code (the
> live path is the tuple loop); modules dodge circular imports with
> `globals()['cellblender']=importlib.import_module(__package__)`; some "old scene panel" code in
> `cellblender_preferences.py` is silently dead under `try/except: pass`.

---

## 4. The data model is the architectural hub (doc 05)

The single most important concept. The **data model** is a pure nested `dict`/`list`/scalar
structure — **no `bpy` types** — that is JSON- and pickle-serializable (`data_model.py:244-269`)
and stored in the `.blend` as `scene.mcell['data_model']` (an ID-property, distinct from the live
PropertyGroups). It is CellBlender's stable, version-independent interchange format and the input
to every exporter.

Every domain module implements the same contract so the whole tree can round-trip:

| Method | Direction | Role |
|---|---|---|
| `init_properties` | — | initialize the PropertyGroup |
| `build_data_model_from_properties` | properties → dict | serialize this domain's slice |
| `upgrade_data_model` *(static)* | dict → dict | migrate an older saved slice forward |
| `build_properties_from_data_model` | dict → properties | deserialize into live PropertyGroups |
| `check_properties_after_building` | — | post-load validation/fix-up |

`cellblender_main.py` orchestrates these into/out of one whole-model dict keyed by section
(`build_data_model_from_properties` at `cellblender_main.py:998`, `upgrade_data_model` at
`cellblender_main.py:1043`, `build_properties_from_data_model` at `cellblender_main.py:1165`). Saved models carry **date-coded version stamps** (`DM_YYYY_MM_DD_HHMM`, 40+ constants);
each domain's `upgrade_data_model` is a fall-through `if`-cascade that steps any older fragment up
to the current schema (canonical example: `cellblender_molecules.py` upgrade cascade). Upgrades are
triggered by the **source-SHA mismatch** detected in `@persistent` `load_post`/`save_pre` handlers
— not by comparing version strings directly.

Two export paths leave the data model:
- **`mdl/data_model_to_mdl.py`** generates full **MDL** to feed **MCell3 / MCell3-R**.
- **`mcell4/`** converts the data model to an **MCell4 Python** script (`import mcell`).

And one import path enters it: **`bng/`** brings **BNGL/SBML** models in (`bngl_to_data_model.py`,
`sbml2*`).

---

## 5. Integration map — who depends on what

This is the cross-cutting view; each arrow is detailed in the linked doc.

### 5.1 Every domain ⇄ the root `MCellPropertyGroup` (doc 01)
All chemistry/geometry/run/viz PropertyGroups are `PointerProperty` children of
`MCellPropertyGroup` on `scene.mcell`; the single host panel calls each child's `draw_layout`.
There is no per-domain panel registration — the selector dispatches.

### 5.2 Every numeric field ⇄ the parameter system (doc 04)
Rates, diffusion constants, counts, coordinates, timing, partition bounds — virtually every numeric
input is **parameter-backed**: the domain PropertyGroup embeds a one-field `Parameter_Reference`
(`parameter_system.py`) instead of a raw float, and the value is an **expression string**.
- **General parameters** (`g#`) are user-named variables with expressions (the Model Parameters
  list). **Panel parameters** (`p#`) are the in-UI fields that can hold an expression.
- Per-parameter data lives in **ID-property dicts** (not RNA) for performance; expressions are
  parsed via `ast` into a pickled token list and evaluated with bare `eval()` over a
  topologically sorted dependency graph (Kahn sort, with cycle detection).
- **Gotcha:** the `eval` is **not sandboxed** (a security boundary on untrusted data models), and
  every edit triggers a full recompute. `ParameterSpace.py` is **dead legacy code** (won't import
  under Py3.13).

### 5.3 Chemistry domains ⇄ each other by *name string* (doc 02)
Molecules are the root authority. Reactions, release sites, and surface classes reference species
**by name string**, not by pointer — so renames don't cascade automatically. All six chemistry
modules share the PropertyGroup-pair + `MCELL_OT_*` Operators + `MCELL_UL_*` UIList + data-model
methods pattern. Glyphs (`cellblender_glyphs.py`) supply procedural display shapes attached per
molecule.

### 5.4 Geometry ⇄ Blender meshes (doc 03)
"Model objects" are Blender `MESH` objects flagged `object.mcell.include`; a derived
`model_objects.object_list` mirrors that flag, kept in sync by `load_post`/`save_pre` handlers.
**Surface regions are named *face sets*** stored as a run-length-encoded, 32767-chunked ID-property
dict on the *mesh* (keyed by numeric region id) — **not** as Blender vertex groups. Regions
cross-reference surface classes (5.3) and drive releases-on-region. Partitions bound the world
(per-axis for MCell3, single cube for MCell4); the meshalyzer validates manifold/orientable/
watertight topology and computes area/volume/genus via NumPy/SciPy.

### 5.5 Run pipeline: data model → engine → runner → output (doc 06)
`MCELL_OT_run_simulation` (`cellblender_simulation.py`) dispatches on a `simulation_run_control`
enum. The default "MCell Local" path walks the **parameter-sweep × seed** grid and, per point,
exports either MDL (MCell3) or an MCell4 Python script (the `mcell4_mode` preference), or takes the
MCell3-R/BNG branch. Jobs go on a global `SimQueue` (`sim_runner_queue.py`) that spawns one
`run_wrapper.py` shim per job (stable PID, signal forwarding, live stdout). A parallel **pluggable**
system (`sim_engine_manager/` + `sim_runner_manager/`, duck-typed modules selected into globals)
backs the experimental dynamic path.

### 5.6 Results ⇄ Blender (doc 07)
Two independent halves:
- **Spatial molecule viz** (`cellblender_mol_viz.py`): reads per-frame `viz_data/seed_xxxxx/*.dat`
  files (binary v1/v2 + ASCII), builds per-species glyph + position-mesh objects with a
  Geometry-Nodes instancing modifier, and a `@persistent` `frame_change_pre` handler rebuilds them
  to match `scene.frame_current` (undo disabled for speed; no cross-frame caching → slow on large
  datasets).
- **Reaction count output** (`cellblender_reaction_output.py`): defines counts over
  World/Object/Region, globs per-seed time-series `.dat` files, and dispatches to an **external**
  plotter subprocess in `data_plotters/` (matplotlib/gnuplot/xmgrace/java).

---

## 6. Subsystem cheat-sheet (file → doc)

| Area | Primary files | Doc |
|---|---|---|
| Add-on entry / registration / main panel | `__init__.py`, `cellblender_main.py`, `cellblender_initialization.py` | 01 |
| Preferences / utils / project / scripting / examples / build-id | `cellblender_preferences.py`, `cellblender_utils.py`, `cellblender_project.py`, `cellblender_scripting.py`, `cellblender_examples.py`, `cellblender_id.py`, `cellblender_source_info.py`, `cellblender_legacy.py` | 01 |
| Molecules / reactions / release / surface classes / molmaker / glyphs | `cellblender_molecules.py`, `cellblender_reactions.py`, `cellblender_release.py`, `cellblender_surface_classes.py`, `cellblender_molmaker.py`, `cellblender_glyphs.py` | 02 |
| Model objects / surface regions / partitions / meshalyzer / PBC | `cellblender_objects.py`, `cellblender_surface_regions.py`, `object_surface_regions.py`, `cellblender_partitions.py`, `cellblender_meshalyzer.py`, `cellblender_pbc.py` | 03 |
| Parameter system / sweeps | `parameter_system.py`, `ParameterSpace.py` | 04 |
| Data model / MDL I/O / plotters | `data_model.py`, `io_mesh_mcell_mdl/`, `mdl/`, `data_plotters/` | 05 |
| Run / engines / runners / BNG | `cellblender_simulation.py`, `sim_engine_manager/`, `sim_runner_manager/`, `run_simulations.py`, `run_wrapper.py`, `sim_runner_queue.py`, `old_sim_engines/`, `mcell4/`, `bng/` | 06 |
| Molecule viz / reaction output | `cellblender_mol_viz.py`, `cellblender_reaction_output.py` | 07 |

*(Not covered in depth — minor/auxiliary: `developer_utilities/`, `test_suite/`, `examples/`
[mostly bundled data], `icons/`, `extensions/`, `git_hooks/`, `META-INF/`.)*

---

## 7. Cross-cutting gotchas (consolidated)

- **The data model — not the PropertyGroups — is the source of truth for save/load/export.** Add a
  field by wiring all five data-model methods *and* bumping the version + an `upgrade_data_model`
  step, or old files break. (doc 05)
- **Refresh `cellblender_id.py` before any pushed commit** (`python3 update_cellblender_id.py`).
  The SHA mismatch is what triggers upgrades; a stale ID means installed CellBlenders won't
  recognize the new version. (doc 01/05, and `cellblender/CLAUDE.md`)
- **Cross-references are by name string, not pointer** (species in reactions/releases/surf-classes;
  surface classes on regions). Renames don't cascade. (doc 02/03)
- **Parameter `eval()` is unsandboxed** and recomputes the whole dependency graph on every edit —
  a security and performance consideration when loading untrusted data models. (doc 04)
- **Surface regions live on the mesh as chunked ID-properties**, not vertex groups; geometry code
  branches heavily on **MCell3 vs MCell4** mode. (doc 03)
- **`ParameterSpace.py` and parts of `__init__.py`/`cellblender_preferences.py` are dead code** —
  don't mistake them for live paths. (doc 01/04)
- **Two parallel MDL exporters exist** (`io_mesh_mcell_mdl/export_mcell_mdl.py` legacy vs
  `mdl/data_model_to_mdl.py` current), plus engine-specific copies under `sim_engine_manager/`.
  (doc 05/06)
- **Job tracking keys on the *wrapper* PID**, not the engine PID; the pluggable engine/runner
  system is largely experimental relative to the default "MCell Local" path. (doc 06)
- **Molecule viz rebuilds every frame with no caching** — large datasets are slow; `frame_change`
  handlers couple it to Blender's timeline. (doc 07)

---

*Generated by a multi-agent mapping pass (one agent per domain doc), consolidated here. Each linked
document carries `file_path:line` references to the real source; this overview is the index and the
integration map that ties them together. Paths are written relative to `$ROOT` (the parent of this
wiki folder; see `CLAUDE.md`). See `MAINTENANCE.md` to keep it in sync.*
