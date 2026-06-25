# 04 · The parameter system (expressions, dependencies & sweeps)

> Audience: developers touching *any* numeric field in CellBlender — reaction rates,
> diffusion constants, release counts, geometry coordinates, iterations, time steps.
> All of those are parameter-backed. This is the authoritative reference for how
> expressions, the dependency graph, evaluation order, units, validation, sweeps,
> and data-model serialization work. Other domain docs should point here.

The whole subsystem lives in two files:

| File | Role |
|------|------|
| `cellblender/parameter_system.py` (~3290 lines) | The live system. Defines all PropertyGroups, operators, the expression parser/evaluator, the dependency graph and the panel UI. |
| `cellblender/ParameterSpace.py` (~989 lines) | **Legacy / dead code.** A standalone, Blender-independent re-implementation of the same idea. It is *not* imported anywhere live (its only reference is a commented-out import in `cellblender/object_surface_regions.py:37`) and it cannot even load under Python 3.13 because it does `import parser` / `import symbol` (`cellblender/ParameterSpace.py:4,6`), modules removed in Python 3.10+. Documented at the end for historical context. |

---

## 1. Two kinds of parameters

CellBlender distinguishes **general parameters** from **panel parameters**. This split is the
single most important concept in the subsystem.

### General parameters (`g#`)
User-named, user-created variables shown in the "Model Parameters" list. Each has a name,
an expression, units and a description. They may reference *other* general parameters in
their expressions, forming a dependency graph. Example: `vol = 4/3 * PI * r^3`.

- Stored in the **`gp_dict`** ID-property dictionary on the parameter system, keyed by `g1`, `g2`, …
- Mirrored by a Blender `CollectionProperty` (`general_parameter_list`) of `ParameterMappingProperty`
  items that hold only the `par_id` string (`cellblender/parameter_system.py:1141-1143,1186`).

### Panel parameters (`p#`)
The numeric fields scattered throughout the UI (diffusion constant, rate, count, x/y/z
location, …). Each such field can hold either a literal number *or an expression* that
references general parameters. They are **leaves** in the dependency graph: nothing can
depend on a panel parameter (they have no user-facing name) — see the note at
`cellblender/parameter_system.py:2669` ("Panel Parameters cannot be referenced in expressions").

- Stored in the **`panel_parameter_list`** `CollectionProperty` of `PanelParameterData`
  items, keyed by `p1`, `p2`, … (`cellblender/parameter_system.py:1187`).
- Each embedding PropertyGroup holds only a tiny `Parameter_Reference` whose single string
  field `unique_static_name` is the `p#` key (see §4).

```
ParameterSystemPropertyGroup  (mcell.parameter_system)
 ├─ general_parameter_list : Collection<ParameterMappingProperty>   # par_id strings "g#"
 ├─ panel_parameter_list   : Collection<PanelParameterData>         # keyed "p#"
 ├─ ['gp_dict']            : ID dict  { "g#": {name,expr,elist,units,desc,deps,status,...} }
 └─ ['gp_ordered_list']    : ID list  [ "g#", ... ] in dependency order
```

The system is mounted on the master MCell group as
`parameter_system: PointerProperty(type=ParameterSystemPropertyGroup)` at
`cellblender/cellblender_main.py:929`, reachable everywhere as
`bpy.context.scene.mcell.parameter_system`.

---

## 2. RNA properties vs. ID properties — the performance hack

> **Gotcha #1 — the central design tension.** Blender RNA properties
> (`StringProperty`, `CollectionProperty`, …) are slow to create in bulk and were the
> primary performance bottleneck. The whole module is structured around *minimizing* the
> number of RNA properties by storing the real per-parameter data in **ID properties**
> (`self['gp_dict']`, `self['gp_ordered_list']`, and the dynamic keys on each item)
> instead. See the long design comment at `cellblender/parameter_system.py:1146-1179`.

Consequences a maintainer must keep in mind:

- `gp_dict` and `gp_ordered_list` are *not* declared as RNA properties; they are created
  lazily by `init_parameter_system()` (`cellblender/parameter_system.py:1507-1512`). Nearly
  every method calls `init_parameter_system()` defensively before touching them.
