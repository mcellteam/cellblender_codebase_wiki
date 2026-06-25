# Keeping This Wiki Current

> **Purpose:** the maintenance playbook for the CellBlender wiki itself. After you change the
> CellBlender source, use it to decide *which* document needs updating and *how* to refresh it — so
> the wiki keeps matching the tree instead of rotting into stale notes.
>
> **Core rule:** the wiki is a *derived artifact* of the source. Every doc cites real
> `file_path:line` locations, and **line numbers drift on almost any edit**. Treat a wiki update as
> part of "done" for any change that touches the areas below — the same way you'd update a
> changelog or a test.
>
> **Scope note:** this wiki documents the `cellblender/` repo only. Citations are written relative
> to **`$ROOT`** — the directory containing both `cellblender/` and `cellblender_codebase_wiki/`
> (the parent of this wiki folder), so they read `cellblender/<file>.py:line`. `$ROOT` is
> self-locating; see `CLAUDE.md` §"`$ROOT`" for the one-liner to resolve it. The shell snippets
> below assume you have set `ROOT` (e.g. from this wiki dir, `ROOT=$(cd .. && pwd)`). Beware the
> `cellblender -> .` self-symlink inside the repo — always cite the real path
> (`cellblender/cellblender_main.py`), never the doubled `cellblender/cellblender/...`.

---

## 1. The fastest way to refresh: re-run the mapping pass

The wiki was produced by a **multi-agent mapping pass** — one agent per domain document, each
reading its slice of the source and writing one `NN_*.md` with `file_path:line` citations, then an
orchestrator consolidating `00_overview.md`. The cleanest way to update after substantial changes
is to **re-run that pass** (or the relevant slice) rather than hand-patch. Ask the assistant:

> "Re-map `<area>` and update the corresponding wiki doc(s) in `cellblender_codebase_wiki/`,
> preserving the structure and refreshing all `file_path:line` references."

Each document is independent and regenerable on its own, so you can re-map just the part that
changed. For a small, surgical change, a hand-edit is fine — see §3.

---

## 2. Change → document map

Find the area you touched on the left; update the doc(s) on the right. (This table is mirrored by
the `RULES` list in `wiki_check.py` — keep them in sync.)

| If you changed… | Update | Why |
|---|---|---|
| `__init__.py`, `cellblender_main.py`, `cellblender_initialization.py`, preferences/utils/project/scripting/examples/legacy, `cellblender_id.py`/`cellblender_source_info.py`/`update_cellblender_id.py` | **01** (+ **00** if registration/root-PropertyGroup/boot flow changes) | the add-on core & UI framework doc |
| `cellblender_molecules.py`, `cellblender_reactions.py`, `cellblender_release.py`, `cellblender_surface_classes.py`, `cellblender_molmaker.py`, `cellblender_glyphs.py` | **02** (+ **00 §5.3** if cross-references change) | the chemistry doc |
| `cellblender_objects.py`, `cellblender_surface_regions.py`, `object_surface_regions.py`, `cellblender_partitions.py`, `cellblender_meshalyzer.py`, `cellblender_pbc.py` | **03** (+ **00 §5.4**) | the geometry doc |
| `parameter_system.py`, `ParameterSpace.py` | **04** (+ **00 §5.2**) | nearly every numeric field is parameter-backed |
| `data_model.py`, `io_mesh_mcell_mdl/`, `mdl/`, `data_plotters/` | **05** (+ **00 §4** if the data-model contract / version scheme changes) | the data-model hub & MDL I/O doc |
| `cellblender_simulation.py`, `sim_engine_manager/`, `sim_runner_manager/`, `run_simulations.py`, `run_wrapper.py`, `sim_runner_queue.py`, `old_sim_engines/`, `mcell4/`, `bng/` | **06** (+ **00 §5.5**) | the run pipeline & engines doc |
| `cellblender_mol_viz.py`, `cellblender_reaction_output.py` | **07** (+ **00 §5.6**) | the results-visualization doc |
| `blender_manifest.toml`, `make_bundle.sh`, `makefile`, packaging | **00 §2** | the packaging description lives in the overview |
| Added/removed a whole top-level module or subpackage | the relevant `NN_*.md` **+ 00 §1 index, §6 cheat-sheet** **+** a new `RULES` row in `wiki_check.py` | the integration map is the source of truth for "what's wired in" |

