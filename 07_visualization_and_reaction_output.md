# 07 — Visualization & reaction-data output

> How MCell simulation **results** flow back into Blender. Two independent halves:
> (1) **spatial molecule visualization** — per-frame molecule coordinates drawn as
> point-cloud objects in the 3D viewport, driven by Blender's timeline; and
> (2) **reaction count output** — defining time-series observables and plotting the
> resulting `.dat` files through external plotter plugins. Audience: developers
> extending result viewing/plotting or debugging viz performance.

---

## 1. Big picture

```
                          ┌─────────────────────────────────────────────┐
   MCell run output       │            CellBlender (Blender)             │
   ───────────────        │                                             │
  viz_data/seed_xxxxx/    │  cellblender_mol_viz.py                      │
    proj.cellbin.NNNN.dat ├─►  read_viz_data → per-frame file list       │
   (binary or ASCII       │   frame_change_pre handler ──┐               │
    molecule positions)   │     → mol_viz_update          │ 3D VIEWPORT  │
                          │       → mol_viz_file_read ─────┘ point clouds │
                          │                                             │
  react_data/seed_xxxxx/  │  cellblender_reaction_output.py              │
    Mol.World.dat  ...    ├─►  rxn_output_list (PropertyGroups)          │
   (time<TAB>count rows)  │   plot_rxn_output_with_selected → glob .dat  │
                          │     → plot_module.plot() ──────► data_plotters/
                          └─────────────────────────────────────────────┘
                                                          (subprocess: mpl, gnuplot,
                                                           xmgrace, java, simple)
```

The two halves share **nothing** at runtime except the `data_layout.json` sweep
descriptor (see §4) and the `mcell_files_path()` helper. Molecule viz is bound to
Blender's animation system; reaction output is a one-shot "Plot" button that shells
out to a plotter plugin.

Both PropertyGroups hang off the per-scene `mcell` root:
`mcell.mol_viz` (`MCellMolVizPropertyGroup`), `mcell.viz_output`
(`MCellVizOutputPropertyGroup`), and `mcell.rxn_output`
(`MCellReactionOutputPropertyGroup`) — wired at
`cellblender/cellblender_main.py:923`, `:938`, `:939`.

---

## 2. Molecule visualization — `cellblender/cellblender_mol_viz.py`

### 2.1 Property groups

| Group | Role | Cite |
|-------|------|------|
| `MCellMolVizPropertyGroup` | The "Visualize Simulation Results" panel state: viz directory, seed list, current frame index, color list, custom-script selection. | `cellblender/cellblender_mol_viz.py:1456` |
| `MCellVizOutputPropertyGroup` | The **export** side: which molecules / iteration range MCell should *write* as viz output (start/end/step, export_all). | `cellblender/cellblender_mol_viz.py:1835` |

Note the naming gotcha: `MCellVizOutputPropertyGroup` (export config, lives in the
*same file*) is about telling MCell what to emit; `MCellMolVizPropertyGroup` is about
*reading it back*. Only the latter participates in result visualization.

Key per-frame state on `MCellMolVizPropertyGroup`:
`mol_file_dir`, `mol_file_index` (current frame), `mol_file_num`,
`mol_file_start/stop/step_index`, `mol_viz_enable` (toggle to speed up playback),
`color_list` / `color_index`, `viz_code` (standard/custom/both) —
`cellblender/cellblender_mol_viz.py:1463-1514`.

A module-level `global_mol_file_list` (not a Blender property) holds the sorted list
of per-frame `.dat` filenames for the active seed —
`cellblender/cellblender_mol_viz.py:59`. It was deliberately moved out of the data
model because storing a huge file list in the `.blend` was slow (the panel
`template_list` over `mol_file_list` is commented out at
`cellblender/cellblender_mol_viz.py:1811-1815` for the same "UI slowdown" reason).

### 2.2 Reading the viz data — operators

