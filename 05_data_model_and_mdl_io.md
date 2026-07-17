# 05 — The Data Model & MDL / File I/O

> Audience: developers who need to understand CellBlender's central interchange
> format (the "data model"), how every domain serializes to/from it, how saved
> models are version-stamped and upgraded, and how the data model is turned into
> MCell MDL text or imported from MDL geometry. This is the architectural hub doc:
> nearly every other CellBlender subsystem is described in terms of "the data model".

---

## 1. What the data model *is*

The **CellBlender Data Model** is a pure, nested Python **dict / list / scalar**
structure — no Blender types, no `PropertyGroup` references, nothing that requires
`bpy` to read. It is designed to be a *stable, version-independent* representation
of a whole CellBlender project that survives across CellBlender releases
(`cellblender/data_model.py:20-24`).

Because it is just dicts/lists/strings/numbers, it is trivially serializable two
ways (`cellblender/data_model.py:244-254`):

| Form | Encode | Decode |
|------|--------|--------|
| Python pickle (text, protocol 0, latin-1) | `pickle_data_model()` | `unpickle_data_model()` |
| JSON | `json_from_data_model()` | `data_model_from_json()` |

The root of a saved model is always wrapped as `{ 'mcell': <dm> }`
(`cellblender/data_model.py:257-269`).

The module also ships pure-structure **introspection helpers** that recurse the
dict/list tree without any Blender knowledge: `dump_data_model()` (console dump,
`:105`), `list_data_model()` (`:130`), `text_data_model()` (pretty indented text,
`:158`), `get_data_model_keys()` (schema key-set, `:216`), and `data_model_as_text()`
(`:236`). There is even a standalone **Tk tree browser** (`CellBlenderDataModelBrowser`,
`:285-462`) that walks the same structure, plus operators `cb.print_data_model`,
`cb.print_dm_keys`, `cb.regenerate_data_model`, `cb.tk_browse_data_model`
(`:472-533`). All of these work purely on the nested-dict shape — proof the format
is decoupled from Blender.

### Why it is the hub

```
                   ┌─────────────────────────────┐
 Blender RNA       │      THE DATA MODEL          │      external world
 PropertyGroups    │  nested dict/list (no bpy)   │
 (cellblender_*.py)│                              │
        │  build_data_model_from_properties      │
        ├───────────────────────────────────────▶│──▶ .blend  (mcell['data_model'], pickled)
        │                                         │──▶ .txt    (pickle) / .json  export
        │◀───────────────────────────────────────┤
        │  build_properties_from_data_model      │──▶ MDL text  (mdl/data_model_to_mdl.py → MCell3)
        │                                         │──▶ other sim engines (sim_engine_manager/*)
        └─────────────────────────────────────────┘
```

Every domain (molecules, reactions, releases, geometry, viz, …) knows how to
**emit** itself to a data-model fragment and **rebuild** itself from one. The data
model is the single point through which a project is saved, loaded, exported,
upgraded, and handed to a simulation engine. Other wiki docs refer to "the data
model" constantly — this is that object.

---

## 2. The round-trip convention every domain implements

CellBlender uses a strict, duck-typed contract. **Each domain `PropertyGroup`
implements three methods** with identical signatures across the codebase:

| Method | Direction | Purpose |
|--------|-----------|---------|
| `build_data_model_from_properties(context, ...)` | properties → dict | serialize this domain to a data-model fragment |
| `build_properties_from_data_model(context, dm, ...)` | dict → properties | rebuild this domain's RNA props from a fragment |
| `@staticmethod upgrade_data_model(dm)` | dict → dict | migrate an old fragment to this domain's current version |

