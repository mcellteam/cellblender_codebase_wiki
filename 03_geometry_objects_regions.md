# 03 — Geometry: Model Objects, Surface Regions, Partitions & Mesh Analysis

> Audience: developers working on CellBlender's geometry subsystem — the bridge between
> actual Blender mesh objects and the MCell model. Covers which meshes are simulated
> (model objects), how named face sets (surface regions) are stored on the mesh and tied
> to surface classes / releases, how partitions bound the simulated world, periodic
> boundary conditions, and what the Meshalyzer validates. Scope: `cellblender_objects.py`,
> `cellblender_surface_regions.py`, `object_surface_regions.py`, `cellblender_partitions.py`,
> `cellblender_pbc.py`, `cellblender_meshalyzer.py`.

## Where this fits

In MCell, geometry *is* the cell: closed triangulated meshes are membranes/compartments,
named subsets of their faces are **surface regions** where surface molecules live and
surface classes act, and a bounding box of **partitions** speeds up the spatial search.
CellBlender stores all of this directly on Blender's own data — `bpy.data.objects`,
their `Mesh` datablocks, and a per-object `mcell` PointerProperty — then serializes it
into the data model at export time.

All five PropertyGroups hang off the scene's `mcell` group or off objects:

| Concept | PropertyGroup | Attached at | Wired in `cellblender_main.py` |
|---|---|---|---|
| Model object list | `MCellModelObjectsPropertyGroup` | `scene.mcell.model_objects` | `cellblender_main.py:937` |
| Per-object regions | `MCellObjectPropertyGroup` (holds `regions`, `include`) | `object.mcell` | `__init__.py:391` |
| Surface-class→region assignment | `MCellModSurfRegionsPropertyGroup` | `scene.mcell.mod_surf_regions` | `cellblender_main.py:934` |
| Partitions | `MCellPartitionsPropertyGroup` | `scene.mcell.partitions` | `cellblender_main.py:925` |
| PBC | `MCellPBCPropertyGroup` | `scene.mcell.pbc` | `cellblender_main.py:926` |
| Meshalyzer report | `MCellMeshalyzerPropertyGroup` | `scene.mcell.meshalyzer` | `cellblender_main.py:940` |
| Object name-filter selector | `MCellObjectSelectorPropertyGroup` | `scene.mcell.object_selector` | `cellblender_main.py:148,941` |

Panels are mostly drawn inline from the main CellBlender panel via `draw_layout`
(`cellblender_main.py:820-846`); the per-object region editor is drawn in the same
"Model Objects" section when an object is active (`cellblender_main.py:826`). Meshalyzer
and the Object Selector have their own standalone N-panel `bpy.types.Panel`s
(`cellblender_meshalyzer.py:1423`, `cellblender_surface_regions.py:192`).

---

## 1. Model objects — which meshes are part of the MCell model

File: `cellblender/cellblender_objects.py`.

A "model object" is any Blender `MESH` object whose `object.mcell.include` boolean is
`True` (`object_surface_regions.py:781`). The scene-level
`MCellModelObjectsPropertyGroup.object_list` (`cellblender_objects.py:795`) is a *mirror*
of that flag — it holds one `MCellModelObjectsProperty` per included object, keyed by the
object's name (`cellblender_objects.py:691`). The two representations are kept in sync by
`model_objects_update()` (`cellblender_objects.py:426`).

### The include flag vs. the list (gotcha: dual source of truth)

The `include` boolean on the object is authoritative; the `object_list` is a derived,
sorted view used for the UI list and for per-object MCell metadata (description, dynamic
geometry, BioNetGen parent/membrane). `build_properties_from_data_model` explicitly writes
*both* places (`cellblender_objects.py:1024-1062`): it rebuilds `object_list` from the data
model and then sets `o.mcell.include` for every scene object based on membership.

### `model_objects_update()` — the rebuild-from-scratch handler

`cellblender_objects.py:426-517`. Registered as both a `load_post` and a `save_pre`
handler (`__init__.py:453,465`) and called after any add/remove. It:

- Reads object status (visibility/selection/active) to restore later
  (`get_object_status`/`restore_object_status`, `cellblender_objects.py:52,66`).
- Collects names of `include`-flagged objects, sorts them, and **destroys and rebuilds**
  the entire `object_list`, saving and restoring the per-object MCell metadata
  (`description`, `dynamic`, `script_name`, `object_source`, `dynamic_display_source`,
  `parent_object`, `membrane_name`) through a `dyn_dict` keyed by name
  (`cellblender_objects.py:455-484`).