- **`MCELL_OT_read_viz_data`** (`mcell.read_viz_data`) — the main loader,
  `cellblender/cellblender_mol_viz.py:155`. It resolves the viz directory two ways:
  - **Sweep layout** (`output_data/` present): parses `data_layout.json`, walks the
    `data_layout` levels (`/DIR`, `/FILE_TYPE` forced to `viz_data`, `/SEED`, plus
    parameter-sweep subdirs `name_index_N`) — `:189-215`.
  - **Legacy layout**: `<files>/viz_data/seed_xxxxx/` — `:217-221`.
  It then globs `*.dat`, sorts, fills `global_mol_file_list`, calls
  `create_color_list()`, `set_viz_boundaries()`, then `mol_viz_update()` —
  `:256-294`.
- **`MCELL_OT_select_viz_data`** (`mcell.select_viz_data`) — manual file-browser
  picker for an arbitrary viz directory (`manual_select_viz_dir` mode),
  `cellblender/cellblender_mol_viz.py:335`.
- **`MCELL_OT_mol_viz_set_index`** (`mcell.mol_viz_set_index`) — clamps
  `mol_file_index` to start/stop and calls `mol_viz_update`,
  `cellblender/cellblender_mol_viz.py:391`. **This is the operator the frame handler
  calls** (see §2.4).
- **`MCELL_OT_update_data_layout`** (`mcell.update_data_layout`) — refreshes the
  sweep `choices_list` enum from `data_layout.json`, `:142`.

`set_viz_boundaries()` ties the dataset length to the timeline: it sets
`scene.frame_start = 0` and `scene.frame_end = len(global_mol_file_list)-1`, so one
Blender frame == one viz `.dat` file — `cellblender/cellblender_mol_viz.py:304-318`.

### 2.3 File formats read — `mol_viz_file_read()`

`mol_viz_file_read(mcell, filepath)` (`cellblender/cellblender_mol_viz.py:950`) reads
ONE frame file. First byte/int is a magic version tag (read as a 4-byte `array("I")`):

| `b[0]` | Format | Notes |
|--------|--------|-------|
| `1` | Binary v1 | name-length is **1 byte**; per-mol count field is `3 × num_molecules` (float count). `cellblender/cellblender_mol_viz.py:1010-1011,1031` |
| `2` | Binary v2 | name-length is a **4-byte int**; includes a `mol_ids` array (read then ignored); count field is `num_molecules`. `:1013, :1025-1029` |
| else | ASCII | text lines `name <orient?> x y z [ox oy oz]`; surface mols have nonzero orientation. `:1076-1110` |

Per-molecule binary record: name length, name bytes, 1-byte **molecule type** `mt`
(`1` = surface molecule → orientations follow positions), position floats, and (for
surface mols) orientation floats — `:1003-1038`. EOF terminates the read loop.

**MCell4 vs MCell3 complex handling**: in MCell4 mode
(`cellblender_preferences.mcell4_mode`), a complex species name like
`@EC:scov2(...).spike(...)@CP` is split into elementary molecule names via
`get_used_molecule_names()` / `remove_compartment_and_state()` so each component gets
its own glyph (`cellblender/cellblender_mol_viz.py:814-838`, used at `:1040-1046`).
MCell3 binary viz already pre-splits complexes, so it passes the name through.

`mol_viz_file_dump()` (`:735`) is a debug-only binary dumper (v1 format) that prints
molecule counts; not used in normal drawing.

### 2.4 How molecules are drawn (Blender objects)

For each molecule species in a frame, `mol_viz_file_read` builds three linked Blender
data-blocks (`cellblender/cellblender_mol_viz.py:1125-1291`):

1. **`mol_<name>_shape`** — the **glyph**: a tiny ico-sphere primitive
   (`primitive_ico_sphere_add`, radius 0.005) created once and reused, parented under
   the position object — `:1163-1179`. A `mol_<name>_mat` material carries the display
   color from `color_list[color_index]` (default red) — `:1191-1206`.
2. **`mol_<name>_pos`** — a **mesh** whose *vertices* are the molecule positions
   (`vertices.add` + `foreach_set("co", mol_pos)`), `:1216-1231`. Volume molecules get
   random orientations (`:1234-1236`); orientations are stored as a custom
   `FLOAT_VECTOR` point attribute named `mol_orient` — `:1240-1243`.
