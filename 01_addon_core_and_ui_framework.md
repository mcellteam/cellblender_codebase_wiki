# 01 — Add-on Core & UI Framework

> Audience: developers extending or debugging CellBlender. Scope: how the add-on
> boots, how its classes get registered, the root data-model hierarchy hung off
> `bpy.context.scene.mcell`, and the panel/operator/property-group conventions
> that every other CellBlender module follows. Read this before the domain docs
> (molecules, reactions, simulation, etc.) — they all plug into the framework
> described here.

---

## 1. The big picture

CellBlender is a classic Blender add-on built from three kinds of `bpy.types`
subclasses:

| Kind | Base class | Role | Example |
|------|-----------|------|---------|
| Data | `bpy.types.PropertyGroup` | persisted model data (lives in the `.blend`) | `MCellPropertyGroup` (`cellblender/cellblender_main.py:894`) |
| Action | `bpy.types.Operator` | buttons / commands | `PP_OT_init_mcell` (`cellblender/cellblender_main.py:159`) |
| UI | `bpy.types.Panel` / `UIList` / `Menu` | drawing | `MCELL_PT_main_panel` (`cellblender/cellblender_main.py:177`) |

Everything is anchored to a **single root PropertyGroup**, `MCellPropertyGroup`,
which is attached to every Blender Scene as `bpy.context.scene.mcell`
(`cellblender/__init__.py:389`). All of CellBlender's state is reachable from
there. A parallel, much smaller group is attached to every Object as
`bpy.context.object.mcell` (`cellblender/__init__.py:391`, type
`object_surface_regions.MCellObjectPropertyGroup`).

The whole add-on is structured around a **data model** (a plain nested
`dict`/`list`/scalar tree) that mirrors the property tree. Every PropertyGroup
implements a small contract for converting itself to/from that dict — this is
how files are saved, upgraded across versions, scripted, and exported to MCell.
See §6.

---

## 2. Entry point & registration flow — `cellblender/__init__.py`

The package manifest is `cellblender/blender_manifest.toml` (Blender 4.2+
extension format): `id = "cellblender"`, `version = "4.2.0"`,
`blender_version_min = "5.1.0"` (`cellblender/blender_manifest.toml:2-10`). The
classic `bl_info` dict is **not** in `__init__.py`; legacy version metadata lives
in the `cellblender_info` dict in `cellblender_source_info.py` (§5).

### 2.1 Import-time work

When Blender imports the package, `__init__.py` runs top-to-bottom:

1. `importlib.import_module(".cellblender_source_info", ...)` and aliases
   `cellblender_info = cellblender_source_info.cellblender_info`
   (`cellblender/__init__.py:29`). This dict is the global "about me" record used
   everywhere (`cellblender.cellblender_info[...]`).
2. Two parallel **module-name tuples** are declared:
   `IMPORT_MODULE_NAMES` (`cellblender/__init__.py:34`) and
   `REGISTER_MODULE_NAMES` (`cellblender/__init__.py:67`). Everything in the
   first is imported; the subset in the second is also `register()`-ed. Some
   modules (e.g. `cellblender_utils`, `run_simulations`, `sim_runner_queue`,
   `data_plotters`) are imported but not registered — they expose helpers/menus
   rather than Blender classes.
3. A module-level singleton simulation queue is created:
   `simulation_queue = sim_runner_queue.SimQueue(python_path)`
   (`cellblender/__init__.py:232`), where `python_path` comes from
   `cellblender_utils.get_python_path()`.

> **Gotcha — two registration paths exist.** There is an explicit
> `cb_register()` / `cb_unregister()` pair (`cellblender/__init__.py:264`/`293`)
> that lists every module by hand, *and* the data-driven loop inside `register()`
> that iterates `_register_modules`. **`cb_register()` is dead code** (its call
> at line 345 is commented out); the live path is the loop. A large commented-out
> `imp.reload(...)` block (lines 102-189) is also dead — it documents the old
> pre-`importlib` reload scheme. When changing load order, edit the **tuples**,
> not `cb_register()`.