> **Note:** doc **00 (overview)** is the integration map — almost any *structural* change (new
> domain module, changed data-model contract, new run/engine path, new cross-reference) should be
> reflected there even if the detail lives in another doc.

---

## 3. Updating a single doc by hand (small changes)

For a localized change (renamed an operator, moved a field, added one PropertyGroup):

1. **Open the doc** from the §2 table.
2. **Grep for the old reference** in the doc and the new location in the source:
   ```sh
   cd "$ROOT"        # the dir holding cellblender/ and cellblender_codebase_wiki/
   grep -n "old_operator_name" cellblender_codebase_wiki/02_chemistry_molecules_reactions.md
   grep -rn "new_operator_name" cellblender
   ```
3. **Fix the prose + the `file_path:line`.** Re-confirm the line number against the current file
   (line numbers are the first thing to go stale).
4. If the change affects a **data-model field** (a new attribute that serializes), confirm all five
   data-model methods and any **`upgrade_data_model` version bump** are reflected — see §4.
5. If it affects a **cross-reference** (who references whom) or the **run pipeline**, also patch
   **00**'s integration map.
6. Update the "Generated …" stamp at the bottom of the doc if you did a meaningful refresh.

---

## 4. Special trigger: the data model (most common drift source)

CellBlender's **data model** (doc 05) is the interchange format every domain serializes to/from,
and it is **versioned**. Whenever you add or change a serialized field:

- The owning domain's `build_data_model_from_properties` / `build_properties_from_data_model`
  change → update that domain's doc (02/03/04/06/07) **and**, if the *shape* changed, doc 05.
- You bumped the **data-model version** and added an `upgrade_data_model` step → update doc 05's
  version-chain section (the `DM_YYYY_MM_DD_HHMM` constants) and note the new step.
- **Refresh the build identity**: run `python3 update_cellblender_id.py` and commit the resulting
  `cellblender_id.py`. The SHA mismatch is what triggers upgrades on load; a stale ID means
  installed CellBlenders won't recognize the new version. (This is the repo's own standing rule —
  see `cellblender/CLAUDE.md`.)

---

## 5. Drift-detection checklist (run before trusting the wiki)