3. **`mol_<name>`** — the **object** holding the position mesh, with a **Geometry
   Nodes** modifier whose node tree `mol_<name>_orient_node` instances the glyph onto
   each point and aligns it to the `mol_orient` attribute —
   `:1259-1275`, tree built by `update_geo_node_tree()` (`:876-925`,
   `GeometryNodeInstanceOnPoints` + `FunctionNodeAlignRotationToVector`). All
   `mol_*` objects are parented to a hidden empty named **`molecules`** —
   `:1112-1123, :1291`.

> **Gotcha — Geometry Nodes is the modern path.** Older Blender (≤2.93) used
> vertex-instancing (`instance_type='VERTS'`, `use_instance_vertices_rotation`); that
> code survives as commented-out blocks (`:1279-1289`) and inside the dead
> `old_mol_viz_file_read` (`:553-728`). Current code (Blender ≥3.3) uses the
> per-species Geometry-Nodes tree instead. The orientation grid helper
> `set_mol_orientation()` (`:842`) is also legacy/unused.

`mol_viz_clear()` (`cellblender/cellblender_mol_viz.py:496`) tears down the previous
frame: it unlinks/removes each `mol_*` object + position mesh and recreates an empty
mesh, **preserving the per-object visibility (hide) state** so toggling a species off
persists across frames. With `force_clear=True` it sweeps every scene object whose
name starts with `mol_` and not ending in `_shape`.

### 2.5 Coupling to Blender's timeline (frame handlers)

```
scrub timeline ─► frame_change_pre ─► frame_change_handler(scn)
                                        sets mol_viz.mol_file_index = scn.frame_current
                                        bpy.ops.mcell.mol_viz_set_index()
                                          └► mol_viz_update() ► mol_viz_clear()
                                                              + mol_viz_file_read(frame)
```

- **`frame_change_handler(scn)`** — `@persistent`, `cellblender/cellblender_mol_viz.py:418`.
  Registered onto `bpy.app.handlers.frame_change_pre` at
  `cellblender/__init__.py:443`. On every frame change it syncs `mol_file_index` to
  `scene.frame_current` and invokes `mcell.mol_viz_set_index`.
- **`mol_viz_update(self, context)`** — `:472`. Looks up the current frame's filename
  in `global_mol_file_list`, then `mol_viz_clear()` + `mol_viz_file_read()`.
  It **disables global undo** around the rebuild (`use_global_undo = False`, `:484`)
  to avoid blowing up the undo stack / memory on every scrub.
- **`read_viz_data_load_post`** — `@persistent` load_post handler (`:104`, registered
  `cellblender/__init__.py:458`) auto-loads viz data when a `.blend` opens.
- **`viz_data_save_post`** — `@persistent` save_post handler (`:110`, registered
  `cellblender/__init__.py:468`). If you "Save As" to a path that no longer matches
  the viz directory, it **clears** `global_mol_file_list` and `mol_file_dir` so stale
  viz isn't shown against the wrong project — `:127-131`.

> **Performance gotchas.**
> - `mol_viz_enable=False` (`:1486`) short-circuits drawing in `mol_viz_update`
>   (`:488`) for faster playback preview — the documented escape hatch for large
>   datasets.
> - Every frame change fully **rebuilds** all molecule objects/meshes from disk; there
>   is no caching across frames. Large molecule counts → slow scrubbing.
> - The file-list `template_list` UI is intentionally disabled (`:1811-1815`) and the
>   per-frame list is kept in a module global, both to avoid UI/`.blend` bloat.

### 2.6 Custom visualization scripts

`viz_code` can be `custom` or `both` (`:1502-1509`). In that mode
`mol_viz_file_read` reads a user Python script (internal `bpy.data.texts` entry or an
external `.py`), stashes the current frame path in `mol_viz.frame_file_name`,
`compile()`s and `exec()`s it (`:954-978`). `MCELL_OT_viz_script_refresh`
(`:1440`) + `update_available_viz_scripts()` (`:1417`) populate the script picker.
`custom` skips standard drawing entirely; `both` runs the script then draws normally.

---

## 3. Reaction-data output — `cellblender/cellblender_reaction_output.py`

### 3.1 Defining what to count

`MCellReactionOutputProperty` (`cellblender/cellblender_reaction_output.py:657`) is one
count specification. Key fields:

- `rxn_or_mol` enum — `Molecule` / `Reaction` / `MDLString` / `File`
  (`:691-700`). `MDLString` lets the user write a raw `COUNT[...]` expression;
  `File` just plots an existing `.dat` without generating anything.