- Per-parameter fields (`name`, `expr`, `elist`, `value`, `units`, `desc`, `status`,
  `who_i_depend_on`, `who_depends_on_me`, `what_depends_on_me`, optionally `sweep_expr` /
  `sweep_enabled`) are *dictionary keys on an IDPropertyGroup*, created in
  `new_general_parameter()` (`cellblender/parameter_system.py:1412-1438`). They are not RNA
  attributes — you access them as `self['gp_dict']['g3']['expr']`.
- **Sets are not storable as ID properties**, so "sets" are emulated as dicts whose values
  are all `True` (`who_i_depend_on`, `status`, etc.) — explicit comments at lines 1429-1432
  and 1881/1884-1885.
- **Booleans become integers** when round-tripped through ID properties; `sweep_enabled` is
  read back with `!= 0` everywhere (e.g. `cellblender/parameter_system.py:1264,1304,1773`).

### The "active_*" editing mirror
The list UI appears to edit a selected collection item, but it is actually editing a single
fixed set of RNA `StringProperty`/`IntProperty` slots on the group:
`active_par_index`, `active_name`, `active_elist`, `active_expr`, `active_units`,
`active_desc`, `active_sweep_expr`, `active_sweep_enabled`, plus `last_selected_id`
(`cellblender/parameter_system.py:1196-1204`).

- Selecting a row fires `update_parameter_index()` which **copies the chosen `gp_dict[g#]`
  fields into the `active_*` slots** and records `last_selected_id`
  (`cellblender/parameter_system.py:1756-1787`).
- Editing any `active_*` slot fires its `update=` callback (e.g.
  `update_parameter_expression`), which **writes the change back into
  `gp_dict[last_selected_id]`** and re-evaluates
  (`cellblender/parameter_system.py:1903-1924`).
- Each external callback is a tiny module-level function (Blender's `update=` cannot take a
  bound method) that just calls the same-named method and stamps
  `last_parameter_update_time` (`cellblender/parameter_system.py:1093-1128`).

---

## 3. Expressions: parsing, the "elist", and evaluation

### 3.1 The encoded expression list ("elist")
An expression is never stored only as a string. It is parsed into a **token list** in which:

- **integers** are general-parameter IDs (the number after the `g`),
- **strings** are verbatim operators / literals / function names,
- **`None`** is a sentinel placed *immediately before* an undefined name.

Full spec with examples is in the docstring at `cellblender/parameter_system.py:2650-2670`.
Example: with `a→g1`, `b→g2`, `c` undefined, `"a + 5 + b + c"` becomes
`[1, '+', '5', '+', 2, '+', None, 'c']`.

This list is **pickled** (protocol 0, latin-1 decoded) into the string field `elist` so it
survives as an ID/RNA string property
(`pickle.dumps(...,protocol=0).decode('latin1')`, e.g. line 1665, 689). Watch for this
encode/decode dance everywhere: `pickle.loads(x.encode('latin1'))`.

### 3.2 Parser — `parse_param_expr()` (AST based)
`cellblender/parameter_system.py:3088-3190`. Two parsers exist; the live one uses Python's
`ast` module (the older `parser`-module version above it is commented out at lines 3036-3084).

- `ast.parse(param_expr)` builds a tree; a nested `format_node()` walks it and converts each
  node to elist tokens. Parenthesization is re-emitted for `BinOp`/`UnaryOp`; operators map
  to strings (`Add→'+'`, `Pow→'**'`, `BitXor→'^'`, …).
- A `Name` node is resolved in priority order (`cellblender/parameter_system.py:3151-3163`):
  function keyword → `name '('`; expression keyword → the name; **a known general parameter
  → its integer ID** (`int(self.general_parameter_list[name]['par_id'][1:])`); otherwise →
  `[None, name]` (undefined sentinel + the literal name).
- A syntax error is caught and printed, returning `None`
  (`cellblender/parameter_system.py:3179-3182`). Callers treat `None` (or `None` *inside* the
  list) as "invalid / undefined".

### 3.3 Keywords & functions
`get_expression_keywords()` (`cellblender/parameter_system.py:2678-2680`) maps MDL-style
tokens to Python: `^→**`, `SQRT→sqrt`, `PI→pi`, `RAND_UNIFORM→0`, `RAND_GAUSSIAN→0`,
`SEED→1`, etc. `get_func_keywords()` (line 2683-2685) is the function subset. `from math
import *` and `from random import uniform, gauss` at the top (lines 61-62) supply the names
that `eval` will see. A large list of reserved MDL keywords is in `get_mdl_keywords()`
(line 2689) to avoid naming collisions.