- Sets a per-object `status` error if any face is not a triangle
  (`cellblender_objects.py:487-492`) — MCell requires triangulated meshes.
- Re-validates every release site, since adding an object can satisfy a region/object
  release that referenced a not-yet-existing object
  (`cellblender_objects.py:505-513`; see doc on releases).

### Operators (Add / Remove / Visibility / Selection)

| Operator | idname | What it does |
|---|---|---|
| `MCELL_OT_model_objects_add` | `mcell.model_objects_add` | Include the **selected** mesh objects: triangulates them (`quads_convert_to_tris`), sets display flags, sets `obj.mcell.include = True`, calls `model_objects_update` (`cellblender_objects.py:141-191`). Skips molecule display meshes under the `molecules` object (`cellblender_objects.py:152-159`). |
| `MCELL_OT_model_objects_remove` | `mcell.model_objects_remove` | Clears `include` on the active list item, removes it (`cellblender_objects.py:194-217`). |
| `MCELL_OT_model_objects_remove_sel` | `mcell.model_objects_remove_sel` | Removes all selected mesh objects from the list (`cellblender_objects.py:220-251`). |
| `MCELL_OT_model_obj_add_mat` | `mcell.model_obj_add_mat` | Creates/assigns a `<name>_mat` material for color (`cellblender_objects.py:114-138`). |
| `MCELL_OT_create_object` | `mcell.model_objects_create` | `eval`s a `bpy.ops.mesh.primitive_*_add()` chosen via EnumProperty (`cellblender_objects.py:93-111`). |
| Show/Hide/Toggle visibility | `mcell.object_show_all` etc. | Iterate model objects, set `hide_viewport`/`hide_set` (`cellblender_objects.py:353-417`). |

The UIList `MCELL_UL_model_objects` (`cellblender_objects.py:542`) draws each row with a
material color swatch, a "show only this object" toggle (`object_show_only` callback,
`cellblender_objects.py:616`) and a per-object visibility toggle
(`toggle_visibility` callback, `cellblender_objects.py:650`). In BioNetGen mode it also
exposes `parent_object` and `membrane_name` for compartment nesting.

### Object naming constraint (gotcha)

`check_model_object_name` (`cellblender_objects.py:521-535`) enforces MDL-legal names:
must match `^[A-Za-z]+[0-9A-Za-z_.]*$` (start with a letter, only alphanumerics, `_`, `.`).
Illegal names set a `status` string that shows as an ERROR icon in the list; the rename is
*not* blocked, only flagged. The same regex governs region names
(`object_surface_regions.py:221`).

### Geometry serialization (mesh → data model and back)

`MCellModelObjectsPropertyGroup` is where geometry actually crosses into the data model:

- `build_data_model_object_from_mesh` (`cellblender_objects.py:1122-1194`): for one object,
  emits `name`, `location`, `material_names`, a `vertex_list` and `element_connections`
  (faces), optional per-face `element_material_indices`, and — critically — the object's
  surface regions via `data_object.mcell.get_regions_dictionary(...)` into
  `define_surface_regions` (`cellblender_objects.py:1177-1188`). It uses
  `to_mesh(preserve_all_data_layers=True, depsgraph=...)` and bakes `matrix_world`
  into the vertices (`cellblender_objects.py:1161-1168`).
- `build_data_model_geometry_from_mesh` (`cellblender_objects.py:1197-1249`): loops all
  included objects; when `dyn_geo=True` it steps every frame and snapshots a `frame_list`
  for dynamic non-scripted objects.
- `build_mesh_from_data_model_geometry` (`cellblender_objects.py:1267-1371`): the reverse —
  deletes name-colliding meshes, rebuilds each via `bpy.data.meshes.new` +
  `from_pydata`, reassigns materials/face indices, and **recreates surface regions** by
  calling `new_obj.mcell.regions.add_region_by_name` then `reg.set_region_faces`
  (`cellblender_objects.py:1356-1360`).
- `build_data_model_from_properties` (`cellblender_objects.py:941-963`): emits the
  lighter `model_object_list` (names + metadata, no vertices); data model version
  `DM_2018_01_11_1330`, upgraded through several versions at
  `cellblender_objects.py:966-1021`.

Note the data-model split: `model_objects` carries the *list/metadata*, while
`geometrical_objects` (vertices/faces/regions) and `materials` are separate top-level keys
assembled in `cellblender_main.py:1028,1036-1037`.

