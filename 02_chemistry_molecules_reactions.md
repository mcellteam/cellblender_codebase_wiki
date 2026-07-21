# Chemistry: molecules, reactions, release & surface classes

> Audience: developers extending or debugging CellBlender's chemistry model. Scope: how
> molecule species, reaction rules, release/placement, surface classes, the complex-molecule
> builder (MolMaker), and display glyphs are represented as Blender PropertyGroups, edited
> through Operators, drawn into the main panel, and serialized into the CellBlender **data
> model**. For the parameter/expression machinery behind every numeric field see
> `04_*` (parameter_system); for runtime molecule visualization see `07_*` (mol_viz).

All five chemistry subsystems share one architecture (the CellBlender "triad" + serialization):

```
 bpy.context.scene.mcell   (MCellPropertyGroup, cellblender_main.py)
   ├─ .molecules        → MCellMoleculesListProperty        (cellblender_molecules.py)
   ├─ .molmaker         → MCellMolMakerPropertyGroup         (cellblender_molmaker.py)
   ├─ .reactions        → MCellReactionsListProperty         (cellblender_reactions.py)
   ├─ .surface_classes  → MCellSurfaceClassesPropertyGroup   (cellblender_surface_classes.py)
   ├─ .release_sites    → MCellMoleculeReleasePropertyGroup  (cellblender_release.py)
   └─ .release_patterns → MCellReleasePatternPropertyGroup   (cellblender_release.py)
```

These PointerProperties are attached to the scene-level `MCellPropertyGroup` at
`cellblender/cellblender_main.py:930-942`. Each is a **collection (list) PropertyGroup** that
owns a `CollectionProperty` of per-item PropertyGroups, plus an `active_*_index` for the UIList
selection. Molecules are referenced **by name (string)** from reactions, release sites and
surface classes — there are no cross PointerProperties, only name strings resolved at export time.

---

## 1. The shared pattern (read this once, applies to all sections)

Every domain module follows the same five-part recipe:

| Part | Convention | Example (molecules) |
|---|---|---|
| **Item PropertyGroup** | one row of data; defines `init_properties`, `remove_properties`, `build_data_model_from_properties`, `upgrade_data_model` (static), `build_properties_from_data_model` | `MCellMoleculeProperty` `cellblender/cellblender_molecules.py:876` |
| **Collection PropertyGroup** | holds `CollectionProperty` + `active_*_index`; `add_*`/`remove_active_*` helpers; rolls each item's data model into a list dict | `MCellMoleculesListProperty` `cellblender/cellblender_molecules.py:2238` |
| **Operators** | `MCELL_OT_*` add/remove/edit; thin wrappers that call collection helpers | `MCELL_OT_molecule_add` `cellblender/cellblender_molecules.py:177` |
| **UIList** | `MCELL_UL_*` draws each row + status icon | `MCELL_UL_check_molecule` `cellblender/cellblender_molecules.py:1861` |
| **Panel drawing** | `draw_layout(context, layout)` (and a `draw_panel` wrapper) | `cellblender/cellblender_molecules.py:2480` |

**Numeric fields are Parameter-backed.** Diffusion constants, rates, locations, diameters,
quantities, clamp values, train timing — every quantity that can hold a units-bearing math
expression is a `PointerProperty(type=parameter_system.Parameter_Reference)`, not a raw float.
Each is wired up in `init_properties` via `self.<field>.init_ref(parameter_system, user_name=…,
user_expr=…, user_units=…, user_descr=…)` and torn down in `remove_properties` via
`clear_ref(ps)`. Serialization reads the **expression string** with `.get_expr()` and restores
it with `.set_expr()` (see `04_*`). This is why the data model stores `'diffusion_constant':
"0"` (a string), not a number.

**Data model serialization.** `build_data_model_from_properties` returns a plain
dict/list/str/number tree (JSON-friendly) tagged with a `data_model_version` string;
`build_properties_from_data_model` rebuilds the PropertyGroups from such a dict; the static
`upgrade_data_model` migrates old versions forward (or returns `None` and calls
`data_model.flag_incompatible_data_model(...)`). The scene-level `MCellPropertyGroup`
aggregates every subsystem's dict into the single project data model used for save/load and
MDL/MCell4 export.