### 2.2 `register()` — the live boot sequence

`register()` (`cellblender/__init__.py:323`) does, in order:

1. Clears `_import_modules` / `_register_modules`, then loops `IMPORT_MODULE_NAMES`,
   importing (or `importlib.reload`-ing) each and appending registered ones to
   `_register_modules` (`cellblender/__init__.py:330-337`).
2. Re-creates the simulation queue (`:339`).
3. **`for module in _register_modules: module.register()`** (`:342`) — this is
   what actually calls each module's own `register()` (each of which calls
   `bpy.utils.register_class` on its `classes` tuple; see §7).
4. Installs File ▸ Import/Export menu items (MDL, BNGL, data-model JSON/txt),
   first `remove`-ing then `append`-ing to avoid duplicates on reload
   (`cellblender/__init__.py:349-385`).
5. **Attaches the root groups** (`cellblender/__init__.py:389-392`):
   ```python
   bpy.types.Scene.mcell  = PointerProperty(type=cellblender_main.MCellPropertyGroup)
   bpy.types.Object.mcell = PointerProperty(type=object_surface_regions.MCellObjectPropertyGroup)
   ```
   Because `cellblender_main` is registered *before* this line, its
   `MCellPropertyGroup` (and all the sub-groups it points to) already exist.
6. Computes the source identity SHA1 (§5), reading it from `cellblender_id.py`
   (`cellblender/__init__.py:417`).
7. Discovers optional data plotters (`:424-437`).
8. **Registers all `bpy.app.handlers`** (frame_change, load_pre/post, save_pre/post,
   depsgraph_update_pre) via the `add_handler` helper (`cellblender/__init__.py:439-468`).
   `add_handler`/`remove_handler` (`:250`/`:258`) just guard against double-adds.
9. `atexit.register(simulation_queue.shutdown)` (`:471`) and a WindowManager
   pointer for molecule labels (`:474`).

### 2.3 Module registration order (the live tuples)

```
parameter_system → cellblender_examples → cellblender_preferences →
cellblender_scripting → cellblender_project → cellblender_simulation →
cellblender_initialization → cellblender_pbc → cellblender_objects →
cellblender_molecules → cellblender_molmaker → cellblender_reactions →
cellblender_release → cellblender_surface_classes → cellblender_surface_regions →
cellblender_reaction_output → cellblender_partitions → cellblender_mol_viz →
cellblender_meshalyzer → cellblender_legacy → object_surface_regions →
io_mesh_mcell_mdl → mdl → bng → cellblender_main → data_model
```
(`cellblender/__init__.py:67-93`)

> **Gotcha — `cellblender_main` registers near the end, on purpose.**
> `MCellPropertyGroup` holds `PointerProperty`s to almost every other group
> (§4), and a Blender PropertyGroup type must be *registered before* another
> group can point to it. Hence all the leaf groups register first and
> `cellblender_main` last (followed only by `data_model`). `unregister()` walks
> `_register_modules[::-1]` (`cellblender/__init__.py:507`) for the reverse order.

> **Gotcha — circular imports are sidestepped with `importlib`.** Several
> modules need the top-level package object. Instead of `import cellblender`
> (which would be circular at load time) they do
> `globals()['cellblender'] = importlib.import_module(__package__)`
> (e.g. `cellblender/cellblender_main.py:53`, `cellblender_examples.py:23`,
> `cellblender_project.py:45`). User scripts conventionally `import cellblender as cb`.

---

## 3. The main Panel & the panel-selector system — `cellblender_main.py`

CellBlender does **not** register a separate Blender panel per feature in the
normal flow. Instead one host panel draws everything, dispatching to each
sub-group's `draw_layout`.

### 3.1 The host panel