### Dynamic / scripted geometry

`MCellModelObjectsProperty` carries `dynamic`, `object_source` (`blender`/`script`),
`script_name`, `dynamic_display_source` (`script`/`files`)
(`cellblender_objects.py:694-716`). `update_scene` (`cellblender_objects.py:1442-1601`)
regenerates meshes per frame: it either `exec`s the user's Python script (which is handed
`points`, `faces`, `regions_dict`, `region_props`, `origin`, `frame_number`, a shallow
sweep-substituted `data_model`) or reads exported per-frame MDL via
`read_from_regularized_mdl` (`cellblender_objects.py:1374-1440`). A `frame_change_pre`
handler `frame_change_handler` (`cellblender_objects.py:1604`) drives it whenever
`has_some_dynamic` is set. `has_some_dynamic` is maintained by `changed_dynamic_callback`
(`cellblender_objects.py:669-677`).

---

## 2. Surface regions — named face sets on the mesh

Two files cooperate, and the naming is confusingly close:

| File | PropertyGroup(s) | Role |
|---|---|---|
| `object_surface_regions.py` | `MCellSurfaceRegionProperty`, `MCellSurfaceRegionListProperty`, `MCellObjectPropertyGroup` | The **per-object** region store + editor: defines regions, owns the face-set data on the mesh. Attached as `object.mcell`. |
| `cellblender_surface_regions.py` | `MCellModSurfRegionsProperty`, `MCellModSurfRegionsPropertyGroup`, `MCELL_PT_object_selector` | The **scene-level** "assign a surface class to a region" table. Attached as `scene.mcell.mod_surf_regions`. Also hosts the Object Selector panel. |

### 2a. Per-object regions (`object_surface_regions.py`)

`MCellObjectPropertyGroup` (`object_surface_regions.py:778-807`) is the type of
`object.mcell` (registered at `__init__.py:391`). It holds:

- `include: BoolProperty` — the model-object flag from §1.
- `regions: PointerProperty(type=MCellSurfaceRegionListProperty)` — the region collection.
- `get_regions_dictionary(obj)` (`object_surface_regions.py:783`) → `{region_name: [sorted face indices]}`, consumed by geometry export.
- `get_face_regions_dictionary(obj)` (`object_surface_regions.py:796`) → `{face: [region names]}`.

`MCellSurfaceRegionListProperty` (`object_surface_regions.py:464`) is the managing
collection: `region_list` of `MCellSurfaceRegionProperty`, an `active_reg_index`, and an
`id_counter` that hands out **unique integer IDs** via `allocate_id`
(`object_surface_regions.py:480-487`). It owns add/remove (`add_region`,
`add_region_by_name`, `remove_region`, `remove_all_regions`,
`object_surface_regions.py:531-587`), name validation + sorting (`region_update`,
`sort_region_list`, an in-place quicksort `inplace_quicksort`,
`object_surface_regions.py:590-640`), and the panel (`draw_layout`,
`object_surface_regions.py:647-712`).

#### How face sets are physically stored (the key data-model gotcha)

Region membership is **not** a Blender vertex group or face map — it is stored as a custom
ID-property dict directly on the *mesh datablock*:

```
mesh["mcell"]["regions"][ str(region_id) ][ str(seg_idx) ] = <run-length-encoded face indices>
```

See `init_region`/`reset_region`/`set_region_faces`/`get_region_faces`
(`object_surface_regions.py:326-401`). Important details:

- The dict is keyed by the **numeric region id** (as a string), *not* the region name —
  so renaming a region does not touch the mesh data (`object_surface_regions.py:305,358,378`).
- Face index lists are **run-length encoded** (`rl_encode`/`rl_decode`,
  `object_surface_regions.py:404-461`) and **segmented into ≤32767-element chunks**
  (`set_region_faces`, `object_surface_regions.py:386-401`) because Blender ID-property
  integer arrays have a length limit.
- `get_region_faces` decodes all segments back into a Python `set` of face indices
  (`object_surface_regions.py:355-372`).

#### Editing faces ↔ regions (Blender mesh API)

The region editor works in Edit Mode against `mesh.polygons` and `bmesh`:

- `MCELL_OT_region_faces_assign` / `_remove` → `assign_region_faces` /
  `remove_region_faces` (`object_surface_regions.py:75-98, 231-259`): read selected faces
  (`mesh.total_face_sel`, `f.select`), flip to OBJECT mode to mutate, update the encoded
  face set.
