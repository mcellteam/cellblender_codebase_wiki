# 06 — Running simulations: configuration, engines & runners

> **Audience/scope:** Developers who need to understand how CellBlender turns an in-Blender
> model into a *running* simulation: how run settings are stored, how the model is exported
> (MDL for MCell3 vs. MCell4 Python), how an **engine** and a **runner** are chosen, how
> processes are launched and tracked, and how external **BNGL/SBML** models are imported.
> Builds on doc 05 (export / data-model → MDL). See `00_overview.md` for the map.

---

## 1. The big picture: export → engine → runner → results

CellBlender separates *what* to simulate (the **engine**: MCell3, MCell3R/Rules, MCell4,
prototype C++/Python, Smoldyn, …) from *how/where* the job is executed (the **runner**:
local queue, SGE, batch system, …). In practice almost every user run goes through one
hard-wired pipeline ("MCell Local" = `SWEEP_QUEUE`); the fully pluggable engine/runner
manager is a parallel, "experimental" (`DYNAMIC`) path.

```
 User clicks "Run"  (MCELL_OT_run_simulation, cellblender_simulation.py:417)
         │  dispatches on run_simulation.simulation_run_control
         ▼
 ┌───────────────────────────────────────────────────────────────────────┐
 │ SWEEP_QUEUE  → MCELL_OT_run_simulation_sweep_queue  (:712)  ← THE DEFAULT│
 │ SWEEP_SGE    → MCELL_OT_run_simulation_sweep_sge    (:1027)             │
 │ DYNAMIC      → MCELL_OT_run_simulation_dynamic      (:1484)  pluggable  │
 │ (legacy, commented out of the menu but code lives on):                  │
 │   QUEUE      → run_simulation_control_queue         (:1285)             │
 │   COMMAND    → run_simulation_control_normal        (:1183)             │
 │   SWEEP      → run_simulation_control_sweep         (:532)              │
 └───────────────────────────────────────────────────────────────────────┘
         │
         ▼  for each (sweep-point × seed):
   1. build data model from Blender props  (mcell.build_data_model_from_properties)
   2. EXPORT: write MDL  (data_model_to_mdl.write_mdl)   ← MCell3 path  (doc 05)
            OR convert to MCell4 Python (mcell4.convert_data_model_to_python)
   3. enqueue a subprocess in cellblender.simulation_queue (a SimQueue)
         │
         ▼
   sim_runner_queue.SimQueue → run_wrapper.py → Popen(mcell / python model.py)
         │
         ▼
   output_data/.../react_data + viz_data ;  job status tracked in task_dict
```

The two flag fields `export_requested` / `run_requested`
(`cellblender_simulation.py:2301-2302`) let the *same* operator body do export-only,
run-only, or both — needed because the "Decouple Export and Run" preference can split
those two phases, and because a sweep must be traversed once to export and again to run
(`cellblender_simulation.py:761-769`).

---

## 2. Run-settings PropertyGroup — `MCellRunSimulationPropertyGroup`

Defined at `cellblender_simulation.py:2277`, registered as `scene.mcell.run_simulation`.
This single group holds essentially all run configuration. Key fields:

| Field | Line | Meaning |
|-------|------|---------|
| `start_seed` / `end_seed` | 2304-2305 | Seed range (Parameter_Reference pointers, so they can be expressions). One run per seed. |
| `run_limit` | 2306 | Safety cap on total runs (seeds × sweep points); `-1` = no limit. Checked in `MCELL_OT_run_simulation.execute` (:495). |
| `mcell_processes` | 2307 | Parallel worker count; defaults to `cpu_count()`. |
| `log_file` / `error_file` | 2317 / 2324 | `none` / `file` / `console` — where stdout / stderr go. |
| `remove_append` | 2330 | `remove` wipes prior `react_data`/`viz_data`; `append` keeps it. |
| `simulation_run_control` | 2369 | EnumProperty selecting the runner path (see §1). `items` is the **function** `simulation_engine_and_run_enum` list at :2361 → only `SWEEP_QUEUE`, `SWEEP_SGE`, `DYNAMIC` are exposed; `QUEUE`/`COMMAND`/`SWEEP` are commented out. |
| `processes_list` / `active_process_index` | 2335 / 2338 | `CollectionProperty` of `MCellRunSimulationProcessesProperty` — one UI row per launched job (named `"PID: …, Seed: …"`). |
| `status` | 2340 | Status string shown in the panel. |
| `error_list` | 2341 | Pre-run model errors; with `invalid_policy=='dont_run'` blocks the run. |
| `save_text_logs` | 2353 | If set, each job gets a Blender text datablock capturing its console output. |
| `text_update_timer_delay` | 2358 | Poll interval (s) for the percentage-done modal timer. |
| `export_requested` / `run_requested` | 2301-2302 | Phase flags (see §1). |
| `enable_run_once_script` + `internal_external` + `dm_run_once_*` | 2287-2299 | Optional "run-once" script executed against the data model just before export (`exec`'d at :829). |
| SGE fields: `sge_host_name`, `sge_email_addr`, `computer_list`, `required_memory_gig`, … | 2279-2284 | Sun Grid Engine host selection. |

`init_properties` (:2378) seeds the three Parameter_Reference fields (start=1, end=1,
run_limit=12). **Gotcha:** because `simulation_run_control.items` is a function, it cannot
declare a `default=` (noted at :2372) — the first enum entry wins by position.

The "experimental" engine/runner selection lives in two **separate** `Pluggable`
PropertyGroups, `scene.mcell.sim_engines` and `scene.mcell.sim_runners` (see §6), *not*
in this group.

---

## 3. The "Run" entry operator — dispatch

`MCELL_OT_run_simulation` (`cellblender_simulation.py:417`) is the button target. Its
`execute` (:467):

1. Computes `num_runs_requested = (1 + end - start) × count_sweep_runs()` and aborts if it
   exceeds `run_limit` (:482-497).
2. Sets `export_requested`/`run_requested` from the `decouple_export_run` preference
   (:485-489).
3. Normalizes the scene name into a legal MCell `base_name` (:504-509).
4. Dispatches to the concrete operator by `simulation_run_control` (:512-525).

Its `poll` (:423) disables the button while a `QUEUE`/`DYNAMIC` job for the model is still
`running`/`queued` (inspecting `cellblender.simulation_queue.task_dict`).

A separate **export-only** operator `MCELL_OT_dm_export_mdl` (`mcell.dm_export_mdl`, :379)
sets `export_requested=True, run_requested=False` and calls the sweep-queue operator so it
writes MDL without launching.

---

## 4. The default pipeline — `MCELL_OT_run_simulation_sweep_queue`

`cellblender_simulation.py:712` — registered as `mcell.run_simulation_sweep_queue`. This
is the operator behind the "MCell Local" menu item and the one that actually exercises
export + sweep + MCell3/MCell4 selection + queueing. Flow of `execute` (:719):

1. **MCell4 mode check** — `mcell.cellblender_preferences.mcell4_mode` (:725) selects the
   MCell4 (Python) export path vs. the MCell3 (MDL) path later.
2. **Library path env** — copies `os.environ` and prepends the binary's `lib/` dir to
   `DYLD_LIBRARY_PATH` (macOS) or `LD_LIBRARY_PATH` (:738-749). This `my_env` is passed to
   every spawned process.
3. **Output dirs** — under `output_data/`, optionally wipes then recreates
   `react_data`/`viz_data` when `export_requested && remove_append=='remove'`
   (:774-787).
4. **Build the data model** — with geometry+scripts when exporting, without when only
   running (:835-841).
5. **Build the sweep** — `sim_engine_manager.build_sweep_list(dm['parameter_system'])`
   (:843) enumerates swept parameters; `count_sweep_runs` (:855) gives the grid size;
   `write_sweep_list_to_layout_file` writes `data_layout.json` (:852) describing the output
   directory tree (consumed later by plotting/viz).
6. **Per-sweep-point, per-seed loop** (:866-910): builds a nested directory
   `output_data/<par>_index_<i>/…`, sets each swept parameter's `par_expression` to the
   current value, then **exports**:
   - **MCell4 (`mcell4_mode`)** (:886-895): writes `<base>.data_model.json`, then
     `mcell4.convert_data_model_to_python(...)` runs the external `data_model_to_pymcell`
     converter to emit a runnable `*_model.py`. Conversion failure aborts the operator.
   - **MCell3 (default)** (:896-899): `data_model_to_mdl.write_mdl(...)` writes
     `<base>.main.mdl` (the doc-05 export path).
   Each iteration appends a `run_cmd = [binary, wd, base_name, error_opt, log_opt, seed]`.
7. **Launch loop** (:918-1011) — only when `run_requested`. For each `run_cmd` it adds a
   `processes_list` UI row and enqueues a task on `cellblender.simulation_queue`
   (a `SimQueue`, §5). Three sub-cases:
   - **BioNetGen/MCell3R** (`bionetgen_mode && not mcell4_mode`, :949): first converts MDLR
     → MDL via a blocking `Popen` of `mdlr2mdl.py` (:959), then enqueues
     `mcell3r.py -s <seed> -r Scene.mdlr_rules.xml -m Scene.main.mdl` (:982).
     `bionetgen_mode` itself = `data_model_to_mdl.requires_mcellr(dm) or pref.bionetgen_mode`
     (:860).
   - **Plain MCell3** (:984): enqueues `mcell -seed <seed> <base>.main.mdl` (:993).
   - **MCell4** (:995): enqueues `python <base>_model.py -seed <seed>` with
     `MCELL_PATH` set in the env (:1002-1005).
8. Starts the modal progress timer `bpy.ops.mcell.percentage_done_timer()` (:1011).

**Gotcha — the dummy `.main.mdl`:** when exporting a sweep there is no single top-level
MDL, so the code writes a *one-line placeholder* `<base>.main.mdl` purely to signal "this
project has been exported" to CellBlender's export-detection logic (:794-804).

The legacy operators `run_simulation_control_normal` (:1183) and `run_simulation_control_queue`
(:1285) are simpler single-directory variants; `run_simulation_control_normal` and
`run_simulation_control_sweep` (:532) spawn a helper Python script
(`run_simulations.py` / `mdl/run_data_model_mcell.py`) via `subprocess.Popen` that itself
builds a `multiprocessing.Pool` — done this way because `multiprocessing` requires the
`__main__` module be importable by children (:593-596, :1256-1259).

---

## 5. Job execution & tracking — `SimQueue` / `run_wrapper.py` / `OutputQueue`

The runtime machinery lives in `cellblender/sim_runner_queue.py` plus
`cellblender/run_wrapper.py`. A single global `SimQueue` is created at add-on init:

- `cellblender/__init__.py:97` — `simulation_popen_list = []` (legacy direct-Popen jobs).
- `cellblender/__init__.py:231-232` — `simulation_queue = sim_runner_queue.SimQueue(python_path)`.
- `cellblender/__init__.py:471` — `atexit.register(simulation_queue.shutdown)` so child
  processes are torn down on exit.

### `SimQueue` (`sim_runner_queue.py:157`)
- Maintains a `work_q` (thread-safe `Queue`), a pool of worker threads, and
  `task_dict[pid] → {process, cmd, args, status, stdout, stderr, output, bl_text}`
  (:160-167).
- `start(n_threads)` (:170) grows/shrinks the worker pool (shrinking by pushing `None`
  sentinels).
- `add_task(cmd, args, wd, make_texts, env)` (:221) spawns a **`run_wrapper.py`** child via
  `Popen([python, run_wrapper.py, wd], stdin=PIPE, stdout=PIPE, stderr=PIPE)`, records it as
  `status='queued'`, optionally creates a Blender text datablock `task_<pid>_output`, and
  enqueues it. **The PID returned is the wrapper's PID** — that's the key used everywhere to
  track the job.
- `run_q_item` (:182) is the worker loop: pulls a task, sends `cmd` + `args` to the
  wrapper's stdin, and maps the return code to status — `0→completed`, `1→mcell_error`,
  else `died` (:205-211).
- `kill_task(pid)` (:243) terminates running or de-queues queued tasks (→ `died`).
- `shutdown` (:268) signals workers, drains queued tasks, terminates running ones, joins.

### `run_wrapper.py` (the per-job shim)
A tiny standalone script (`cellblender/run_wrapper.py`) that the SimQueue launches. It:
- reads the command and args from **stdin** (quoted-arg parsing, posix vs. windows branch,
  :104/:160),
- `Popen`s the real engine (`mcell`, `python model.py`, …) with `cwd=wd` (:195),
- installs a `SIGTERM` handler that forwards the signal to the child (:197-205) so
  `kill_task` propagates,
- streams the child's stdout/stderr through an `OutputQueue` in *passthrough* mode (:207).

**Why the wrapper exists:** it gives a stable parent PID per job, lets CellBlender capture
live output, and provides a clean kill path. **Gotcha:** the SimQueue's `task_dict` is keyed
on the wrapper PID, not the underlying `mcell` PID; killing therefore goes through the
wrapper's signal handler.

### `OutputQueue` (`sim_runner_queue.py:35`)
Manages a running process's stdout/stderr with reader+writer threads onto `Queue`s
(:41-66), optionally appending each line to a Python list **and** to a Blender text
datablock (`bl_text`) for the in-Blender log overlay. `run_proc` (:81) wires the four
threads, feeds stdin args, waits, and returns `(returncode, (stdout, stderr))`.

### Progress tracking — `MCELL_OT_percentage_done_timer`
`cellblender_simulation.py:643`. A modal timer operator that, every
`text_update_timer_delay` seconds, scans each job's captured `output` lines for the latest
`"Iterations  <n> of <total>"` line, computes a percentage, and rewrites the
`processes_list` row name to `"PID: …, Seed: …, NN%"` (:666-683). It cancels itself when all
tasks are finished or errored (:690). **Gotcha:** it forces a viewport redraw with a
throwaway theme-color tweak (:686-688) because Blender won't otherwise repaint from a timer.

**Kill / cleanup operators:** `MCELL_OT_kill_simulation` (:1409),
`MCELL_OT_kill_all_simulations` (:1448), `MCELL_OT_clear_run_list` (:1932),
`MCELL_OT_clear_simulation_queue` (:1976), `MCELL_OT_remove_text_logs` (:1916). PIDs are
parsed back out of the `processes_list` row names via `get_pid`.

---

## 6. The pluggable engine/runner managers

CellBlender ships a self-contained plugin system in two sibling packages with identical
structure: each *subdirectory* containing an `__init__.py` is an engine (or runner) module.

### Engines — `cellblender/sim_engine_manager/`
`__init__.py:31` `get_modules()` scans the package directory and `importlib.import_module`s
every subfolder that has an `__init__.py` (:57-72), returning the module objects. Modules
present:

> **Blender add-on rule — an add-on must not mutate `sys.path`.** Discovery imports each
> plugin with a *relative* `importlib.import_module(f'.{f}', package=__package__)`
> (`sim_engine_manager/__init__.py:58`), which resolves inside the package and needs no
> path manipulation. Blender explicitly forbids add-ons/extensions from appending to
> `sys.path`: it pollutes the shared interpreter and breaks extension isolation. Earlier
> versions of both `get_modules()` here **and** `data_plotters.find_plotting_options()`
> (doc 05 §6) appended their package directory to `sys.path` before importing; those blocks
> were redundant given the relative import and were removed in commit `90fe1f3`.

| Dir | `plug_code` | `plug_name` |
|-----|-------------|-------------|
| `mcell3/` | `MCELL3` | MCell 3 with Dynamic Geometry |
| `mcell3dm/` | `MCELL3DM` | MCell 3 via Data Model |
| `mcell3r/` | `MCELLR` | MCell Rules (BioNetGen/MCell3R) |
| `limited_cpp/` | `LIM_CPP` | Prototype C++ Simulation |
| `limited_python/` | (proto) | pure-Python prototype |
| `cBNGL/`, `smoldyn248/`, `Proto_Andreas_1/` | … | other prototypes |

`sim_engine_manager/__init__.py` also hosts the **sweep utilities** shared across all run
paths: `build_sweep_list` (:84), `count_sweep_runs` (:150), `build_sweep_layout` (:157),
`write_sweep_list_to_layout_file` (:169), `write_default_data_layout` (:190), and
`makedirs_exist_ok` (:203).

**Engine module contract** (duck-typed via `dir(module)`): module-level `plug_code`,
`plug_name`, optional `plug_active`; and one of the export functions
`prepare_runs_no_data_model(project_dir)`,
`prepare_runs_data_model_no_geom(dm, project_dir)`, or
`prepare_runs_data_model_full(dm, project_dir)` returning a list of run commands
(e.g. `mcell3r/__init__.py:135`). Optional: `register_blender_classes` /
`unregister_blender_classes`, `parameter_dictionary` + `parameter_layout` (for auto-built
option UI, §7), `draw_layout`, `get_progress_message_and_status`, `postprocess_runs`.

### Runners — `cellblender/sim_runner_manager/`
Same `get_modules()` mechanism (`__init__.py:30`), but it **skips `queue_local`** in the
scan (:57-58) — that runner is imported/used directly rather than as a discovered plugin.
Runner dirs: `queue_local/` (`QUEUE_LOCAL`, "Local Queue"), `command_line/`, `java/`,
`open_gl/`, `portable_batch_system/`, `sun_grid_engine/`, `sun_grid_engine_simple/`.

**Runner module contract:** `plug_code`/`plug_name`; and either
`run_engine(engine_module, dm, project_dir)` (runner drives the engine itself) **or**
`run_commands(command_list)` (runner executes the commands the engine prepared,
e.g. `queue_local/__init__.py:229`). Optional `get_pid`, `register_blender_classes`, etc.

### How a module becomes "active" — `Pluggable` (`cellblender_simulation.py:3288`)
`scene.mcell.sim_engines` and `scene.mcell.sim_runners` are both `Pluggable` groups. Their
`engines_enum` / `runners_enum` EnumProperties are populated by `get_engines_as_items`
(:3006) / `get_runners_as_items` (:3019), which call `load_plug_modules` (:2999) to lazily
fill `sim_engine_manager.plug_modules` / `sim_runner_manager.plug_modules` once.

On selection change, `plugs_changed_callback` (:3303) runs: it `unregister_blender_classes`
on the previously active module, finds the module whose `plug_code` matches the enum,
sets the **module-global** `active_engine_module` / `active_runner_module`
(`cellblender_simulation.py:2991-2992`), calls its `register_blender_classes`, and rebuilds
the option UI from its `parameter_dictionary` (§7). `PLUGGABLE_OT_Reload` (:3034) clears the
caches to force a rescan.

### The `DYNAMIC` run path — `MCELL_OT_run_simulation_dynamic`
`cellblender_simulation.py:1484`. This is where the engine/runner abstraction is actually
exercised (:1562-1589):

```
if 'run_engine' in active_runner_module:        # runner owns the whole run
    dm = build_data_model_from_properties(...full...)
    active_runner_module.run_engine(active_engine_module, dm, project_dir)
else:                                            # engine prepares, runner runs
    command_list = active_engine_module.prepare_runs_*(...)   # picks the richest available
    if   'run_commands'     in active_runner_module: active_runner_module.run_commands(command_list)
    elif 'run_simulations'  in active_engine_module: active_engine_module.run_simulations(command_list)
    elif 'run_simulation'   in active_engine_module: active_engine_module.run_simulation(dm, project_dir)
```

It validates that an engine and runner are selected and that the engine exposes a
`prepare_runs_*` function before doing anything (:1513-1523), and writes the default
`data_layout.json` first (:1557).

---

## 7. Auto-generated plugin option UI

Each plugin can expose a `parameter_dictionary` (`{name: {'val': <int|float|bool|str|callable>, 'icon':…, 'as':'filename'}}`)
and a `parameter_layout` (rows of keys). `plugs_changed_callback` mirrors that dictionary
into a `CollectionProperty` of `PluggableValue` (`cellblender_simulation.py:3169`), typing
each entry `i/f/b/s/fn/F` (the last = a button that calls back into the plugin)
(:3373-3403). `Pluggable.draw_panel` (:3413) then renders the controls, and
`PLUGGABLE_OT_User` (:3088) invokes the plugin's callbacks
(`active_*_module.parameter_dictionary[name]['val']()`). This lets an engine/runner ship its
own settings panel with **no Blender registration code** of its own.

---

## 8. The MCell4 hook — `cellblender/mcell4/`

A single file, `cellblender/mcell4/__init__.py`. Its one function
`convert_data_model_to_python(mcell_binary, dm_file, sweep_item_path, base_name, bng_mode)`
(:26) locates the sibling `bin/data_model_to_pymcell` converter next to the MCell binary and
runs it (`<conv> dm.json -o base_name [-b]`) to emit MCell4 Python (:30-40). Returns `''`
on success or the decoded stderr on failure. Invoked from the sweep-queue export step
(`cellblender_simulation.py:891`). The resulting `*_model.py` is then run as
`python model.py -seed N` (§4 step 7).

> **Generated `model.py` guards its execution block with
> `if __name__ != '__mp_main__':`.** The converter emits the final
> initialization/execution block wrapped in this guard so that a
> `multiprocessing` **spawn** child — which re-imports `model.py` under
> `__name__ == '__mp_main__'` — does not re-run the simulation. Without it, a
> model whose `customization.py` `custom_init_and_run` launches subprocesses
> (e.g. coupling MCell to NEURON over a `mp.Pipe`) recurses: each spawn child
> re-executes the block, re-enters `custom_init_and_run`, and spawns again.
> The guard uses `!= '__mp_main__'` (not `== '__main__'`) so both direct
> execution (`'__main__'`) and MCell's checkpoint resume — which
> `exec_module`s `model.py` under the module name `'model'` — still run. This
> is a property of the **converter**, which lives in the *mcell* repo, not the
> CellBlender add-on: `mcell/utils/data_model_to_pymcell/mcell4_generator.cpp`
> (the "initialization and execution" section emitted by
> `MCell4Generator::generate_model`). See the *mcell* codebase wiki
> (`05_mcell_python_api_and_build.md`, §8 pointers) for the generator's source
> map. `fork` (Linux default) copies memory instead of re-importing, so the
> bug does not manifest there.

**MCell3 vs MCell4 in one line:** MCell3 exports **MDL** and runs the `mcell` binary
directly; MCell4 exports a **Python script** (via `data_model_to_pymcell`) and runs it under
the CellBlender Python interpreter with `MCELL_PATH` set. The switch is the
`mcell4_mode` preference (`cellblender_preferences.py:448`). NFsim/MCell3R is a third,
MCell3-only branch (MDLR → MDL → `mcell3r.py`).

---

## 9. Legacy engines — `cellblender/old_sim_engines/`

Pre-plugin prototypes kept for reference, **not** wired into the current run paths:
`old_sim_engines/pure_python/` (`pure_python_sim.py` — a toy pure-Python diffusion sim),
`old_sim_engines/libMCell/` (a C/C++/SWIG `libMCell` experiment with `mcell_main.*`,
JSON data-model glue, pipe-control variants), and `old_sim_engines/mcell/`. Treat these as
historical; the live equivalents are under `sim_engine_manager/` (`limited_python`,
`limited_cpp`, `mcell3*`).

---

## 10. BioNetGen / SBML import — `cellblender/bng/`

This package imports *external* reaction-network models into CellBlender's data model
(separate from running a simulation, but it's how rule-based / SBML models enter the tool).

### Entry operators (`bng/__init__.py`)
- **`bng.import_data`** (`ImportBioNetGenData`, :19) — file selector for `*.bngl` / `*.xml`.
  `execute` (:37) branches on extension:
  - **`.bngl`** → `bng_operators.execute_bionetgen(filepath, context)` (:45).
  - **`.xml` (SBML)** → `sbml_operators.execute_sbml2blender` (geometry) +
    `execute_sbml2mcell` (network) (:54-57).
  Then it populates the model by invoking the `external.*` operators in order:
  `parameter_add`, `molecule_add`, `reaction_add`, `release_site_add`, and (SBML only)
  `reaction_output_add` (:62-73). For SBML with `<listOfCompartments>` but no spatial
  geometry, it synthesizes a CBNGL compartment block and builds meshes via
  `bngl_to_data_model.read_data_model_from_bngl_text` (:81-198).
- **`cbngl.import_data`** (`ImportCBNGL`, :200) — imports a Compartmental-BNGL file by
  building a **full** data model directly with
  `bngl_to_data_model.read_data_model_from_bngl_file` (:217), upgrading it, applying it via
  `build_properties_from_data_model`, and forcing `mcell4_mode = True` (:218-221).

### Running BNG — `bng/bng_operators.py`
`execute_bionetgen(filepath, context)` (:17) locates `BNG2.pl` (preference
`bionetgen_location`, else a bundled `extensions/.../bng2/BNG2.pl`, else a 20-level
directory walk) and runs it via `subprocess.call([bngpath, "--outdir", destpath, filepath])`
(:30/:39/:68). BNG writes a `<file>.json` (and network files) into the `bng/` dir.

### SBML path — `bng/sbml_operators.py`, `sbml2json.py`, `sbml2blender.py`
`execute_sbml2mcell` (:11) shells out to `sbml2json.py` (`subprocess.call([python, sbml2json.py, -i, filepath])`)
to turn SBML into the same `.json` reaction-network format; `execute_sbml2blender` (:25)
calls `sbml2blender.sbml2blender(...)` to pull spatial geometry into Blender. There's a
PyInstaller spec (`sbml2json.spec`) and a bundled `pyinstaller2.zip` for shipping the
SBML converter as a standalone.

### Loading the network into the data model
- `bng/external_operators.py` — the `external.*` operators. `accessFile(filePath, op)`
  (:16) reads the produced `<filePath>.json` once (cached on the function), then each
  operator (`EXTERNAL_OT_parameter_add` :30, `_molecule_add` :69, `_reaction_add` :128,
  `_release_site_add` :165, `_reaction_output_add` :206) copies its slice
  (`par_list`, molecule/reaction/release lists) into the corresponding CellBlender
  PropertyGroups. This is the **JSON-bridge** import route (BNGL/SBML → `.json` → data
  model).
- `bng/bngl_to_data_model.py` — the **direct** route: `read_data_model_from_bngl_file`
  (:1510) uses `BNGSim.BNGModel` (which itself calls `BNG2.pl` to produce XML/`.net`) and
  `read_data_model_from_bngsim` (:1139) to assemble a complete data model; on failure it
  falls back to `read_data_model_from_bngl_text` (:621), a self-contained BNGL text parser
  (:1521-1527). `BNGSim/` and `treelib3/` are vendored support libraries.
- `bng/net.py` is a very large (~300 KB) vendored module of parsed-network data/helpers used
  along the BNG path.

**Gotchas (BNG/SBML):**
- BNG and SBML conversion run **external** tools (`BNG2.pl` needs Perl; `sbml2json.py`
  needs `libsbml`). Failures surface as `accessFile` reporting "could not be imported"
  (`external_operators.py:21-26`) — i.e. a missing `.json` is the symptom of a converter
  that never ran.
- The two import routes produce different results: the `external.*`/JSON bridge **adds**
  parameters/molecules/reactions to the current model, whereas `cbngl.import_data`
  **replaces** the model and flips it into MCell4 mode.

---

## 11. Key files & symbols

| File | Role |
|------|------|
| `cellblender/cellblender_simulation.py` | All run operators, run-settings PropertyGroup, `Pluggable` engine/runner selection, plugin loading. |
| `cellblender/sim_runner_queue.py` | `SimQueue`, `OutputQueue` — threaded job queue + output capture. |
| `cellblender/run_wrapper.py` | Per-job subprocess shim launched by `SimQueue`. |
| `cellblender/run_simulations.py` | Legacy multiprocessing-pool MDL launcher (COMMAND path). |
| `cellblender/sim_engine_manager/` | Engine plugins + shared sweep/data-layout utilities. |
| `cellblender/sim_runner_manager/` | Runner plugins (local queue, SGE, PBS, …). |
| `cellblender/mcell4/__init__.py` | `convert_data_model_to_python` — MCell4 export hook. |
| `cellblender/old_sim_engines/` | Historical pre-plugin engines (not wired in). |
| `cellblender/bng/` | BioNetGen / SBML / CBNGL import into the data model. |

---

*Part of the CellBlender codebase wiki — see 00_overview.md.*