**Panels.** None of these modules register their own `bpy.types.Panel`. The single CellBlender
main panel (`cellblender_main.py`, `draw_self`) conditionally calls each list group's
`draw_layout` based on which section the user selected — e.g. molecules at
`cellblender/cellblender_main.py:797`, reactions at `:808`, release sites at `:813`, release
patterns at `:818`, surface classes at `:831`. So "the Panel" for each domain is really its
`draw_layout` method invoked by the shared panel.

---

## 2. Molecules — `cellblender_molecules.py`

Defines molecule **species** and their appearance. The species list is the root authority that
reactions, releases, and surface classes refer to by name.

### PropertyGroups

| Class | Role | Location |
|---|---|---|
| `MCellMolComponentProperty` | one BNGL **component** (binding site): `component_name`, `states_string`, `is_key`, and Parameter-backed `loc_x/y/z`, `rot_x/y/z`, `rot_ang`, `rot_index` | `cellblender/cellblender_molecules.py:714` |
| `MCellMoleculeProperty` | one molecule **species** | `cellblender/cellblender_molecules.py:876` |
| `MCellMoleculesListProperty` | the species collection (`molecule_list`, `active_mol_index`, `last_id`) | `cellblender/cellblender_molecules.py:2238` |
| `MCellMolMakerPropertyGroup` is referenced here but lives in `cellblender_molmaker.py` (see §6) | | |

Key `MCellMoleculeProperty` fields (`cellblender/cellblender_molecules.py:876-992`):
- `name` (species name, `update=name_change_callback` at `:408`), `description`, `bnglLabel`.
- `type` enum: `'2D'` = **Surface Molecule**, `'3D'` = **Volume Molecule** (`:883-890`).
- `diffusion_constant`, `custom_time_step`, `custom_space_step`, `maximum_step_length` — all
  `Parameter_Reference` PointerProperties (`:891-904`), initialized at `:972-1001`.
- `target_only`, `export_viz` flags.
- Display: `glyph` enum (Sphere_1, Cone, Cube, …, Letter), `letter` enum, `color`, `alpha`,
  `emit`, `scale` — most carry `update=display_callback`/`shape_change_callback`
  (`:906-957`).
- Complex-molecule layout: `component_list` (CollectionProperty of components), `geom_type`
  enum (Coincident / XYZ,RotRef / XYZ,RotAxis / 2D/3D auto), `component_distance` (`:855-874`).

### Operators (selected)

| `bl_idname` | Action | Location |
|---|---|---|
| `mcell.molecule_add` | add species | `cellblender/cellblender_molecules.py:177` |
| `mcell.molecule_duplicate` | clone active species (round-trips through data model) | `:187` |
| `mcell.molecule_remove` | remove active species | `:197` |
| `mcell.mol_comp_add` / `mcell.mol_comp_remove` | add/remove a component | `:209` / `:220` |
| `mcell.set_molecule_glyph` | apply a library glyph mesh to the selected mol object | `:232` |
| `mcell.mol_comp_stick` / `mcell.mol_comp_nostick` / `mcell.mol_auto_key` | stick-figure / auto-key layout of components | `:257` / `:343` / `:371` |
| `mcell.mol_shade_flat` / `mcell.mol_shade_smooth` / `mcell.molecule_show_all` / `mcell.molecule_hide_all` | display helpers | `:499` / `:516` / `:2152` / `:2178` |

### Glyph / mesh creation

`create_mol_data` (`cellblender/cellblender_molecules.py:1057`) builds the actual Blender mesh
object (`mol_<name>` / `mol_<name>_shape`) for a species, calling
`cellblender_glyphs.get_named_shape(glyph_name, …)` (`:1057` body, imported at `:80`) to obtain
the vertex/face geometry — this is the bridge into §7 (glyphs). `set_mol_glyph`
(`cellblender/cellblender_molecules.py:1743`) swaps the mesh by selecting the mol object and
delegating to the module-level `set_molecule_glyph` (`:94`), which links the glyph mesh from
`glyph_library.blend`.