`MCELL_PT_main_panel` (`cellblender/cellblender_main.py:177`) lives in the 3D
Viewport sidebar: `bl_space_type = "VIEW_3D"`, `bl_region_type = "UI"`,
`bl_category = "CellBlender"`, `bl_idname = "VIEW3D_PT_CellBlender"`. Its
`draw_header` loads the CellBlender icon image; its entire `draw` body is a
one-liner that delegates:

```python
def draw(self, context):
    bpy.context.scene.mcell.cellblender_main_panel.draw_self(bpy.context, self.layout)
```
(`cellblender/cellblender_main.py:201`)

### 3.2 `CellBlenderMainPanelPropertyGroup` — the selector / dispatcher

`CellBlenderMainPanelPropertyGroup` (`cellblender/cellblender_main.py:355`) is a
PropertyGroup that *is* the menu state. It holds ~20 `BoolProperty` "toggle"
flags (`molecule_select`, `reaction_select`, `objects_select`, `init_select`,
`viz_select`, …) plus `select_multiple` (the "pin" — show several panels at once)
and a `last_state: BoolVectorProperty(size=22)` used to detect button
transitions (`cellblender/cellblender_main.py:380`).

- Every toggle has `update=select_callback`, a module-level shim
  (`cellblender/cellblender_main.py:351`) that forwards to the group's own
  `select_callback` method (`:390`). That method implements radio-button-like
  logic: with the pin off, selecting one panel deselects the others; pinning
  shows all; un-pinning hides all.
- `draw_self` (`cellblender/cellblender_main.py:496`) is the real UI brain. It:
  1. Decides whether to show an **upgrade / init** state (see §6.3) based on
     `saved_by_source_id` vs the current source SHA1.
  2. Draws the row(s) of selector buttons — either a compact single-row of
     icon-only toggles (short format) or a two-column labelled layout (long
     format), gated by `mcell.cellblender_preferences.use_long_menus`
     (`:572` vs `:647`).
  3. For each toggle that is on, draws a separator box, a label, and calls the
     corresponding sub-group's `draw_layout`, e.g.
     `bpy.context.scene.mcell.molecules.draw_layout(bpy.context, layout)`
     (`cellblender/cellblender_main.py:794-868`).

So the **convention every domain module follows is: implement
`draw_layout(self, context, layout)` on your PropertyGroup**, and add a `prop`
toggle + a dispatch block here. The visible button-show/hide is further gated by
`mcell.cellblender_preferences.show_button_num[N]` (a `BoolVectorProperty(size=17)`).

> **Gotcha — `show_button_num` must stay large enough.** The short-format draw
> indexes `show_button_num[0..16]`; if the preferences array
> (`cellblender/cellblender_preferences.py:487`) is smaller than the number of
> buttons, drawing throws. The code comments at
> `cellblender/cellblender_main.py:583` shout about this.

### 3.3 Other operators in `cellblender_main.py`

| Operator | `bl_idname` | Purpose | Line |
|----------|-------------|---------|------|
| `PP_OT_init_mcell` | `mcell.init_cellblender` | First-time init of the whole tree | `:159` |
| `MCELL_OT_upgrade` | `mcell.upgrade` | Upgrade `.blend` via data model | `:244` |
| `MCELL_OT_export_dm` | `mcell.export_data_model` | Dump data model to `DM.txt` | `:261` |
| `MCELL_OT_export_dm_json` | `mcell.export_data_model_json` | Dump to `DM.json` | `:286` |
| `MCELL_OT_delete` | `mcell.delete` | `remove_properties` on the whole tree | `:311` |
| `CBM_OT_refresh_operator` | `cbm.refresh_operator` | Rebuild/reload params, mols, geometry, viz | `:327` |

`cellblender_main.py` also defines the persistent handlers `mcell_valid_update`
(`:90`), `init_properties` (`:100`), `report_load_pre` (`:207`) and
`scene_loaded` (`:217`). `scene_loaded` lazily loads the icon PNGs and then
**removes itself** from `depsgraph_update_pre` once icons exist
(`:237-240`); it also force-disables Python scripting on load (§8).