This pattern is documented in the `MCellPropertyGroup` header comment
(`cellblender/cellblender_main.py:27-31`) and implemented by **17 modules**
(grep `def build_data_model_from_properties`): `parameter_system.py`,
`cellblender_initialization.py`, `cellblender_partitions.py`,
`cellblender_molecules.py`, `cellblender_reactions.py`, `cellblender_release.py`,
`cellblender_surface_classes.py`, `cellblender_surface_regions.py`,
`cellblender_pbc.py`, `cellblender_objects.py`, `cellblender_mol_viz.py`,
`cellblender_simulation.py`, `cellblender_reaction_output.py`,
`cellblender_scripting.py`, `cellblender_legacy.py`, `cellblender_molmaker.py`,
and the top-level `cellblender_main.py`.

### `cellblender_main.py` orchestrates the whole model

`MCellPropertyGroup.build_data_model_from_properties()`
(`cellblender/cellblender_main.py:998-1038`) builds the top-level dict: it stamps
`data_model_version`, records `model_language` (`mcell3`/`mcell3r`/`mcell4`,
`:1003-1008`), `blender_version`, `cellblender_version`, `cellblender_source_sha1`,
then calls each domain's builder into a named key:

```
dm['parameter_system']    = self.parameter_system.build_data_model_from_properties(...)
dm['initialization']      = self.initialization.build_data_model_from_properties(...)
dm['define_molecules']    = self.molecules.build_data_model_from_properties(...)
dm['define_reactions']    = self.reactions.build_data_model_from_properties(...)
dm['release_sites']       = self.release_sites...
dm['model_objects']       = self.model_objects...
dm['reaction_data_output']= self.rxn_output...
...                                                      (cellblender_main.py:1018-1033)
```

Geometry (mesh vertices/faces/regions) and materials are added **only when
`geometry=True`** (`:1034-1037`) — most ordinary saves carry the *settings* but not
the heavy mesh data, which lives in the .blend itself.

`build_properties_from_data_model()` (`:1165` onward) is the inverse: it checks the
version, wipes existing props (`remove_properties` → `init_properties`), then
dispatches each `dm[...]` fragment back into the matching domain's
`build_properties_from_data_model`.

---

## 3. The version-upgrade chain (the heart of the system)

Saved models carry **date-coded version stamps** of the form
`DM_YYYY_MM_DD_HHMM` (e.g. `DM_2017_06_23_1300`). Grep across the codebase finds
**40+ distinct version constants** (`DM_2014_10_24_1638` … `DM_2020_07_12_1600`),
each marking a schema change in some domain.

### How a stamp is set

`build_data_model_from_properties` hard-codes the *current* version it produces.
At the top level that is `dm['data_model_version'] = "DM_2017_06_23_1300"`
(`cellblender/cellblender_main.py:1002`). Each domain hard-codes **its own**
current version independently — e.g. molecules emit `"DM_2018_10_16_1632"`
(`cellblender/cellblender_molecules.py:1216`). So a single saved model is a tree of
fragments, **each with its own version stamp**.

### How upgrade dispatch works

`MCellPropertyGroup.upgrade_data_model(dm)` is the **top-level orchestrator**
(`cellblender/cellblender_main.py:1042-1161`):

1. Migrate the **top-level** stamp forward through a chain of `if` clauses:
   missing → `DM_2014_10_24_1638` → `DM_2017_06_23_1300` (`:1052-1057`).
2. If the stamp still isn't the current one, call
   `data_model.flag_incompatible_data_model(...)` and **return `None`** (`:1059-1061`).
3. Then, for each domain key present, delegate to that domain's
   `upgrade_data_model` static method and replace the fragment with the result;
   a `None` return aborts the whole upgrade (`:1063-1159`).

Each domain repeats the same **stepwise `if`-cascade** pattern internally. The
molecule upgrader (`cellblender/cellblender_molecules.py:1259-1369`) is the
canonical example — it walks a chain of ~10 versions, applying one incremental
mutation per step:

```
if dm['data_model_version'] == "DM_2014_10_24_1638":
    dm['mol_bngl_label'] = ""                       # add field
    dm['data_model_version'] = "DM_2015_07_24_1330"
if dm['data_model_version'] == "DM_2015_07_24_1330":
    dm['display'] = disp_dict                       # add display block
    dm['data_model_version'] = "DM_2016_01_13_1930"
... (each step adds/renames keys, bumps the stamp) ...
if dm['data_model_version'] != "DM_2018_10_16_1632":  # final guard
    data_model.flag_incompatible_data_model(...); return None
```

Because the clauses are **non-`elif` and fall through in date order**, a model from
*any* prior version is carried step-by-step up to the current schema. This is the
mechanism that lets a brand-new CellBlender open a years-old .blend.

> **Gotcha — `model_language` rewrite on upgrade.** `upgrade_data_model` forces
> `dm['model_language'] = 'mcell4'` for *any* upgraded model
> (`cellblender_main.py:1048-1049`), and `build_properties_from_data_model` defaults
> an absent `model_language` to mcell4 + bionetgen mode
> (`cellblender_main.py:1192-1195`). Upgrading an old model can therefore silently
> switch its target engine.

### When upgrades fire (version detection via source SHA-1)

CellBlender does **not** compare data-model versions to decide whether a file is
stale; it compares a **SHA-1 of the CellBlender source** stored in the .blend
(`mcell['saved_by_source_id']`) against the running add-on's id
(`cellblender_info['cellblender_source_sha1']`). The Blender `@persistent`
handlers in `data_model.py` drive this:

- **`load_post(context)`** (`cellblender/data_model.py:868-913`) reads the saved
  source id, compares to the current one, and sets
  `cellblender_info['versions_match']`. It does **not** auto-upgrade — it only flags
  so the UI can offer an "Upgrade" button.
- **`save_pre(context)`** (`cellblender/data_model.py:819-850`) rebuilds the data
  model from current properties and stores it as `mcell['data_model']` (pickled). If
  versions don't match it forces an upgrade first (RC3/RC4 path vs. normal path,
  `:842-846`).
- The actual property rebuild lives in **`upgrade_properties_from_data_model()`**
  (`cellblender/data_model.py:689-755`): it unpickles `mcell['data_model']`, deletes
  and reinstates the `Scene.mcell` RNA, runs
  `MCellPropertyGroup.upgrade_data_model(dm)`, then
  `build_properties_from_data_model`. `upgrade_RC3_properties_from_data_model()`
  (`:758-814`) handles ancient RC3/RC4 files that predate stored source ids.

> **Gotcha — refresh the source id.** Per `cellblender/CLAUDE.md`, you must run
> `python3 update_cellblender_id.py` and commit `cellblender_id.py` whenever source
> changes; otherwise installed CellBlenders won't notice the version differs and
> won't offer the upgrade. The id is read from `cellblender_id.py` via
> `cellblender_source_info.identify_source_version_from_file()`
> (`cellblender/data_model.py:888`).

### Relationship to .blend storage

The data model is **stored inside the .blend** as a custom property string
`bpy.context.scene.mcell['data_model']` (pickled), written in `save_pre`. The live
RNA `PropertyGroup` tree is the *editable* representation; the embedded pickled data
model is the *durable, upgradeable* representation. On version mismatch the embedded
data model is the source of truth that gets upgraded and re-expanded into properties.

---

## 4. External file export / import (JSON & pickle)

`data_model.py` registers Blender operators (all subclass `ExportHelper`,
`cellblender/data_model.py:536-650`):

| Operator (`bl_idname`) | What |
|------|------|
| `cb.export_data_model` / `cb.import_data_model` | pickle `.txt`, **no** geometry |
| `cb.export_data_model_all` / `cb.import_data_model_all` | pickle `.txt`, **with** geometry + scripts |
| `cb.export_data_model_all_json` / `cb.import_data_model_all_json` | JSON `.json`, with geometry + scripts |