- `count_location` enum — `World` / `Object` / `Region` (`:683-690`), plus
  `object_name` / `region_name`.
- Region-counting modifiers: `all_enc` (all-enclosed), `est_conc` (estimate
  concentration), `trig` (triggers), and hits/crossings flags
  (`hit_front/back/all`, `cross_front/back/all`) on the *group* —
  `:833-844`, drawn conditionally at `:1106-1158`.
- `plotting_enabled` per item; `status` holds validation errors.

`MCellReactionOutputPropertyGroup` (`:819`) is the panel/collection wrapper:
`rxn_output_list` (CollectionProperty of the above, `:845`), output `rxn_step` and
`output_buf_size` parameters (`:821-824`), and **plot options**: `plot_layout`
(page/plot layout, `:846-853`), `plot_legend` placement (`:854-870`),
`combine_seeds` (`:871`), `mol_colors` (use molecule material color as the line
color, `:875`), `plotter_to_use` (`:883`), and `ignore_start_time` (`:894`).

**Operators** (`:59-137`): `mcell.rxn_output_add` / `_remove`, `mcell.rxn_out_all_world`
(adds a World count for every molecule), `mcell.rxn_output_enable_all` / `_disable_all`.

### 3.2 Validation — `check_rxn_output()`

`check_rxn_output()` (`cellblender/cellblender_reaction_output.py:524`) runs as the
`update` callback on most fields. It builds the human-readable item name
("Count X in World" / "in/on Object" / "in/on Object[Region]"), validates the
molecule/reaction name against the model lists with a regex
(`r"(^[A-Za-z]+[0-9A-Za-z_.]*)"`, `:575`), checks the object/region exists, and flags
duplicates — writing any problem to `rxn_output.status` (shown with an ERROR icon in
the UIList `MCELL_UL_check_reaction_output_settings`, `:636`).
`update_name_and_check_rxn_output()` (`:616`) additionally sets the display name for
`MDLString`/`File` items. Guards avoid infinite-recursion (setting `.name` re-triggers
the callback) by only writing when the value actually changes.

### 3.3 Reading the count files & dispatching to plotters

The heavy lifting is `MCELL_OT_plot_rxn_output_with_selected`
(`mcell.plot_rxn_output_with_selected`, `cellblender/cellblender_reaction_output.py:164`),
bound to the "Plot" button (`:1194`):

1. **Pick the plotter** by matching `plotter_to_use` against
   `cellblender.cellblender_info['cellblender_plotting_modules']` — `:183-189`.
2. **Resolve the data root & sweep paths.** Reads `data_layout.json`; `mcell4_mode`
   uses cwd, otherwise checks for `output_data/` to decide sweep vs legacy
   (`react_data/`) layout — `:191-214`. For **sweep v2** it expands the
   `data_layout` levels into one `run_path` (+ a human "parameter point" label
   `par_path`) per parameter combination — `:234-291` (a v1/legacy branch follows,
   `:292-342`).
3. **Find the per-item `.dat` file(s).** Builds the filename from the count spec:
   `<mol>.World.dat`, `<mol>.<obj>.dat`, `<mol>.<obj>.<region>.dat`, the
   `<prefix>_MDLString.dat` form, or a literal `File` path — `:367-399`. Then it
   **globs across all seeds** (`seed_*/<file>`), with fallbacks that retry without the
   `_MDLString` suffix and with `.`→`_` substitution — `:412-434`.
4. **Filter stale files.** Unless `ignore_start_time`, it drops files older than
   `start_time.txt` (minus 10 s) so a previous run's output isn't plotted — `:440-445`.
   **Gotcha:** this start-time filter is MCell3-only (skipped in `mcell4_mode`).
5. **Build a generic plot-spec string** of space-separated tokens
   (`xlabel=… ylabel=… legend=… title=… ppt=… color=#rrggbb f=<relpath>` plus
   `tf=<tmpfile>`) — `:356-512`. `mol_colors` pulls the line color from the molecule's
   `mol_<name>_mat` material (`:472-486`). A temp file records the data path
   (`create_reactdata_tmpfile`, `:146`).