### 3.4 Building back to a string — `build_expression()`
`cellblender/parameter_system.py:2972-3005`. The inverse of the parser: walks an elist and
emits either an MDL expression (`as_python=False`) or a Python expression
(`as_python=True`, applying the keyword map). Integer IDs are replaced by the *current* user
name from `gp_dict` — this is how renaming a parameter automatically rewrites every
expression that references it (§5). A `None` anywhere makes the whole result `None`;
unresolved IDs emit `UNDEFINED_NAME()` = `"   (0*1111111*0)   "` — a string that evaluates
to 0 but is easy to spot (line 2673-2675).

### 3.5 Evaluation
> **Gotcha #2 — `eval()` is used directly on user input.** Values are computed with bare
> Python `eval(py_expr, globals(), gl)` (`cellblender/parameter_system.py:746, 2110, 2173`).
> The globals include everything `from math import *` / `from random import *` pulled in, so
> expressions are effectively arbitrary Python. There is **no sandboxing** — this is a trust
> boundary. A malicious `.blend`/data-model could embed an expression that runs code on load.
> Errors are swallowed with bare `try/except` and the parameter is flagged invalid.

The evaluation dictionary `gl` is built by **`build_eval_dict()`**
(`cellblender/parameter_system.py:2127-2177`): it iterates `gp_ordered_list` **in dependency
order**, evaluates each general parameter, stores `par['value']`, and inserts
`gl[par_name] = value` so later parameters can reference it. Because the order is
topological, every dependency is already in `gl` by the time a dependent is evaluated.

- `evaluate_all_gp_expressions()` (line 2082) does the same to populate general-parameter
  values.
- `evaluate_all_pp_expressions()` (line 2115) then evaluates *every panel parameter* by
  calling `PanelParameterData.update_panel_expression(context, gl)` with the shared `gl`
  (line 2124) — passing `gl` in avoids rebuilding the whole general-parameter dict per panel
  field.

---

## 4. The reference scheme: how other domains embed a parameter field

Domains never store a number directly when it should be parameter-aware. They store a
`Parameter_Reference` `PointerProperty` (`cellblender/parameter_system.py:772-775`). It has
**exactly one** field, `unique_static_name` (= the `p#` key), and the code comment warns
*not to add any more* (line 774).

Typical embedding (molecules):

```python
# cellblender/cellblender_molecules.py:891
diffusion_constant: PointerProperty(name="...", type=parameter_system.Parameter_Reference)
# ...initialized once:
# cellblender/cellblender_molecules.py:980
self.diffusion_constant.init_ref(parameter_system, user_name="Diffusion Constant",
                                 user_expr="0", user_units="cm^2/sec", user_descr=helptext)
```

The `Parameter_Reference` API (all in `parameter_system.py`):

| Method | Lines | Purpose |
|--------|-------|---------|
| `init_ref(ps, user_name, user_expr, user_descr, user_units, user_int)` | 795-860 | Allocate a `p#` (`allocate_available_pid`), add a `PanelParameterData` to `panel_parameter_list`, set its `expr`/`user_name`/`user_type`/`user_units`/`user_descr`, and eval the initial value. Idempotent: re-uses an existing `unique_static_name`. |
| `clear_ref(ps)` | 878-898 | Remove the panel param; first un-register itself from every general parameter's `what_depends_on_me`, then remove the collection item. Must be called explicitly on delete — ID props don't self-clean. |
| `set_expr(expr)` / `get_expr()` | 928-940 | Get/set the expression string. |
| `get_value()` | 943-964 | Return the numeric value (`float` or `int` per `user_type`). |
| `get_as_string_or_value(as_expr)` | 967-980 | Return either the expression or a `%g`-formatted number. |
| `draw(layout, ps, label)` / `draw_prop_only(col, ps)` | 988-1080 | Draw the field (one- or two-line mode), value readout, validity icon, and optional help box. |