Import always runs the saved fragment through
`MCellPropertyGroup.upgrade_data_model(dm['mcell'])` **before** calling
`build_properties_from_data_model` (`cellblender/data_model.py:605-607`,
`:628-630`, `:664-666`) — so importing an old exported model upgrades it too. JSON
import is factored into the standalone `import_datamodel_all_json()`
(`:658-666`). Save helpers: `save_data_model_to_file` (pickle, `:264`) and
`save_data_model_to_json_file` (JSON, `:257`).

> **Gotcha — pickle is text, not binary.** `pickle_data_model` uses protocol 0 and
> decodes to a latin-1 *string* (`:244-248`), so the "pickle" export is a human-ish
> text file, and JSON vs. pickle is auto-detected on read by sniffing for `"mcell"`
> in the first 20 bytes (see `read_data_model`, `mdl/data_model_to_mdl.py:52-84`).

---

## 5. MDL — the Model Description Language text format

**MDL** is MCell's native plain-text input language. CellBlender both *imports*
MDL geometry (mesh → Blender objects) and *generates* full MDL from the data model
to feed **MCell3**. Two separate code paths exist.

### 5a. `io_mesh_mcell_mdl/` — mesh-level MDL import/export

This package is a Blender Import/Export add-on for **geometry only** (objects,
vertices, faces, surface regions) — it does not handle molecules/reactions.

- **`__init__.py`** — registers two operators: `ImportMCellMDL`
  (`import_mdl_mesh.mdl`) and `ExportMCellMDL` (`export_mdl_mesh.mdl`)
  (`cellblender/io_mesh_mcell_mdl/__init__.py:50-121`). Import tries the **fast SWIG
  C parser first and falls back to the pure-Python parser on `ImportError`**
  (`:76-91`).
- **`mdlmesh_parser.py`** — a thin **SWIG-generated** wrapper (`mdl_parser(filename)`)
  around the compiled C extension `_mdlmesh_parser`
  (`cellblender/io_mesh_mcell_mdl/mdlmesh_parser.py:62-63`). Built via `setup.py`
  (SWIG). This is the fast path. **Gotcha: it only exists if `make` built the C
  extension**; otherwise the fallback is used.
- **`mdlobj.py`** — the plain Python node class (`mdlObject`/`objRegion`) the SWIG
  parser returns: a linked tree with `next`/`first_child`, `object_type`
  (META vs POLY), `vertices`, `faces`, `regions`
  (`cellblender/io_mesh_mcell_mdl/mdlobj.py:1-40`).
- **`import_mcell_mdl.py`** — drives the SWIG parser, walks the returned `mdlObject`
  tree, and hands POLY objects to `import_shared.import_obj`
  (`cellblender/io_mesh_mcell_mdl/import_mcell_mdl.py:25-46`).
- **`import_mcell_mdl_pyparsing.py`** — the **pure-Python fallback parser**: a
  `pyparsing` BNF grammar for `POLYGON_LIST` / `VERTEX_LIST` /
  `ELEMENT_CONNECTIONS` / `DEFINE_SURFACE_REGIONS` with parse-action callbacks that
  fill `mdlObject`s
  (`cellblender/io_mesh_mcell_mdl/import_mcell_mdl_pyparsing.py:84-171`). Slower but
  needs no compilation.
- **`import_shared.py`** — the back-end used by *both* importers:
  `import_obj(mdlobj, ...)` creates a Blender mesh via `mesh.from_pydata`, applies a
  gray `obj_mat` and red `reg_mat`, recreates each surface region through
  `obj.mcell.regions.add_region_by_name`, and (optionally) registers the object in
  the Model Objects list
  (`cellblender/io_mesh_mcell_mdl/import_shared.py:30-109`).
- **`export_mcell_mdl.py`** (1245 lines) — the **legacy properties→MDL exporter**
  for MCell3. Unlike the data-model path below, it reads Blender properties directly
  and can write either one unified `Scene.main.mdl` or **modular** include files
  (`Scene.molecules.mdl`, `Scene.reactions.mdl`, …) per
  `export_project.export_format` (`cellblender/io_mesh_mcell_mdl/export_mcell_mdl.py:90-118`).
  It also implements the invalid-entry "filter / dont_run / ignore" policy
  (`:56-87`). Invoked from `cellblender_project.py:237` and imported in
  `cellblender_main.py:88`.