> **Blender-API note — deleting the old glyph object.** When rebuilding a glyph,
> `create_mol_data` deletes the previous shape object with `bpy.data.objects.remove()`,
> which already unlinks it from *all* collections. The explicit
> `collection.objects.unlink(obj)` that precedes it is only valid when the object is
> actually linked to *that* collection — Blender 4.x/5.x raise
> `RuntimeError: Object '…' not in collection` otherwise — so it is guarded by an
> `obj in scn_objs` membership check at all three call sites
> (`cellblender/cellblender_molecules.py:284, 369, 1097`). Without the guard,
> opening/upgrading an older project under Blender 5.1 aborts the whole
> `build_properties_from_data_model` rebuild.

### Data model

`MCellMoleculeProperty.build_data_model_from_properties`
(`cellblender/cellblender_molecules.py:1247`) emits `mol_name`, `mol_type`, `diffusion_constant`
(expr string), `target_only`, the step fields, a `bngl_component_list`, and a nested `display`
dict (glyph/letter/color/scale). Version tag `DM_2018_10_16_1632`. The list group's
`build_data_model_from_properties` (`:2382`) wraps all species into `molecule_list` **and folds
in the MolMaker dict** (`mol_dm['molmaker'] = molmaker.build_data_model_from_properties()` at
`:2391`). `upgrade_data_model` (`:1293`, `:2396`) chains version migrations. Registration of all
classes is at `cellblender/cellblender_molecules.py:2520-2544`.

> **Gotcha:** `add_molecule` (`:2252`) has a `mol_viz.molecule_read_in` branch that imports
> species names from already-loaded visualization objects (`bpy.data.objects['molecules']`),
> using `dup_check` to skip duplicates — adding a molecule does not always create a fresh blank
> entry. `MCellMoleculeGlyphsPropertyGroup` (`:151`) and its `molecule_glyphs` scene pointer
> (`cellblender/cellblender_main.py:942`) are **commented out**; references to
> `mcell.molecule_glyphs.status`/`.glyph_lib` in `set_molecule_glyph` rely on that group still
> being defined at module top — handle with care when refactoring glyph code.

---

## 3. Reactions — `cellblender_reactions.py`

Reaction **rules** between named molecule species.

### PropertyGroups

| Class | Role | Location |
|---|---|---|
| `MCellReactionProperty` | one reaction rule | `cellblender/cellblender_reactions.py:300` |
| `RxnStringProperty` | generic name-string holder for collections | `:528` |
| `MCellReactionsListProperty` | `reaction_list` + `reaction_name_list` + `active_rxn_index` | `:537` |

`MCellReactionProperty` fields (`:300-349`):
- `reactants` / `products`: **strings** of `+`-separated species names; reactants may end with
  `@ surface_class` (`:308-316`). This is the cross-reference into molecules — species are named,
  not pointer-linked.
- `type` enum: `'irreversible'` (`->`) or `'reversible'` (`<->`) (`:317-324`).
- `fwd_rate`, `bkwd_rate`: `Parameter_Reference` PointerProperties (`:337-338`); units depend on
  uni/bimolecular and vol/surf (documented in the helptext at `:362-376`).
- Variable rate: `variable_rate_switch`, `variable_rate` (FILE_PATH), `variable_rate_valid`
  (`:325-333`); the operator `mcell.variable_rate_add` (`:72`) loads a two-column time/rate file.

### Operators & validation

`mcell.reaction_add` (`:49`), `mcell.reaction_remove` (`:60`), `mcell.variable_rate_add` (`:72`).
The `check_reaction` callback (`cellblender/cellblender_reactions.py:106`) fires on every edit:
it reformats reactant/product strings (adds spaces around `+` and `@` unless in BioNetGen mode),
builds the canonical `rxn.name = "reactants type products"` (`:146`), and flags duplicate
reactions (`:148`).

### Data model