6. **Dispatch:** `plot_module.plot(root_path, plot_spec_string, python_path)` — `:516`.

The `.dat` files themselves are simple two-column `time<whitespace>count` time-series;
they are parsed by the **plotter subprocess**, not by CellBlender. CellBlender only
locates the files and constructs the spec string.

### 3.4 Linkage to `data_plotters/` (see also doc 05)

Plotter plugins live in `cellblender/data_plotters/` and are discovered at add-on
startup by `data_plotters.find_plotting_options()`
(`cellblender/data_plotters/__init__.py:43`), which imports every subdir containing an
`__init__.py` and keeps those whose `requirements_met()` returns true. The survivors
are stored in `cellblender.cellblender_info['cellblender_plotting_modules']`
(`cellblender/__init__.py:426-434`).

Each plugin exposes a uniform interface — `get_name()`, `requirements_met()`,
`plot(data_path, plot_spec, python_path=None)` — e.g.
`cellblender/data_plotters/mpl_plot/__init__.py:9,13,23`. `plot()` typically launches
an **external `subprocess.Popen`** (its own `*.py` run under the bundled Python, or
`gnuplot`/`xmgrace`/`java`) parsing the generic plot-spec tokens —
`cellblender/data_plotters/mpl_plot/__init__.py:55`. Available plugins:
`mpl_plot`, `mpl_simple`, `gnuplot`, `xmgrace`, `java_plot`. The panel orders them by
a hard-coded preference list in `get_plotters_as_items()`
(`cellblender/cellblender_reaction_output.py:798`).

> **Decoupling gotcha.** CellBlender never imports matplotlib etc. into Blender's
> Python; it shells out so a plotter's heavy dependencies (or a crash) can't take down
> Blender. The price is that plotting is fire-and-forget — no plot data is returned
> into Blender, and errors surface only in the spawned process's console.

---

## 4. Shared sweep descriptor: `data_layout.json`

Both halves consume the same sweep-layout file written by the run engine. It contains
a `data_layout` list of `[key, values]` levels: `/DIR` (top dir), `/FILE_TYPE`
(`viz_data` vs `react_data`), `/SEED`, and one entry per swept parameter whose
subdirectories are named `<param>_index_<N>`. Molecule viz reads it to pick the active
sweep point (`cellblender/cellblender_mol_viz.py:189-215`) and to populate the
`choices_list` enums (`update_data_layout`, `:1698-1767`); reaction output reads it to
enumerate every run path for plotting (`cellblender/cellblender_reaction_output.py:222-291`).

---

## 5. Quick reference

| Need | Symbol | Cite |
|------|--------|------|
| Load viz dir & build frame list | `MCELL_OT_read_viz_data` | `cellblender/cellblender_mol_viz.py:155` |
| Per-frame draw on timeline | `frame_change_handler` → `mol_viz_set_index` → `mol_viz_update` | `cellblender/cellblender_mol_viz.py:418, 391, 472` |
| Parse one frame file (bin v1/v2 + ASCII) | `mol_viz_file_read` | `cellblender/cellblender_mol_viz.py:950` |
| Glyph + GeoNodes instancing | `update_geo_node_tree` | `cellblender/cellblender_mol_viz.py:876` |
| Clear previous frame | `mol_viz_clear` | `cellblender/cellblender_mol_viz.py:496` |
| Frame↔dataset binding | `set_viz_boundaries` | `cellblender/cellblender_mol_viz.py:304` |
| Disable drawing for speed | `mol_viz_enable` | `cellblender/cellblender_mol_viz.py:1486` |
| One count spec | `MCellReactionOutputProperty` | `cellblender/cellblender_reaction_output.py:657` |
| Plot panel / options | `MCellReactionOutputPropertyGroup` | `cellblender/cellblender_reaction_output.py:819` |
| Find `.dat`, build spec, dispatch | `MCELL_OT_plot_rxn_output_with_selected` | `cellblender/cellblender_reaction_output.py:164` |
| Plotter discovery | `find_plotting_options` | `cellblender/data_plotters/__init__.py:43` |
| Handler registration | `add_handler(...)` | `cellblender/__init__.py:443, 458, 468` |

*Part of the CellBlender codebase wiki — see 00_overview.md.*