- `MCELL_OT_region_faces_select` / `_deselect` / `_select_all`
  (`object_surface_regions.py:101-136, 262-287`): push the stored face set back onto
  `mesh.polygons[f].select`.
- `MCELL_OT_face_get_regions` / `MCELL_OT_faces_get_regions`
  (`object_surface_regions.py:162-181`) → `face_get_regions`/`faces_get_regions`
  (`object_surface_regions.py:500-528`): which regions a face belongs to. These use a
  draw-safe `_get_selected_face_indices` that reads from `bmesh.from_edit_mesh` when in
  Edit mode (`object_surface_regions.py:490-497`).
- `MCELL_OT_eliminate_overlapping_faces` / `MCELL_OT_eliminate_all_overlaps`
  (`object_surface_regions.py:138-160, 289-300`): remove this region's faces from all
  other regions so a face belongs to a single region.

#### Format upgrade & legacy vertex groups

`format_update` (`object_surface_regions.py:715-772`), run by the `load_post` handler
`object_regions_format_update` (`object_surface_regions.py:813`, registered at
`__init__.py:454`), migrates pre-v1.0 region storage (keyed by region *name*) to the new
id-keyed format, and prunes orphaned mesh region cruft. `MCELL_OT_vertex_groups_to_regions`
(`object_surface_regions.py:834-906`) is legacy tooling to convert old vertex-group regions
into face regions (regions used to be stored as vertex groups).

### 2b. Surface-class → region assignment (`cellblender_surface_regions.py`)

`MCellModSurfRegionsProperty` (`cellblender_surface_regions.py:231-339`) ties a **surface
class** (see doc 02) to a region (or ALL faces) of a model object. Fields: `surf_class_name`,
`object_name`, `region_selection` (`ALL`/`SEL`), `region_name`. The validator
`check_mod_surf_regions` (`cellblender_surface_regions.py:69-134`) cross-checks that:

- the surface class exists in `mcell.surface_classes.surf_class_list`,
- the object exists in `mcell.model_objects.object_list`,
- the region name exists in `bpy.data.objects[object_name].mcell.regions.region_list`
  (unless `ALL`), looked up live (`cellblender_surface_regions.py:91-93`).

The panel (`cellblender_surface_regions.py:409-463`) uses `prop_search` against
`mcell.surface_classes`, `mcell.model_objects.object_list`, and the object's own
`regions.region_list` — directly demonstrating the wiring between surface classes, model
objects, and per-object regions. It refuses to draw until at least one surface class and
one model object exist (`cellblender_surface_regions.py:419-423`). Serialized as
`modify_surface_regions_list` (`cellblender_surface_regions.py:347-355`). Note the upgrade
path drops MCell4 "initial region molecules" with a warning — they are not supported
(`cellblender_surface_regions.py:308-311`).

### 2c. Object Selector (bonus panel in the same file)

`MCELL_PT_object_selector` (`cellblender_surface_regions.py:192-214`) is a standalone
N-panel exposing `mcell.object_selector.filter` (a regex). Its operators live in
`cellblender_objects.py`: `MCELL_OT_select_filtered`, `_deselect_filtered`,
`_toggle_visibility_filtered`, `_toggle_renderability_filtered`
(`cellblender_objects.py:256-350`) — they `re.match` object names and act on whole-name
matches.

### How regions connect to the rest of MCell

Regions feed three consumers: (1) geometry export embeds them as `define_surface_regions`
(§1); (2) `mod_surf_regions` assigns surface classes to them (doc 02); (3) molecule
**release sites** can release "on region" by referencing `object[region]`
(see the releases doc) — which is why `model_objects_update` re-checks releases when objects
change (`cellblender_objects.py:505-513`).

---

## 3. Partitions — bounding the simulated world

File: `cellblender/cellblender_partitions.py`. `MCellPartitionsPropertyGroup`
(`cellblender_partitions.py:340-553`) defines the axis-aligned subvolume grid MCell uses to
accelerate spatial lookups.

Two field sets, switched by `cellblender_preferences.mcell4_mode`:

- **MCell3**: per-axis `x_start/x_end/x_step`, `y_*`, `z_*` plus an `include` toggle
  (`cellblender_partitions.py:350-385`).
- **MCell4**: scalar `start`, `end`, `step` applied to all axes — MCell4 partitions are a
  single cube (`cellblender_partitions.py:388-401`).

### Visual boundary box (direct Blender object manipulation)