Domains call `ref.get_value()` at simulation/export time, `ref.get_expr()` when serializing
to a data model, and `ref.set_expr(...)` when loading one (see molecule example:
`cellblender/cellblender_molecules.py:1236, 1395`). Other embedders include
`cellblender_reactions.py`, `cellblender_release.py`, `cellblender_initialization.py`,
`cellblender_surface_classes.py`, `cellblender_reaction_output.py`, `cellblender_mol_viz.py`,
`cellblender_simulation.py`.

### `PanelParameterData.update_panel_expression()`
`cellblender/parameter_system.py:675-758` — the heart of a panel field's update. When `expr`
changes (its `update=` callback, line 654-655):
1. re-parse to an elist and re-pickle into `self.elist` (line 688-689);
2. flag invalid if the elist is `None` or contains `None` (lines 692-700);
3. **diff old vs new dependencies** and update each referenced general parameter's
   `what_depends_on_me[self.name]` set (lines 704-726) — this is how a general parameter
   knows which panel fields to refresh when it changes;
4. build/eval the Python expression, storing `self['value']` and `self['valid']`
   (lines 731-755).

---

## 5. The dependency graph, ordering & cycle detection

Each general parameter tracks three "set-as-dict" relations
(`cellblender/parameter_system.py:1429-1431`):

| Key | Meaning |
|-----|---------|
| `who_i_depend_on` | general params (`g#`) this expression references |
| `who_depends_on_me` | general params that reference *this* one |
| `what_depends_on_me` | **panel** params (`p#`) that reference this one |

These are maintained incrementally in `update_expr_list_by_id()`
(`cellblender/parameter_system.py:2006-2073`): it re-parses the expression, recomputes
`who_i_depend_on`, and adds/removes itself from the referenced parameters'
`who_depends_on_me` via set differences (`remove_me_from` / `add_me_to`, lines 2058-2068).
Panel-side edits do the symmetric thing to `what_depends_on_me` (§4).

### Topological ordering — `update_dependency_ordered_name_list()`
`cellblender/parameter_system.py:2181-2247`. Produces `gp_ordered_list` (a dependency order)
by repeated passes (Kahn-style): a parameter joins the ordered list once **all** of its
`who_i_depend_on` are already in the defined set (lines 2222-2229). It first reconciles the
ordered list with the dictionary (adds missing, drops stale, asserts equal length, lines
2194-2208).

> **Cycle detection.** If a full pass adds nothing, a `double_check_count` is incremented;
> once it exceeds the parameter count, the remaining un-orderable set is **returned** as the
> cycle members (lines 2236-2243). Callers flag those with `status['loop']`.

### Orchestration — `update_all_parameters()`
`cellblender/parameter_system.py:1875-1900`:
1. clear each `status`; mark `'undef'` for any elist containing `None` (sets the global
   `self['undefined']` flag);
2. call the topological sort; if it returns a non-empty set, mark those `status['loop']`;
3. otherwise evaluate all general then all panel expressions.

> **Gotcha #3 — recompute cost.** `update_all_parameters` re-statuses *every* parameter,
> re-runs the full topological sort, and re-evaluates *every* general and *every* panel
> parameter on essentially any edit. It is explicitly called out as slow (e.g. the comment
> "This one takes a long time" at `cellblender/parameter_system.py:1674`, and the warning
> that re-evaluating all GPs per PP is "very inefficient" at line 2122). Bulk loads go
> through `add_general_parameters_from_list()` (line 1600-1681), which batches: create all
> entries first, parse all elists, then a single `update_all_parameters`.

### Renaming propagation — `update_parameter_name()`
`cellblender/parameter_system.py:1790-1873`. Because expressions store integer IDs, a rename
only changes `gp_dict[pid]['name']`; then for every dependent it rebuilds the displayed
expression string via `build_expression(elist)` (general deps at line 1834, panel deps at
1858) so all referencing expressions show the new name. There is also special handling to
re-resolve previously-`undefined` references when a matching name appears (lines 1836-1853).

---

## 6. Validation, error states & UI highlighting

Two error states, stored in each parameter's `status` dict:

- **`undef`** — an elist contains `None` (an unresolved name). Highest priority.
- **`loop`** — the parameter is part of a circular reference.