`MCellReactionProperty.build_data_model_from_properties`
(`cellblender/cellblender_reactions.py:386`) emits `reactants`, `products`, `rxn_type`,
`fwd_rate`/`bkwd_rate` (expr strings via `.get_expr()`), and — for irreversible reactions with a
valid variable rate — the inlined `variable_rate_text` (`:401-406`). Version `DM_2018_01_11_1330`.
The list group rolls these into `reaction_list` at `:567`. Registration at `:754`.

> **Gotcha:** removing the last reaction calls
> `cellblender_release.update_release_pattern_rxn_name_list()` (`:564`) — reactions and the
> release-pattern name list are coupled.

---

## 4. Release / placement — `cellblender_release.py`

Where and how molecules are **placed/released** into the simulation, plus timed **release
patterns**. Two independent collection groups live here.

### Release sites

| Class | Role | Location |
|---|---|---|
| `MCellPointItemPropertyGroup` | one XYZ point (for LIST releases) | `cellblender/cellblender_release.py:250` |
| `MCellMoleculeReleaseProperty` | one release site | `:363` |
| `MCellMoleculeReleasePropertyGroup` | site collection (`mol_release_list`, `active_release_index`) | `:586` |

`MCellMoleculeReleaseProperty` fields (`:363-420`):
- `molecule`: **string** naming the species to release (cross-reference into §2),
  `update=check_release_site`.
- `shape` enum: `CUBIC`, `SPHERICAL`, `SPHERICAL_SHELL`, `LIST`, `OBJECT` (Object/Region) — surface
  molecules can only use Object/Region (`:373-382`).
- `orient` enum (`'` / `,` / `;` = Top Front / Top Back / Mixed) for surface releases (`:383-390`).
- `object_expr`: object/region expression for OBJECT shape.
- Parameter-backed `location_x/y/z`, `diameter`, `probability`, `quantity`, `stddev`
  (`:396-414`).
- `quantity_type` enum: `NUMBER_TO_RELEASE` / `GAUSSIAN_RELEASE_NUMBER` / `DENSITY` (`:406-411`).
- `points_list` (CollectionProperty of points) for LIST releases; `pattern`: name of a release
  pattern (cross-reference into §4 patterns).

Point operators: `mcellptlist.point_add` (`:259`), `…point_add_cursor` (`:271`),
`…point_add_obj_sel` (add selected vertices from an object, `:284`), `…point_remove` (`:325`),
`…point_remove_all` (`:336`). Site operators: `mcell.release_site_add` (`:59`),
`mcell.release_site_remove` (`:70`).

Data model: per-site dict at `cellblender/cellblender_release.py:502` (`molecule`, `shape`,
`orient`, `object_expr`, location/diameter/probability/quantity/stddev expr strings,
`quantity_type`, `pattern`, and a nested `points_list`), version `DM_2018_01_11_1330`; the group
rolls them at `:651`.

### Release patterns

| Class | Role | Location |
|---|---|---|
| `MCellReleasePatternProperty` | one timed pattern | `cellblender/cellblender_release.py:1005` |
| `RelStringProperty` | name-string holder | `:1098` |
| `MCellReleasePatternPropertyGroup` | pattern collection | `:1107` |

Pattern fields are all Parameter-backed: `delay`, `release_interval`, `train_duration`,
`train_interval`, `number_of_trains` (`:1012-1016`, init at `:1023-1030`). Data model at `:1042`
(version `DM_2018_01_11_1330`), group roll-up at `:1160`. Operators `mcell.release_pattern_add`
(`:917`) / `mcell.release_pattern_remove` (`:928`). A release site's `pattern` string names one
of these patterns; `update_release_pattern_rxn_name_list` keeps the selectable name list current.
Both groups register at `cellblender/cellblender_release.py:1296`.

---

## 5. Surface classes — `cellblender_surface_classes.py`

Defines how molecules behave when they hit a surface. **Three-level** nesting (deeper than the
other domains): a surface class owns a list of property rows, each row affecting some molecules.