`MCELL_OT_create_partitions_object` (`cellblender_partitions.py:46-94`) adds a cube named
`"partitions"`, sets it to wireframe display and `hide_select = True` so the user can't
drag it (there is no machinery to read transforms back). `transform_*_partition_boundary`
(`cellblender_partitions.py:184-255`) — fired as `update` callbacks on the start/end props —
scale and locate that cube to match the numeric bounds (cube is 2×2×2, so
`scale = (end-start)/2`, `location = start + (end-start)/2`).
`MCELL_OT_remove_partitions_object` (`cellblender_partitions.py:97-115`) deletes both the
object and its mesh.

`check_partition_step` (`cellblender_partitions.py:314-335`) clamps step magnitude to the
range and fixes the step's sign to match the start→end direction. A `recursion_flag`
guards against the update callbacks re-entering (`cellblender_partitions.py:346-349,
258-311`).

### Auto-generate from model objects (gotcha: world-space bounds)

`MCELL_OT_auto_generate_boundaries` (`cellblender_partitions.py:118-180`) walks every object
in `model_objects.object_list`, transforms each vertex by `obj.matrix_world` to **world
coordinates** (`cellblender_partitions.py:138`), and sets the partition bounds to the
min/max. It tolerates list entries whose object was deleted (`except KeyError: pass`,
`cellblender_partitions.py:162`). In MCell4 mode it collapses to a single
min/max cube (`cellblender_partitions.py:169-178`).

Serialized at `cellblender_partitions.py:404-437` (version `DM_2016_04_15_1600`); the
partitions dict is nested under `initialization` in the data model
(`cellblender_main.py:1020,1077`). The upgrade code (`cellblender_partitions.py:440-472`)
documents a historic bug where `z_start` was written to `x_start`.

---

## 4. Periodic boundary conditions (`cellblender_pbc.py`)

`MCellPBCPropertyGroup` (`cellblender_pbc.py:39-163`) is a pure data + UI group — no
operators, no Blender-object side effects. It defines an `include` flag, per-axis
`x/y/z_start` and `x/y/z_end`, and booleans `peri_trad` (traditional), `peri_x/y/z`
(`cellblender_pbc.py:41-68`). The panel is disabled in MCell4 mode with the explicit note
"Periodic Boundary Conditions are not supported in MCell4."
(`cellblender_pbc.py:71-73`). Serialized as `periodic_boundary_conditions`
(`cellblender_main.py:1027`), version `DM_2020_02_21_1900`
(`cellblender_pbc.py:106-138`).

---

## 5. Meshalyzer — mesh validation & topology (`cellblender_meshalyzer.py`)

The Meshalyzer checks whether a mesh is a valid MCell surface (closed, manifold,
consistently-oriented, triangulated) and reports geometric/topological quantities. Results
land in `MCellMeshalyzerPropertyGroup` (`cellblender_meshalyzer.py:1496-1520`) and render in
the standalone panel `MCELL_PT_meshalyzer` (`cellblender_meshalyzer.py:1423-1490`).

### Two operators

- `MCELL_OT_meshalyzer` (`mcell.meshalyzer`, `cellblender_meshalyzer.py:179-217`): analyze
  the single selected object; populates the panel fields.
- `MCELL_OT_gen_meshalyzer_report` (`mcell.gen_meshalyzer_report`,
  `cellblender_meshalyzer.py:221-294`): analyze many selected objects, writing a
  `mesh_analysis.txt` Blender text datablock.