Display:
- The general-parameter list row (`MCELL_UL_draw_parameter.draw_item`,
  `cellblender/parameter_system.py:567-617`) shows `CHECKMARK` normally, `ERROR` for undef,
  `LOOP_BACK` for loop; a second column shows sweep status icons
  (`BLANK1`/`DOT`/`FCURVE`).
- The detail layout (`draw_layout`, `cellblender/parameter_system.py:2449-2632`) shows
  banner errors ("Circular References Detected" / "Undefined Values Detected", lines
  2467-2473) and, for the selected parameter, the specific undefined names extracted from the
  elist (lines 2516-2526).
- Panel fields show an `ERROR` icon and `"??"` value when `valid` is false or the value is
  `None` (`Parameter_Reference.draw`, lines 994-1010).

**Units** are purely descriptive metadata (`units`/`user_units`): stored, serialized, and
shown in the help box (e.g. `cellblender/parameter_system.py:1043-1044`), but never used in
computation. `user_type` (`'f'`/`'i'`) controls float-vs-int *display/return*, not storage —
values are kept as full floats (note at lines 756-758).

---

## 7. Data-model serialization

The parameter system serializes to the CellBlender data model under the
`'parameter_system'` key (`cellblender/cellblender_main.py:342,1018`).

- **`build_data_model_from_properties()`** (`cellblender/parameter_system.py:1283-1321`)
  emits `{'model_parameters': [ {par_name, par_expression, par_units, par_description,
  [sweep_expression, sweep_enabled], _extras:{par_id_name, par_value, par_valid}} ... ],
  '_extras':{'ordered_id_names': [...]}}`. Note expressions are exported **as strings**
  (`par['expr']`), so the data model is name-based and human-readable.
- **`build_ordered_data_model_from_properties()`** (line 1230-1280) is a variant that emits
  parameters in dependency order (used for MDL export so definitions precede uses); it also
  appends any parameters left out of `gp_ordered_list` because of circular references (lines
  1243-1250).
- **`build_properties_from_data_model()`** (line 1340-1373) clears everything, resets the
  `active_*` mirror, and rebuilds via `add_general_parameters_from_list()`.
- **Versioning:** data-model version is `"DM_2014_10_24_1638"`;
  `upgrade_data_model()` (line 1324-1337) only bumps an unversioned model to that string and
  rejects anything else.

**Panel parameters are *not* serialized by the parameter system.** Each is serialized by its
*owning* domain as a plain string via `ref.get_expr()` and restored via `ref.set_expr()`
(e.g. molecule `diffusion_constant` in `cellblender/cellblender_molecules.py:1236,1395`).
The `Parameter_Reference` / `p#` key itself is transient and re-allocated by `init_ref` on
load — only the expression text persists.

> **Gotcha #4 — `next_pid` is never reset.** `clear_all_parameters()` resets `next_gid` but
> deliberately *not* `next_pid` (`cellblender/parameter_system.py:1379-1381`), because some
> "static" panel parameters (iterations, time step, start seed) must keep their IDs across a
> simulation reset and are owned by other property groups. `allocate_available_pid` also
> never re-uses freed IDs (TODO at line 1405).

---

## 8. Parameter sweeps

A general parameter can carry a **sweep expression** (`sweep_expr`) and a `sweep_enabled`
flag instead of a single value. The sweep expression is a comma-separated list of points and
ranges, e.g. `"0, 2, 9, 10:20, 25:35:5, 50"` (`#` = point, `#:#` = inclusive range step 1,
`#:#:#` = explicit step).

- `runs_in_sweep(sw_item)` (`cellblender/parameter_system.py:2250-2301`) counts the runs in a
  single comma group, handling scalar / 2-part / 3-part forms (with float step and careful
  fence-post correction).
- `count_sweep_runs()` (line 2304-2325) multiplies the run counts of *all* sweep-enabled
  parameters → total number of simulation runs (a Cartesian product across swept dimensions).
- The list UI shows `"<expr>  => N runs"` for swept parameters
  (`MCELL_UL_draw_parameter`, lines 592-594) and toggles between the normal expression field
  and the sweep field based on `active_sweep_enabled` (`draw_layout`, lines 2498-2501).
- Sweep settings round-trip through the data model (`sweep_expression`, `sweep_enabled`,
  lines 1261-1264, 1301-1304) and through the `update_sweep_*` callbacks (lines 1979-2003).