---

## 4. The root PropertyGroup hierarchy — `MCellPropertyGroup`

`MCellPropertyGroup` (`cellblender/cellblender_main.py:894`) is the tree root.
Besides scalar version fields it is a bag of `PointerProperty`s, one per
subsystem. Selected mapping (all at `cellblender/cellblender_main.py:912-944`):

| Attribute (`scene.mcell.…`) | Pointed-to type | Owning module |
|------|------|------|
| `cellblender_main_panel` | `CellBlenderMainPanelPropertyGroup` | cellblender_main |
| `cellblender_preferences` | `CellBlenderPreferencesPropertyGroup` | cellblender_preferences |
| `cellblender_examples` | `CellBlenderExamplesPropertyGroup` | cellblender_examples |
| `scripting` | `CellBlenderScriptingPropertyGroup` | cellblender_scripting |
| `project_settings` / `export_project` | `MCellProjectPropertyGroup` / `MCellExportProjectPropertyGroup` | cellblender_project |
| `initialization` | `MCellInitializationPropertyGroup` | cellblender_initialization |
| `parameter_system` | `ParameterSystemPropertyGroup` | parameter_system |
| `molecules` / `molmaker` | `MCellMoleculesListProperty` / `MCellMolMakerPropertyGroup` | cellblender_molecules / molmaker |
| `reactions` | `MCellReactionsListProperty` | cellblender_reactions |
| `release_sites` / `release_patterns` | `MCellMoleculeReleasePropertyGroup` / `MCellReleasePatternPropertyGroup` | cellblender_release |
| `surface_classes` / `mod_surf_regions` | surface classes / regions groups | cellblender_surface_* |
| `model_objects` | `MCellModelObjectsPropertyGroup` | cellblender_objects |
| `partitions` / `pbc` | partitions / PBC groups | cellblender_partitions / pbc |
| `run_simulation` / `sim_engines` / `sim_runners` | `MCellRunSimulationPropertyGroup` / `Pluggable` ×2 | cellblender_simulation |
| `viz_output` / `mol_viz` | viz output / mol-viz groups | cellblender_mol_viz |
| `rxn_output` | `MCellReactionOutputPropertyGroup` | cellblender_reaction_output |
| `meshalyzer` | `MCellMeshalyzerPropertyGroup` | cellblender_meshalyzer |
| `legacy` | `MCellLegacyGroup` | cellblender_legacy |

Key methods on the root group:

- `init_properties(context)` (`:948`) — seeds version fields, calls each major
  sub-group's `init_properties`, and stamps
  `self['saved_by_source_id'] = cellblender_info['cellblender_source_sha1']`,
  then sets `self.initialized = True`.
- `remove_properties(context)` (`:971`) — tears down every sub-group (reverse
  dependency order).
- `build_data_model_from_properties(...)` / `build_properties_from_data_model(...)`
  / `upgrade_data_model(...)` — the serialization contract; see §6.
- `draw_uninitialized(layout)` (`:1310`) — draws the single "Initialize
  CellBlender" button shown before init.

> **Gotcha — ID-properties vs RNA properties.** `saved_by_source_id` and
> `api_version` are stored as raw Blender **ID-properties** (`self['…']`),
> not declared RNA `*Property` fields. They survive in the `.blend` even across
> CellBlender versions and are how a stale file is detected (`:501`, `:513`).

---

## 5. Source identity / version — `cellblender_source_info.py`, `cellblender_id.py`, `update_cellblender_id.py`

CellBlender fingerprints its own source so it can tell when a `.blend` was saved
by a *different* build and offer an upgrade.