Both first verify the mesh is triangulated via
`mesh.polygons.foreach_get('vertices', tmp)` against a `3*len` buffer (raises if any face
isn't a tri, `cellblender_meshalyzer.py:204-209`) and warn if the object has a non-unit
scale (analysis runs on unscaled mesh data, `cellblender_meshalyzer.py:211-213`).

### The modern analysis core: `MeshAnalyzer`

`mesh_analyzer(obj)` (`cellblender_meshalyzer.py:92-176`) drives the `MeshAnalyzer` class
(`cellblender_meshalyzer.py:602`), a linear-algebra implementation built on **NumPy +
SciPy sparse** (`coo_array`, `connected_components`, `yen`) and `bmesh`
(`cellblender_meshalyzer.py:36-43`). It builds two oriented sparse incidence matrices —
edge×vertex (`_incidence_edge_vertex`, `cellblender_meshalyzer.py:646`) and
simplex×edge (`_incidence_simplex_edge`, `cellblender_meshalyzer.py:687`) — and derives
everything from them:

| Quantity | Method | Meaning / report field |
|---|---|---|
| Orphan vertices | `_orphan_vertices` (`:735`) | vertices on no edge |
| Dangling / orphan edges | `_dangling_orphan_edges` (`:748`) | edges on no face / fully isolated |
| Disjoint components | `_disjoint_components` (`:773`) | connected pieces |
| Subcomponents | `_subcomponents` (`:830`) | pieces split at non-manifold edges/verts |
| Non-manifold edges | `_nonmanifold_edges` (`:811`) | edges shared by >2 faces |
| Non-manifold vertices | `_nonmanifold_vertices_volume` + boundary (`:882`, `:1002`) | verts shared by >1 neighborhood |
| Consistent normals / orientability | `_consistent_normals` (`:934`) | sum of oriented incidences == 0 |
| Boundary edges / cycles | `_boundary_edges` (`:968`), `_boundary_cycles` (`:1002`) | open mesh borders (via `BoundaryCycles`, `:410`) |
| Euler characteristic | `_euler_characteristic` (`:1056`) | V−E+F |
| Genus | `_genus`/`_gen` (`:1112`, `:1096`) | handles; formula differs for non-orientable |
| Surface area | `_area` (`:1137`) | sum of `polygon.area` |
| Signed volume | `_volume`/`_vol` (`:1184`, `:1170`) | divergence-theorem tetra sum; only for watertight components |
| Median signed SA/V ratio | in `_volume` (`:1219`) | area/volume |

`mesh_analyzer` short-circuits if the mesh is impure (orphans/dangling) and sets
`pure=False` (`cellblender_meshalyzer.py:116-119`). Orientability is handled in a loop:
if normals are inconsistent it calls
`bpy.ops.mesh.normals_make_consistent` once and re-checks; still inconsistent ⇒ declared
non-orientable (`cellblender_meshalyzer.py:96-148`). `BoundaryCycles`
(`cellblender_meshalyzer.py:410-599`) traces boundary loops even when several loops meet at
one singular vertex.

### Legacy path & helpers (still present)

`execute_orig` (`cellblender_meshalyzer.py:297-399`) is the older edge-face-dictionary
algorithm. Its helpers remain in the module and use the Blender mesh / `bpy.ops` directly:
`make_efdict` (`:1307`, XOR-folds face indices per edge), `check_manifold` (`:1323`,
edge_face_count ≤ 2), `check_closed` (`:1342`, count == 2 → watertight),
`count_orphan_vertices`/`count_nonmanifold_vertices` (`:1352`, `:1373`, via
`bpy.ops.mesh.select_non_manifold`), `check_orientable` (`:1398`), and `mesh_vol` (`:1277`).
`select_vertices`/`select_edges`/`select_faces` (`:1226-1274`) use `bmesh.from_edit_mesh`
to highlight problem elements.

**Gotcha:** as commented at `cellblender_meshalyzer.py:1390-1397`, consistent normals do
**not** by themselves prove orientability — the recalculate-and-recheck step in
`mesh_analyzer` is what establishes it, choosing genus formula 1 (orientable) vs. 2
(non-orientable).

---

## Cross-references & gotchas summary

- **Triangulation is mandatory.** Model object inclusion triangulates
  (`cellblender_objects.py:166`), `model_objects_update` flags non-tris
  (`cellblender_objects.py:487`), and Meshalyzer refuses non-tri meshes
  (`cellblender_meshalyzer.py:205-209`).
- **Regions live on the mesh, keyed by id not name**, RLE-encoded and 32767-chunked
  (`object_surface_regions.py:375-401`) — renames are cheap, but copying a mesh copies the
  region IDProp, and the id↔name link lives only in `region_list`.
- **Dual source of truth** for model objects: `object.mcell.include` (authoritative) and
  `model_objects.object_list` (derived) — always go through `model_objects_update`
  (`cellblender_objects.py:426`).
- **MCell3 vs MCell4** branching pervades partitions and PBC (per-axis vs single cube; PBC
  unsupported in MCell4).
- **Name regex** `^[A-Za-z]+[0-9A-Za-z_.]*$` constrains both object and region names
  (`cellblender_objects.py:528`, `object_surface_regions.py:221`).
- The `"partitions"` boundary cube is `hide_select=True`; edits to it are *not* read back —
  numeric props are the source (`cellblender_partitions.py:80, 77-79`).

*Part of the CellBlender codebase wiki — see 00_overview.md.*