| Class | Role | Location |
|---|---|---|
| `MCellSurfaceClassPropertiesProperty` | one rule row (e.g. `ABSORPTIVE = Mol'`) | `cellblender/cellblender_surface_classes.py:226` |
| `MCellSurfaceClassesProperty` | one named surface class owning `surf_class_props_list` | `:349` |
| `MCellSurfaceClassesPropertyGroup` | the class collection (`surf_class_list`, `active_surf_class_index`) | `:441` |

`MCellSurfaceClassPropertiesProperty` fields (`:237-274`):
- `surf_class_type` enum: `ABSORPTIVE` (destroys), `TRANSPARENT` (passes through, default),
  `REFLECTIVE` (bounces), `CLAMP_CONCENTRATION` (`:261-270`).
- `affected_mols` enum: `ALL_MOLECULES` / `ALL_VOLUME_MOLECULES` / `ALL_SURFACE_MOLECULES` /
  `SINGLE` (`:237-245`).
- `molecule`: **string** species name (used when `affected_mols == SINGLE`; cross-reference into
  §2), `update=check_surf_class_props`.
- `surf_class_orient` enum (`'` / `,` / `;` = Top/Front / Bottom/Back / Ignore).
- `clamp_value`: `Parameter_Reference` (only meaningful for CLAMP_CONCENTRATION) (`:272`).

Operators: `mcell.surface_class_add` / `…remove` (`:172` / `:183`) manage classes;
`mcell.surf_class_props_add` / `…remove` (`:150` / `:161`) manage property rows within the active
class — implemented as `add_class`/`remove_active_class`/`add_class_prop`/`remove_class_prop` on
the top group (`:451-500`).

Data model: three nested levels — property row at
`cellblender/cellblender_surface_classes.py:276` (version `DM_2015_11_08_1756`), class at `:378`,
top group at `:504`. Registration at `:713`.

> **Gotcha:** surface classes only *define* behavior; assigning a class to a mesh region is done
> elsewhere (object/region modify; see the geometry doc). The `@ surface_class` suffix in a
> reaction's `reactants` (§3) is how a reaction is scoped to a surface class by name.

---

## 6. MolMaker — `cellblender_molmaker.py`

A construction tool that lays out **complex (multi-molecule, multi-component) structures** in 3D
and converts them to the NAUTY / BNGL string forms MCellR/BioNetGen expect. It is *not* a
separate scene section; its data model is nested inside the molecules dict (§2, `:2357`) and its
PropertyGroup hangs off `scene.mcell.molmaker` (`cellblender/cellblender_main.py:931`).

| Class | Role | Location |
|---|---|---|
| `MolMakerFileNameProperty` | text-name holder for source/loc files | `cellblender/cellblender_molmaker.py:1269` |
| `MolMakerMolCompProperty` | one node in the layout graph: `field_type` (`m`/`c`/`k` = molecule/component/key), `coords`, `graph_string`, `peer_list`, `key_list`, `angle`, `bond_index` | `:1272` |
| `MCellMolMakerPropertyGroup` | the tool state | `:1494` |

Tool state (`:1494-1526`): `molecule_definition` (e.g. `A.B.B.C`), `molcomp_items`
(the parsed graph), flags (`make_materials`, `cellblender_colors`, `show_key_planes`,
`average_coincident`, `axial_rotation`, `bending_rotation`, `dynamic_rotation`), plus
`nauty_string` and `bngl_string` outputs.

Operators: `mol.refresh_mol_def` ("Layout Parts", `:1287`), `mol.chain_mol_defs`
("Chain Molecules", `:1334`), `mol.build_as_is` (`:372`), `mol.rebuild_two_d` / `mol.rebuild_three_d`
(`:1032` / `:1055`), `mol.rebuild_with_cb` ("Build Structure from CellBlender", `:1470`),
`mol.to_nauty` / `mol.to_bngl` (emit the canonical strings, `:1078` / `:1090`),
`mol.purge_by_reopen` (`:1480`), `mol.update_files` (`:140`).

Data model: `build_data_model_from_properties` (`cellblender/cellblender_molmaker.py:1528`,
version `DM_2020_01_10_1930`) serializes the flags and the full `molcomp_list` graph;
`upgrade_data_model` (`:1568`) chains migrations. `draw_layout` at `:1639`. Registration at
`:1943`.