- **`cellblender_source_info.py`** holds the master `cellblender_info` dict
  (`:5`) — `version`, `supported_version_list`, an explicit
  `cellblender_source_list` of every source file to hash (`:16-266`), plus
  mutable runtime slots (`cellblender_source_sha1`, `versions_match`,
  `cellblender_addon_path`, `cellblender_plotting_modules`).
  `identify_source_version(addon_path)` (`:275`) SHA1's every listed file in
  order and stores the hex digest in `cellblender_info['cellblender_source_sha1']`.
- **`cellblender_id.py`** is a **one-line autogenerated file**:
  `cellblender_id = '5f9d79da…'` (`cellblender/cellblender_id.py:1`). It is the
  cached SHA1, deliberately **excluded** from `cellblender_source_list` (see the
  warning banner at `cellblender_source_info.py:13`).
- At boot, `register()` reads the SHA1 *as text* out of `cellblender_id.py`
  rather than recomputing it (`cellblender/__init__.py:417`). Two alternative
  strategies (recompute on load; import the id as code) are present but commented
  out at `:408-413` — only the text-read path is live.
- **`update_cellblender_id.py`** is a standalone CLI script
  (`python3 update_cellblender_id.py`) that recomputes the hash and rewrites
  `cellblender_id.py` *only if it changed* (`:21-30`).

> **Gotcha — refresh the ID before every pushed commit.** Per
> `cellblender/CLAUDE.md`, run `update_cellblender_id.py` and include the
> regenerated `cellblender_id.py` in the commit. Forgetting it means installed
> CellBlenders won't notice the new version (or will spuriously offer upgrades).
> The script is a no-op when nothing changed, so it's always safe to run.

The "Project Settings" panel shows the live ID and a `refresh_source_id`
toggle whose callback (`refresh_source_id_callback`,
`cellblender/cellblender_main.py:876`) recomputes the SHA1 and stashes the
file's original id under `cellblender_info['cellblender_source_id_from_file']`
if they differ, so the panel can flag a mismatch
(`cellblender/cellblender_project.py:73-80`).

---

## 6. The data-model contract (cross-cutting — the heart of CellBlender)

Every substantial PropertyGroup implements the same five methods (documented in
the header comment at `cellblender/cellblender_main.py:19-34`):

| Method | Purpose |
|--------|---------|
| `init_properties` | create a fresh property subtree |
| `build_data_model_from_properties(context, …)` | serialize properties → plain dict |
| `@staticmethod upgrade_data_model(dm)` | bump an older dict to the current version |
| `build_properties_from_data_model(context, dm, …)` | deserialize dict → properties |
| `check_properties_after_building(context)` | resolve cross-references afterward |

### 6.1 Serialization down the tree

`MCellPropertyGroup.build_data_model_from_properties`
(`cellblender/cellblender_main.py:998`) builds a dict tagged
`data_model_version = "DM_2017_06_23_1300"` and a `model_language`
(`mcell4` / `mcell3r` / `mcell3`, from preferences), then calls each sub-group's
`build_data_model_from_properties` and stows the result under a well-known key
(`parameter_system`, `define_molecules`, `define_reactions`, `release_sites`,
`model_objects`, …). With `geometry=True` it also captures mesh geometry and
materials (`:1034-1037`).

### 6.2 Upgrade & rebuild

`upgrade_data_model` (`:1042`, a `@staticmethod`) walks each known group key and
calls that group's own `upgrade_data_model`, returning `None` if any step can't
be upgraded. `build_properties_from_data_model` (`:1165`) verifies the version,
calls `remove_properties`, then `init_properties`, then for each present key
calls the sub-group's `build_properties_from_data_model`, and finally runs every
`check_properties_after_building` to fix up dangling references
(`:1280-1304`).

The top-level wrappers live in `__init__.py`: `get_data_model()` (`:195`) and
`replace_data_model(dm, …)` (`:202`) wrap the dict in `{'mcell': …}`, run the
upgrade, and rebuild — this is the public API user scripts and the examples
loader use.

### 6.3 How the upgrade UI is triggered