- **`pyparsing.py`** (3668 lines) — a **vendored copy** of Paul McGuire's pyparsing
  library (`# Copyright (c) 2003-2013  Paul T. McGuire`,
  `cellblender/io_mesh_mcell_mdl/pyparsing.py:3`). Bundled so the fallback parser
  works without an external dependency. Do not edit; it is third-party.

```
         MDL text file
              │
     ┌────────┴─────────┐
     │ SWIG C parser    │  (fast, needs compiled _mdlmesh_parser)
     │ mdlmesh_parser   │
     └────────┬─────────┘   ── ImportError ──▶ pyparsing fallback
              │                                 (import_mcell_mdl_pyparsing)
        mdlObject tree (mdlobj.py)
              │
     import_shared.import_obj()  →  Blender mesh objects + surface regions
```

### 5b. `mdl/data_model_to_mdl.py` — data-model→MDL (the MCell3 run path)

This is the **standalone program** that turns a *full* data model (not just
geometry) into complete MCell3 MDL. Its docstring notes it can assume it always
receives a current data model because CellBlender upgrades first
(`cellblender/mdl/data_model_to_mdl.py:19-27`). It is deliberately importable
**outside Blender** (no hard `bpy` dependency) so it can run in a subprocess.

- A module-level **`has_blender`** flag (`:242-247`) is set by attempting
  `import bpy`; it gates the in-Blender-only code paths — chiefly the **dynamic
  geometry** export, which reaches into the live `context.scene.mcell`
  (`:1369`, `:1377`, `:1395`, `:1428`, …). Non-Blender runs must keep it `False`.

- Entry point **`write_mdl(dm, file_name, scene_name='Scene', ...)`**
  (`cellblender/mdl/data_model_to_mdl.py:997`). It branches on
  `requires_mcellr(dm)` (`:966`): BioNetGen/MCell3-R models are routed to
  `write_mdlr()` (`:576`, which shells out to a generator); plain MCell3 models are
  written section-by-section via `write_parameter_system`, `write_initialization`,
  `write_molecules`, `write_reactions`, `write_release_sites`,
  `write_surface_classes`, `write_modify_surf_regions`, `write_release_patterns`,
  `write_viz_out`, `write_react_out`, `write_static_geometry`, etc.
  (function table around `:1580-2393`).
- It also handles **modular vs. all-in-one** output (`INCLUDE_FILE` lines,
  `:1019-1082`), dynamic geometry, and inserted user scripting
  (`write_export_scripting`, `:320`).
- It has a `__main__` CLI: `python data_model_to_mdl.py <data_model_file> <mdl_base>`
  reading pickle or JSON via `read_data_model` (`:2414-2447`). Running as
  `__main__` **forces `has_blender = False`** (`:256-257`) — see the gotcha below.
- Called in-process from `cellblender_simulation.py:899`
  (`data_model_to_mdl.write_mdl(...)`) and for engine selection via
  `requires_mcellr` (`:860`).

> **Gotcha — a bare `import bpy` no longer proves we're inside CellBlender.** The
> `bpy` PyPI wheel imports successfully in a plain headless Python, so the
> `has_blender` probe (`:242-247`) can be `True` while **no CellBlender add-on is
> registered and `context.scene.mcell` does not exist**. The standalone CLI (test
> harness / `run_data_model_mcell.py`) then took the in-Blender dynamic-geometry
> branch and crashed with `AttributeError: 'Scene' object has no attribute 'mcell'`
> — this broke the 3 dynamic-geometry data-model tests (`0110`/`0120`/`0130`). Fix:
> when the module runs as `__main__`, force `has_blender = False` (`:256-257`),
> restoring the pre-`bpy`-install standalone behavior. A `__main__` gate is used
> rather than a `hasattr(scene, 'mcell')` check because the module is imported at
> add-on **registration** time, which would make such a check racy against
> property-registration order. CellBlender **imports** this module (never executes
> it as `__main__`), so its in-Blender path is unaffected. (commit `20192d1`,
> branch `mcell4_dev`; verified on both the nanobind and pybind11 builds.)