- [ ] **Citations resolve.** Spot-check a few `file_path:line` refs per doc — does the cited line
      still contain what the doc claims? (Line drift is the #1 failure.)
- [ ] **Registration list matches.** The module load order in **doc 01** vs the `IMPORT_MODULE_NAMES`
      tuple in `cellblender/__init__.py`.
- [ ] **Root PropertyGroup matches.** `MCellPropertyGroup` and its `PointerProperty` children named
      across docs still exist in `cellblender/cellblender_main.py`.
- [ ] **Data-model version constants.** The `DM_*` constants doc 05 lists vs the current source.
- [ ] **Run-control options.** The `simulation_run_control` paths in **doc 06** vs
      `cellblender/cellblender_simulation.py`.
- [ ] **Subpackage file lists.** `ls cellblender/{bng,sim_engine_manager,sim_runner_manager,io_mesh_mcell_mdl,mdl}`
      vs what docs 05/06 enumerate.

A handy one-liner to find every cited file path that no longer exists:
```sh
cd "$ROOT"        # the dir holding cellblender/ and cellblender_codebase_wiki/
grep -rhoE '\bcellblender/[A-Za-z0-9_./-]+\.(py|toml|json|mdl|sh|txt|c|h|i)' cellblender_codebase_wiki \
  | sort -u | while read -r f; do [ -e "$f" ] || echo "MISSING: $f"; done
```
(Paths in the docs are written relative to `$ROOT`; run from there. It flags
deleted/renamed files — line-number drift still needs the spot-check above.)

---

## 6. The `wiki_check.py` helper (automate §2 + §5)

`wiki_check.py` lives in this directory and mechanizes the change→doc map (§2) and the
drift-detection checklist (§5). It is **stdlib-only**, **takes paths as arguments** (nothing
hardcoded), and **never writes to the source repo's tracked files** — so it is safe on a shared
tree. Run it from anywhere:

```sh
cd cellblender_codebase_wiki
./wiki_check.py                       # full audit: citation drift + change->doc reminder
./wiki_check.py --since origin/master # what changed on this branch vs master, and which docs to touch
./wiki_check.py --staged --strict     # gate mode: nonzero exit if drift/pending updates (for a hook)
./wiki_check.py --mark-stale --staged # MODIFY: flag implicated docs with a "possibly stale" banner
./wiki_check.py --clear-stale         # MODIFY: remove all stale banners once docs are updated
```

What it does:
- **Citation check (§5):** scans every `*.md` for `path[:line]` references, resolves each against a
  file index of the whole tree, and reports files that no longer exist or line numbers now out of
  range. It auto-resolves repo-relative paths and ignores shorthand/placeholders. It deliberately
  **does not** descend the `cellblender -> .` self-symlink.
- **Change→doc reminder (§2):** lists changed files in the `cellblender` repo (staged / since a ref
  / vs HEAD) and prints exactly which wiki docs the `RULES` table says to update.
- **`--mark-stale` / `--clear-stale`:** insert or remove an idempotent, byte-clean "possibly stale"
  banner at the top of the implicated docs.

Paths default to this script's directory (`--wiki`), its parent (`--root`, so that
`cellblender/...` citations resolve), and the `cellblender/` repo (`--repo`, auto-discovered);
override any explicitly. **The change→doc rules live in the `RULES` list near the top of the
script — edit `RULES` whenever you add/rename a wiki doc or a watched source area**, mirroring §2.

> ### CAVEAT — how the citation check behaves (don't over-trust it)
> The citation check is deliberately **conservative to avoid false positives**: it flags a cited
> file as `MISSING` only when that **basename exists nowhere** in the tree. A citation that points
> at the *wrong directory* but whose filename still exists somewhere is **not** flagged. So it
> reliably catches deleted/renamed files and out-of-range line numbers, but will **not** catch a
> path-prefix mistake (right filename, wrong folder) — use the §5 spot-check for those.

### Optional: wire it as a *local, uncommitted* pre-commit hook
This keeps automation per-clone and adds **nothing** to the repo's tracked tree (`.git/hooks/` is
local and never committed). In your clone of `cellblender`:

```sh
cat > cellblender/.git/hooks/pre-commit <<'EOF'
#!/bin/sh
# advisory reminder; never blocks a commit (add --strict to make it a hard gate)
exec python3 "$(git rev-parse --show-toplevel)/../cellblender_codebase_wiki/wiki_check.py" --staged
EOF
chmod +x cellblender/.git/hooks/pre-commit
```

> **Tip:** CellBlender already requires refreshing `cellblender_id.py` before each pushed commit
> (`python3 update_cellblender_id.py`). A natural place to combine both reminders is this same local
> hook.

---

## 7. When to do a full re-map vs. a patch

- **Patch by hand** (§3): renamed/moved a few symbols, added one operator or field, fixed a line.
- **Re-map the affected doc** (§1): you reworked a subsystem (e.g. the run pipeline, the parameter
  evaluator, the data-model upgrade chain) and the structure — not just line numbers — changed.
- **Re-map everything**: a major refactor crossing several areas (new engine path, data-model
  overhaul, registration rework). Re-running the whole pass is cheaper and more reliable than
  reconciling every doc by hand.

---

*This note is itself part of the wiki — if you change the wiki's structure or file names, update
the §1 index in `00_overview.md` and this document's §2 table (and the `RULES` list in
`wiki_check.py`) together.*