`draw_self` compares `mcell['saved_by_source_id']` to the live source SHA1
(`cellblender/cellblender_main.py:513`). If absent → uninitialized or a very old
RC3/RC4 file (offers `mcell.upgraderc3`, §9). If present but different → the
normal "Upgrade Blend File" button (`mcell.upgrade`). If equal → draw the
normal panels. The data model is persisted into the `.blend` by `data_model`'s
`save_pre`/`load_post` handlers (see `data_model.py`, documented elsewhere; note
`mcell['data_model']` and `saved_by_source_id` are set there too,
`cellblender/data_model.py:752`).

---

## 7. The per-module registration convention — `cellblender_utils.py` and the `classes` tuple

Almost every CellBlender module ends with the same boilerplate:

```python
classes = ( SomeOperator, SomePropertyGroup, … )
def register():
    for cls in classes: bpy.utils.register_class(cls)
def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
```
(e.g. `cellblender/cellblender_examples.py:776`,
`cellblender/cellblender_project.py:490`,
`cellblender/cellblender_main.py:1339`,
`cellblender/cellblender_initialization.py:732`,
`cellblender/cellblender_preferences.py:734`). The package `register()` simply
calls each of these in tuple order.

**`cellblender_utils.py`** (199 lines) is a registration-free helper grab-bag
shared everywhere:

- Path helpers `project_files_path()` (`:55`) and `mcell_files_path()` (`:64`) —
  both derive `<blendfile>_files/…` from `bpy.data.filepath`.
- Binary discovery `get_python_path(...)` (`:136`) and `get_mcell_path(mcell)`
  (`:156`), preferring the user-set path, then the bundled
  `extensions/mcell/mcell`, then `shutil.which`; `is_executable()` (`:175`).
- `try_to_import()` (`:119`) runs a subprocess to test a Python's importability.
- Property-tree navigation `get_path_to_parent()` / `get_parent()`
  (`:188`/`:194`) — these `eval` a `path_from_id()` string to walk *up* the
  Blender property tree (Blender gives children no parent pointer).
- UI utilities `wrap_long_text()` (`:18`), `timeline_view_all()` (`:39`),
  `preserve_selection_use_operator()` (`:73`), `check_val_str()` (`:99`).

---

## 8. Preferences & dynamic panels — `cellblender_preferences.py`

`CellBlenderPreferencesPropertyGroup` (`cellblender/cellblender_preferences.py:419`)
holds add-on settings as RNA props: the three binary paths
(`mcell_binary`, `python_binary`, `bionetgen_location`) each paired with a
`*_valid` bool and an `update=` callback that re-checks executability and
auto-saves (`:421-426`, callbacks `check_mcell_binary` `:46`, etc.); engine-mode
toggles (`mcell4_mode`, `bionetgen_mode`, `bionetgen_units_mode`); UI prefs
(`use_long_menus`, `use_stock_icons`, `show_button_num`); and policy flags
(`invalid_policy`, `decouple_export_run`, `lockout_export`, `require_mcell`).

Preferences are persisted via Blender's **preset** mechanism, not the data
model: `MCELL_MT_presets` (`:235`) + `MCELL_OT_save_preferences`
(an `AddPresetBase` operator, `:268`) write a `cellblender/Cb` preset listing
`preset_values` (`:281-291`). The `load_preferences` load_post handler (`:244`)
`exec`s that preset file on file load. Binary-setter operators
`mcell.set_mcell_binary` / `set_python_binary` / `set_bionetgen_location`
(`:320`/`:339`/`:357`) open a file browser; theme operators reset/recolor the
viewport (`:376-417`).