### 5c. `mdl/run_data_model_mcell.py`

A standalone launcher (`#!/usr/bin/env python`,
`cellblender/mdl/run_data_model_mcell.py:1-11`) that `import data_model_to_mdl`,
generates the MDL, then **spawns the `mcell` binary** per seed, optionally in a
`multiprocessing` pool for parameter sweeps (`run_sim`, `:16-73`;
`build_sweep_list`, `:80`). It is launched as a subprocess by the simulation
subsystem (`cellblender_simulation.py:581`, `:1106`). Note the in-file comment that
`build_sweep_list` is **deliberately duplicated** because import attempts failed
(`:76-79`) — a known wart.

> **Gotcha — two MDL exporters, two engines.** `io_mesh_mcell_mdl/export_mcell_mdl.py`
> (properties→MDL) and `mdl/data_model_to_mdl.py` (data-model→MDL) are *parallel*
> exporters. The data-model path is the modern one used to run MCell3/MCell3-R; the
> properties path is older and still used for direct geometry/MDL menu export.
> There are also engine-specific copies under `sim_engine_manager/mcell3*/`
> (`data_model_to_mdl_3.py`, `data_model_to_mdl_3r.py`, tracked in
> `cellblender_source_info.py:183-218`) — when changing MDL generation, check which
> copy a given engine actually uses.

---

## 6. `data_plotters/` — pluggable reaction-output plotting

Briefly (reaction output proper is covered in doc 07): `data_plotters/` is a
**plugin directory**. `find_plotting_options()` scans its own folder for
subpackages, imports each, and keeps those whose `requirements_met()` returns True
(`cellblender/data_plotters/__init__.py:43-75`). Shipped backends are subfolders,
each a self-contained package exposing `get_name()` / `requirements_met()`:
`mpl_plot`, `mpl_simple` (matplotlib), `gnuplot`, `xmgrace`, `java_plot`. They plot
the column data MCell writes from `REACTION_DATA_OUTPUT` blocks (which
`data_model_to_mdl.write_react_out`, `:2315`, generates).

`find_plotting_options()` imports each backend with a *relative*
`importlib.import_module(f'.{f}', package=__package__)`
(`cellblender/data_plotters/__init__.py:67`) and must **not** modify `sys.path` — Blender
forbids add-ons from doing so (see doc 06 §6 for the full rule; a redundant
`sys.path.append` was removed here in commit `90fe1f3`).

---

## 7. Quick reference — key files

| File | Role |
|------|------|
| `cellblender/data_model.py` | Core: serialization, save/load operators, `@persistent` save_pre/load_post handlers, upgrade drivers, Tk browser |
| `cellblender/cellblender_main.py:998-1161` | Top-level `build_*`/`upgrade_data_model` orchestration over all domains |
| `cellblender/cellblender_molecules.py:1259-1369` | Canonical per-domain stepwise upgrade cascade |
| `cellblender/io_mesh_mcell_mdl/` | Mesh-level MDL import (SWIG + pyparsing fallback) and legacy properties→MDL export |
| `cellblender/io_mesh_mcell_mdl/pyparsing.py` | Vendored third-party pyparsing (do not edit) |
| `cellblender/mdl/data_model_to_mdl.py` | data-model→full MDL generator (MCell3 / MCell3-R run path) |
| `cellblender/mdl/run_data_model_mcell.py` | Standalone subprocess launcher: generate MDL + run `mcell` (with sweeps) |
| `cellblender/data_plotters/` | Pluggable reaction-output plotting backends |

---

*Part of the CellBlender codebase wiki — see 00_overview.md.*