The actual *iteration* over swept values lives in the run/export layer (the simulation
runner consumes `count_sweep_runs()` and the per-parameter sweep expressions), not in this
file.

---

## 9. Operators & UI registration

Registered classes (`cellblender/parameter_system.py:3263-3286`):

| Class | Lines | Role |
|-------|-------|------|
| `MCELL_OT_add_parameter` / `MCELL_OT_remove_parameter` / `MCELL_OT_remove_all_pars` | 515-557 | Add/remove general parameters. Remove refuses if `who_depends_on_me`/`what_depends_on_me` is non-empty, returning a "used by" error (`remove_active_parameter`, lines 1705-1753). |
| `MCELL_OT_add_par_list` | 452-507 | Debug: bulk-generate test parameters. |
| `MCELL_OT_print_gen_parameters` / `print_par_expressions` / `print_pan_parameters` | 288-448 | Console dumps. |
| `MCELL_OT_print_profiling` / `clear_profiling` | 217-285 | Profiling (the `@profile` decorator wraps nearly every method, lines 103-215). |
| `MCELL_UL_draw_parameter` | 567-617 | The parameter list row drawer. |
| `PanelParameterData`, `Parameter_Reference`, `ParameterMappingProperty`, `ParameterSystemPropertyGroup` | 657, 772, 1141, 1181 | The PropertyGroups. |

The main panel is drawn via `ParameterSystemPropertyGroup.draw_panel`/`draw_layout`
(lines 2635-2639, 2449); the standalone `MCELL_PT_parameter_system` panel is commented out
(line 620-639). Helper drawers `draw_prop_with_help`, `draw_operator_with_help`,
`draw_prop_search_with_help`, `draw_label_with_help` (lines 2327-2422) are used by other
panels to render non-parameter properties with the same info-button styling.

---

## 10. `ParameterSpace.py` — the legacy standalone engine

`cellblender/ParameterSpace.py` is a self-contained, Blender-free class that implements the
same concept with plain Python dicts rather than ID properties:

- `name_ID_dict`, `ID_name_dict`, `ID_expr_dict`, `ID_value_dict`, `ID_error_dict`,
  `ID_valid_dict` (`cellblender/ParameterSpace.py:178-184`).
- `define()` / `set_expr()` / `get_expr()` for CRUD (lines 244-342); dependency queries
  `get_dependents_list`, `get_depend_list` (lines 351-399); deletion guarded by dependents
  (`delete`, line 435-443).
- Two evaluators: `eval_all_ordered()` (fixed-point passes, line 572) and
  `eval_all_any_order()` (dependency-driven passes, line 637), both using `exec`/`eval`
  (lines 597-598, 681-682) — same `eval`-safety caveat as the live system.
- Sweep helpers `init_param_space`/`dump` etc.

**It is not wired into the live application.** Its only mention is a commented-out import
(`object_surface_regions.py:37`), and its parser (`parse_param_expr`, line 724) depends on
the removed `parser`/`symbol`/`token` stdlib modules, so it would raise `ModuleNotFoundError`
on import under Python 3.13. Treat it as historical reference / candidate for deletion; the
authoritative implementation is the `ast`-based engine inside `parameter_system.py`.

---

## Quick reference — key call paths

```
User edits a general-parameter expression
  active_expr (update=) → update_parameter_expression           (1903)
    → gp_dict[id]['expr'] = active_expr; evaluate_active_expression (1919/2076)
        → update_expr_list_by_id  → parse_param_expr → elist, fix who_i/who_depends (2006)
    → update_all_parameters                                      (1923/1875)
        → status pass → update_dependency_ordered_name_list (cycle check) (1889/2181)
        → evaluate_all_gp_expressions / evaluate_all_pp_expressions (1899/2082/2115)

User edits a panel field (e.g. diffusion constant)
  PanelParameterData.expr (update=) → update_panel_expression    (654/675)
    → parse_param_expr → elist; diff deps → general 'what_depends_on_me'
    → build_eval_dict (ordered) → eval → self['value'], self['valid']

Domain reads at export/sim time
  ref.get_value()  /  ref.get_expr()                             (943/935)
```

*Part of the CellBlender codebase wiki — see 00_overview.md.*