> **Gotcha — the "old scene panel" machinery is effectively dead code.**
> `show_old_scene_panels()` / `show_hide_tool_panel()` / `show_hide_scene_panel()`
> (`cellblender/cellblender_preferences.py:75-150`) try to `register_class`
> panel types like `MCELL_PT_main_scene_panel`, `MCELL_PT_initialization`,
> `cellblender_project.MCELL_PT_project_settings`, etc. — **none of which are
> imported in this file and several of which no longer exist** (there is no
> `MCELL_PT_main_scene_panel` definition anywhere; `cellblender_initialization.py`
> defines no `MCELL_PT_initialization`). Every call is wrapped in
> `try/except: pass`, so the related preference toggles
> (`show_scene_panel`, `show_old_scene_panels`, `show_tool_panel`,
> `:490-500`) silently do nothing. The live UI is the single
> `MCELL_PT_main_panel` from `cellblender_main.py`.

---

## 9. Initialization settings — `cellblender_initialization.py`

`MCellInitializationPropertyGroup` (`cellblender/cellblender_initialization.py:44`)
is the "Run Simulation" / model-init settings group reached via
`scene.mcell.initialization`. It is mostly a set of `Parameter_Reference`
PointerProperties (so each value is a live parameter expression, not a raw
number): `iterations`, `time_step`, plus advanced fields `time_step_max`,
`space_step`, `interaction_radius`, `radial_directions`,
`radial_subdivisions`, `vacancy_search_distance`, `surface_grid_density`
(`:50-66`). `init_properties(parameter_system)` (`:70`) seeds each via
`init_ref(...)` with default expression, units, and help text. It implements the
full data-model contract (`build_data_model_from_properties` `:184`,
`draw_layout` `:547`) and is registered with the single-class `classes` tuple
(`:732`).

---

## 10. Project / file management — `cellblender_project.py`

`MCellProjectPropertyGroup` (`cellblender/cellblender_project.py:57`) holds the
`base_name` for generated files and a `status` string; its `draw_layout` (`:63`)
renders the "Project Settings" box (the source-ID line, version-mismatch
warnings, and project-directory status). `MCellExportProjectPropertyGroup`
(`:123`) selects unified vs modular MDL output. `MCELL_OT_export_project`
(`mcell.export_project`, `:135`) writes the model out as MCell MDL; its `poll`
(`:141`) honors `cellblender_preferences.lockout_export`. Project paths are
always derived from `cellblender_utils.project_files_path()` (the
`<blend>_files/` convention).

---

## 11. In-app scripting — `cellblender_scripting.py`

This module (`scene.mcell.scripting`, type `CellBlenderScriptingPropertyGroup`,
`cellblender/cellblender_scripting.py:828`) is CellBlender's user-Python and
data-model hook system. It manages lists of scripts that are either **internal**
(Blender Text data-blocks in `bpy.data.texts`) or **external** (files on disk),
in several flavors: MDL include scripts, Python export scripts, MCell4 scripts,
and "data model" scripts (`internal_*_scripts_list` / `external_*_scripts_list`,
`:834-841`).

How a data-model script runs: `MCELL_OT_scripting_execute`
(`mcell.scripting_execute`, `:454`) calls
`CellBlenderScriptingPropertyGroup.execute_selected_script` (`:1002`), which
builds the current data model, then **`exec(script_text, locals())`** on the
selected internal text (`:1046-1050`). The intended user API inside such scripts
is `cb.get_data_model()` / `cb.replace_data_model()` (the `__init__.py` helpers,
§6.2) — the script mutates a `dm` dict and pushes it back. Export/simulation
scripts are also `exec`-ed during model export (`:1269`, `:1281`).

The module additionally embeds a **data-model browser** (`DataBrowserPropertyGroup`
`:74`, panel `Data_Browser_Panel` `:341`, and `browser.*` operators) for
inspecting the live data model tree, and `CopyDataModelFromSelectedProps`
(`cb.copy_sel_data_model_to_cbd`, `:469`) to copy a chosen data-model section to
the clipboard as text.

> **Gotcha — scripting is a security surface and is force-disabled on load.**
> Running a model can `exec` arbitrary embedded Python. To avoid silently
> executing code from an opened `.blend`, the `enable_python_scripting` flag
> (`cellblender/cellblender_simulation.py:2278`, intentionally *not* in the data
> model) is reset to `False` by both `scene_loaded`
> (`cellblender/cellblender_main.py:219`) and the `disable_python` load_post
> handler (`cellblender/cellblender_simulation.py:2052`). The user must
> re-enable it each session.