> **Gotcha:** MolMaker's `upgrade_data_model` returns `None` on the two intermediate version
> bumps (`:1581`, `:1589`) even though it mutated `dm` — callers must treat the upgrade as
> in-place rather than relying on the return value here.

---

## 7. Glyphs — `cellblender_glyphs.py`

Pure geometry: the library of mesh shapes used to *draw* each molecule species. No PropertyGroups,
Operators, or panels — it is a procedural mesh factory.

- Base classes `point`, `face`, `plf_object` (point/line/face object), and `plf_object_flat`
  (`cellblender/cellblender_glyphs.py:28-71`, `:706`).
- 3D solids: `Tetrahedron`, `Pyramid`, `BasicBox`, `CellBlender_Octahedron`, `CellBlender_Cube`,
  `CellBlender_Icosahedron`, `CellBlender_Cone`, `CellBlender_Cylinder`, `CellBlender_Torus`,
  `CellBlender_Sphere1`, `CellBlender_Sphere2`, `CellBlender_Receptor` (`:71-578`).
- Flat letters `Letter_A` … `Letter_Z` (`:792-1240`).
- Dispatcher `get_named_shape(glyph_name, size_x, size_y, size_z)`
  (`cellblender/cellblender_glyphs.py:1255`) maps a name to a `plf_object` instance.

**How glyphs attach to molecules:** a species' `glyph` enum (and `letter` enum for `Letter`,
§2 `:915-957`) chooses the shape. `MCellMoleculeProperty.create_mol_data`
(`cellblender/cellblender_molecules.py:1057`) calls `cellblender_glyphs.get_named_shape(...)` to
generate the mesh for the `mol_<name>_shape` object, and the glyph/letter/color/scale are stored
in the species' `display` data-model dict (§2 `:1242-1253`). (The alternative path,
`set_molecule_glyph` at `:94`, links a glyph mesh out of `glyph_library.blend` instead of
generating it procedurally.) Runtime per-frame glyph instancing is the mol_viz subsystem's job —
see `07_*`.

---

## 8. Cross-reference summary & gotchas

- **Everything keys off molecule names (strings), not pointers.** Reactions reference species via
  `reactants`/`products` (`cellblender/cellblender_reactions.py:308-316`); release sites via
  `molecule` (`cellblender/cellblender_release.py:369`); surface classes via `molecule`
  (`cellblender/cellblender_surface_classes.py:248`). Renaming a species does **not** auto-update
  these references — `name_change_callback` (`cellblender/cellblender_molecules.py:416`) handles
  the species' own Blender objects, but downstream string references must be re-validated by each
  domain's `check_*` callback. Because Blender auto-appends `.001` when a rename targets a name
  that is already taken, `name_change_callback` first clears any **stale** datablocks occupying the
  destination `mol_<newname>*` name before renaming onto it (guarded so a genuine, user-created
  duplicate-named species is left untouched). Without that clearing, a data-model upgrade that
  leaves behind old `mol_<name>*` objects produces spurious `mol_<name>_shape.001` duplicates.
- **All numeric chemistry quantities are Parameter-backed** (`Parameter_Reference` PointerProperty
  + `init_ref`/`get_expr`/`set_expr`/`clear_ref`); the data model stores expression *strings*. See
  `04_*`.
- **`@ surface_class` in a reaction** ties reactions (§3) to surface classes (§5) by name.
- **MolMaker rides inside the molecules data model** (`cellblender/cellblender_molecules.py:2391`),
  not under its own top-level key.
- **No per-domain Panel classes** — the shared main panel calls each group's `draw_layout`
  (`cellblender/cellblender_main.py:794-831`).
- **Version-tagged data models** differ per group (`DM_2018_10_16_1632`, `DM_2018_01_11_1330`,
  `DM_2015_11_08_1756`, `DM_2020_01_10_1930`, …); `upgrade_data_model` must be kept in lockstep
  when fields change, or load fails via `data_model.flag_incompatible_data_model`.

*Part of the CellBlender codebase wiki — see 00_overview.md.*