---

## 12. Bundled examples — `cellblender_examples.py`

`CellBlenderExamplesPropertyGroup` (`cellblender/cellblender_examples.py:708`)
is the "Examples" panel (`scene.mcell.cellblender_examples`). It is almost pure
UI: `draw_layout` (`:710`) lists one `row.operator(...)` per bundled model. Each
example is a `MCELL_OT_load_*` operator (≈20 of them, `:114-704`) whose
`execute` does the same thing: pull a prebuilt data-model dict from the
`examples` subpackage and load it, e.g.

```python
dm = {'mcell': examples.lv.lv_rxn_lim_dm}
cellblender.replace_data_model(dm, geometry=True)
view_all()
```
(`cellblender/cellblender_examples.py:120-128`)

i.e. examples reuse the §6.2 `replace_data_model` path. The module also carries
viewport helper functions (`view_all`, `scale_view_distance`,
`hide_manipulator`, `:43-110`) used after loading so the model frames nicely.
Some examples set `cellblender_preferences.mcell4_mode/bionetgen_mode` and append
geometry from a bundled `.blend` (`mcell.load_dynamic_geometry`, `:667`).

---

## 13. Legacy compatibility — `cellblender_legacy.py`

`cellblender_legacy.py` exists only to read **CellBlender RC3/RC4** `.blend`
files (those predate the versioned data model). `MCELL_OT_upgradeRC3`
(`mcell.upgraderc3`, `cellblender/cellblender_legacy.py:76`) is the operator the
main panel offers when `saved_by_source_id` is missing (§6.3); it calls
`data_model.upgrade_RC3_properties_from_data_model`. `MCellLegacyGroup`
(`:92`, reached via `scene.mcell.legacy`) provides
`build_data_model_from_RC3_ID_properties` (`:146`) plus a family of
`RC3_add_from_ID_*` helpers (`:107-146`) that scrape the old raw ID-property
layout (objects, molecules, reactions, …) into an unversioned dict that the
normal `upgrade_data_model` chain can then bring current. Registered via the
two-class `classes` tuple (`:809`).

---

## 14. Boot/teardown cheat-sheet

```
Blender enables add-on
        │
        ▼
__init__.register()                         cellblender/__init__.py:323
  ├─ import IMPORT_MODULE_NAMES (build _register_modules)      :330
  ├─ for m in _register_modules: m.register()  ── each does bpy.utils.register_class(classes)
  ├─ install File ▸ Import/Export menu items                   :349
  ├─ Scene.mcell  = PointerProperty(MCellPropertyGroup)        :389
  │   Object.mcell = PointerProperty(MCellObjectPropertyGroup) :391
  ├─ read source SHA1 from cellblender_id.py                   :417
  ├─ discover data plotters                                    :424
  ├─ add_handler(...) for load/save/frame/depsgraph handlers   :439
  └─ atexit.register(simulation_queue.shutdown)                :471
        │
        ▼
User clicks "Initialize CellBlender" (mcell.init_cellblender)
        │
        ▼
MCellPropertyGroup.init_properties()        cellblender/cellblender_main.py:948
  └─ builds the whole sub-group tree, stamps saved_by_source_id
        │
        ▼
MCELL_PT_main_panel.draw → cellblender_main_panel.draw_self()  :496
  └─ dispatches to each scene.mcell.<group>.draw_layout(...)
```

`unregister()` (`cellblender/__init__.py:480`) reverses everything: removes
handlers, unregisters the WindowManager pointer, `atexit.unregister`s the queue,
and walks `_register_modules[::-1]` calling each module's `unregister()`.

---

*Part of the CellBlender codebase wiki — see 00_overview.md.*
