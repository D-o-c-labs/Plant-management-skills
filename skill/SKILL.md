---
name: plant-management
description: Manage plant registry data, care profiles, reminders, and deterministic care evaluation through a validated Python CLI.
requires:
  env:
    - PLANT_DATA_DIR
  bins:
    - python3
optional_env:
  - PLANT_SKILL_DIR
  - PLANT_TIMEZONE
  - PLANT_LOCALE
  - TREFLE_API_KEY
  - PERENUAL_API_KEY
  - OPENPLANTBOOK_CLIENT_ID
  - OPENPLANTBOOK_CLIENT_SECRET
  - TAVILY_API_KEY
---

# Plant Management Skill

Use this skill to manage household plants through the validated Python CLI. The AI handles judgment, clarification, and user messaging. The Python code handles data integrity, schema validation, reminder state, and deterministic care evaluation.

## Operating Defaults

- Never edit JSON files in `$PLANT_DATA_DIR` directly.
- Always run commands from the skill root with `python3 scripts/plant_mgmt_cli.py ...`.
- Prefer `--json` for reads, status checks, and anything you need to reason over programmatically.
- If the user gives a clear, specific write request, run the matching CLI mutation directly. Ask only when the target or effect is genuinely ambiguous.
- Treat `init --force`, `migrate`, broad inferred multi-plant writes, and unclear archive operations as higher-risk changes that may need confirmation.
- For questions about due work, reminders, or current status, use evaluation output as the source of truth before improvising.
- For diagnosis questions involving pests, deficiencies, disease, soil, or treatment supplies, query `products` before recommending that the user buy something.
- If the user is reporting completed care from a reminder-driven task, resolve the reminder when there is exactly one obvious open match. If there is no matching reminder, use `events log`.
- Use external `lookup` commands only when the species or care details are unclear. If API keys are unavailable, continue with the best confirmed local information.
- Routine CLI writes already validate before saving. Run `validate` or `check` explicitly only for setup, migration, repair, or diagnosis.
- If the CLI reports missing dependencies, install `scripts/requirements.txt` into the host Python environment before continuing.

## First Run

1. Set `PLANT_DATA_DIR` to the directory that should contain the plant JSON files.
2. Ensure the host Python environment has the packages from `scripts/requirements.txt`.
3. Initialize a fresh data directory or import an existing one.

```bash
export PLANT_DATA_DIR=/path/to/plant-data
python3 scripts/plant_mgmt_cli.py init
python3 scripts/plant_mgmt_cli.py validate
```

To migrate from an existing compatible data directory:

```bash
python3 scripts/plant_mgmt_cli.py migrate /path/to/existing/data
```

Or:

```bash
python3 scripts/plant_mgmt_cli.py init --from-existing /path/to/existing/data
```

## Primary Workflows

### 1. Status, due work, and reminders

Use these first when the user asks what needs attention, what is due, or whether something should be done now:

```bash
python3 scripts/plant_mgmt_cli.py --json eval status
python3 scripts/plant_mgmt_cli.py --json eval run [--weather '{"tempC":32,"humidity":35,"condition":"sunny"}'] [--dry-run]
python3 scripts/plant_mgmt_cli.py --json eval run | python3 scripts/plant_mgmt_cli.py eval render
python3 scripts/plant_mgmt_cli.py --json eval run | python3 scripts/plant_mgmt_cli.py --json eval render
```

`eval run` returns:

- `actions`: due items that should be pushed now
- `suppressedActions`: due items blocked by push policy
- `noAction`: evaluated plants that are not due
- `stateChanges`: tasks opened, updated, or closed by this evaluation
- `autoIrrigation`: automatic watering confirmations emitted or skipped before rule evaluation
- `summary`: counts

Automatic irrigation events are logged before care rules run, so normal watering reminders self-silence for plants covered by a working enabled system. The auto schedule uses only previous auto-irrigation events as its anchor; manual `watering_confirmed` events do not move the system schedule.

Interpretation:

- `low`: mention casually
- `medium`: worth checking now
- `high`: action should happen soon
- `critical`: urgent and should be phrased directly

Messaging rules:

- One message per evaluation run, not one message per plant
- Group by location and action type
- For 1-2 simple actions, one natural sentence is fine
- For 3+ plants or mixed actions, use a grouped schematic format
- If `actions` is empty, stay quiet unless the user explicitly asked for status

Judgment rules:

- Recovering plants: prefer “check first” over “water now”
- Drought-tolerant plants: do not override conservative baselines with generic thirsty-plant advice
- Heat stress and harsh placement can require shade or movement, not just water
- If confidence is limited, ask for a manual check or photo instead of bluffing certainty

### 2. Confirm completed care

Use this decision tree:

1. If the user is confirming an open reminder task, use `reminders confirm`.
2. If the user does not provide a task ID, inspect open reminders and auto-confirm only when exactly one obvious task matches.
3. If the care action did not come from a reminder, use `events log`.

Common reminder commands:

```bash
python3 scripts/plant_mgmt_cli.py reminders list [--status open|done|expired|cancelled]
python3 scripts/plant_mgmt_cli.py reminders get <taskId>
python3 scripts/plant_mgmt_cli.py reminders confirm <taskId> [--details "Watered thoroughly"]
python3 scripts/plant_mgmt_cli.py reminders confirm <taskId> --details "Neem applied this morning" --effective-date 2026-03-18 --effective-precision part_of_day --effective-part-of-day morning
python3 scripts/plant_mgmt_cli.py reminders cancel <taskId> [--reason "Heavy rain made this irrelevant"]
```

Use `events log` when the user reports an action and there is no reminder task to confirm:

```bash
python3 scripts/plant_mgmt_cli.py events log --type watering_confirmed --plant plant_001 --scope "manual watering" [--details '{"method":"watering_can"}']
python3 scripts/plant_mgmt_cli.py events log --type neem_confirmed --plant plant_001 --effective-date 2026-03-18 --effective-precision part_of_day --effective-part-of-day morning
python3 scripts/plant_mgmt_cli.py events log --type watering_confirmed --plant plant_001 --effective-datetime 2026-03-18T07:30:00 --effective-precision exact
python3 scripts/plant_mgmt_cli.py events list [--plant plant_001] [--type watering_confirmed] [--since 2026-03-01] [--limit 20]
python3 scripts/plant_mgmt_cli.py events last plant_001 [--type watering_confirmed]
```

Common event types:

- `watering_confirmed`
- `rain_confirmed`
- `neem_confirmed`
- `fertilization_confirmed`
- `repotting_confirmed`
- `healthcheck_confirmed`
- `photo_received`

Typical free-text mappings:

- “I watered it” / “innaffiato” / “dato acqua” -> `watering_confirmed`
- “It rained” / “ha piovuto” -> `rain_confirmed`
- “Neem done” / “neem fatto” -> `neem_confirmed`
- “Fertilized” / “concimato” -> `fertilization_confirmed`
- “Repotted” / “rinvasato” -> `repotting_confirmed`

If the user says “I watered the balcony”, apply it to the active plants in that location if the target set is obvious. Ask only when the target plants are genuinely ambiguous.

### 3. Quick registry and profile changes

Use these for common CRUD work:

```bash
python3 scripts/plant_mgmt_cli.py plants list [--status active|recovering|archived|dead] [--location <locationId>]
python3 scripts/plant_mgmt_cli.py plants get <plantId>
python3 scripts/plant_mgmt_cli.py plants add --name "basilico" --location rear_balcony [--species "basil"] [--scientific-name "Ocimum basilicum"] [--sublocation rear_balcony_kitchen] [--irrigation-mode manual|automatic|mixed] [--irrigation-system rear_balcony_irrigation] [--indoor-outdoor indoor|outdoor] [--attached-to-irrigation] [--notes "..."]
python3 scripts/plant_mgmt_cli.py plants update <plantId> --data '{"status":"recovering","notes":"Moved out of direct sun"}'
python3 scripts/plant_mgmt_cli.py plants move <plantId> --location <locationId> [--sublocation <microzoneId>]
python3 scripts/plant_mgmt_cli.py plants archive <plantId> [--reason "Died from frost"]
```

```bash
python3 scripts/plant_mgmt_cli.py locations list
python3 scripts/plant_mgmt_cli.py locations get <locationId>
python3 scripts/plant_mgmt_cli.py locations add --id rear_balcony --name "Rear balcony" --type balcony [--indoor-outdoor outdoor] [--exposure south]
python3 scripts/plant_mgmt_cli.py locations update <locationId> --data '{"notes":"Hot after 14:00"}'
```

```bash
python3 scripts/plant_mgmt_cli.py irrigation list
python3 scripts/plant_mgmt_cli.py irrigation get <systemId>
python3 scripts/plant_mgmt_cli.py irrigation update <systemId> --data '{"autoSchedule":{"cadenceDays":3,"skipOnRain":true}}'
```

An irrigation system `autoSchedule` enables automatic `watering_confirmed` logging during `eval run` for eligible plants. Eligible plants must have `irrigationSystemId` matching the system, `attachedToIrrigation: true`, status `active` or `recovering`, no manual exception on the system, and `irrigationMode` other than `manual`.

`autoSchedule` fields:

- `cadenceDays`: required default automatic watering cadence
- `skipOnRain`: optional boolean; skips today's auto-event when provided weather has `"condition":"rain"`
- `seasonalSchedule`: optional per-season overrides for `winter`, `spring`, `summer`, and `autumn`; each season can set `enabled` and `cadenceDays`

```bash
python3 scripts/plant_mgmt_cli.py profiles list watering [--plant <plantId>]
python3 scripts/plant_mgmt_cli.py profiles get watering <plantId-or-profileId>
python3 scripts/plant_mgmt_cli.py profiles set watering <plantId> --data '{"baselineSource":"container citrus","seasonalBaseline":{"winter":{"level":"low","baseIntervalDays":[10,14]},"spring":{"level":"medium","baseIntervalDays":[5,8]},"summer":{"level":"high","baseIntervalDays":[2,4]},"autumn":{"level":"medium","baseIntervalDays":[6,9]}}}'
python3 scripts/plant_mgmt_cli.py profiles remove watering <plantId-or-profileId>
```

Supported profile types: `watering`, `fertilization`, `repotting`, `pest`, `maintenance`, `healthcheck`.

Profile IDs are supported, but by default a profile’s `profileId` equals its `plantId`. The plant record stores the linked profile ID in fields like `wateringProfileId`.

### 4. Product inventory and diagnosis

Use `products` to store owned pesticides, fungicides, fertilizers, soil amendments, substrates, tools, and other supplies. Prefer this registry when the user asks whether they already have something suitable.

```bash
python3 scripts/plant_mgmt_cli.py --json products list [--category pesticide] [--target-issue spider_mites]
python3 scripts/plant_mgmt_cli.py products get product_001
python3 scripts/plant_mgmt_cli.py products add --display-name "Olio di neem BioGarden" --category pesticide --description "Olio di neem puro 100%" --target-issues spider_mites,aphids [--photo-file /path/to/photo.jpg] [--notes "..."]
python3 scripts/plant_mgmt_cli.py products update product_001 --data '{"notes":"Use in evening only"}'
python3 scripts/plant_mgmt_cli.py products remove product_001
```

Product categories: `pesticide`, `fungicide`, `fertilizer`, `soil_amendment`, `substrate`, `tool`, `other`.

Product photos are copied into `$PLANT_DATA_DIR/media/products/`; the stored `photoPath` is relative to `$PLANT_DATA_DIR`.

Canonical `targetIssues` keys:

`spider_mites, aphids, whitefly, thrips, scale_insects, mealybugs, fungus_gnats, powdery_mildew, downy_mildew, root_rot, leaf_spot, rust, iron_deficiency, nitrogen_deficiency, potassium_deficiency, magnesium_deficiency, sunburn, frost_damage, overwatering, underwatering`

Use these exact keys where applicable. Add new target issue keys only in snake_case English. Keep full label and usage context in `description` so fallback text search remains useful.

Diagnosis flow:

1. Identify the likely issue from the user's photo or description.
2. Normalize it to a canonical key, such as Italian “ragnetti rossi” -> `spider_mites`.
3. Run `python3 scripts/plant_mgmt_cli.py --json products list --target-issue <key> --category <likely-category>`.
4. If products match, recommend from inventory with appropriate caution.
5. If no product matches, run `python3 scripts/plant_mgmt_cli.py --json products list` and scan `description` fields before concluding there is no suitable owned product.

### 5. Onboard a new plant

When adding new plants:

1. Identify the plant from a photo or text description.
2. Use `lookup` only if species or care info is unclear.
3. Create the plant record with `plants add`.
4. Create at least a watering profile. Add fertilization or other profiles if you know them.
5. Re-run `eval run --dry-run` to verify the plant is now part of evaluation.

Prefer onboarding one location at a time.

Lookup commands:

```bash
python3 scripts/plant_mgmt_cli.py lookup search "monstera deliciosa"
python3 scripts/plant_mgmt_cli.py lookup care "basil"
python3 scripts/plant_mgmt_cli.py lookup species "Ocimum basilicum"
```

Lookup cascade:

1. Trefle
2. Perenual
3. OpenPlantbook
4. Tavily

Lookup results are cached in `$PLANT_DATA_DIR/lookup_cache.json`.

### 6. Setup, validation, and recovery

Use these for initialization, migration, or diagnosis:

```bash
python3 scripts/plant_mgmt_cli.py init [--force]
python3 scripts/plant_mgmt_cli.py init --from-existing /path/to/source
python3 scripts/plant_mgmt_cli.py migrate /path/to/source
python3 scripts/plant_mgmt_cli.py validate
python3 scripts/plant_mgmt_cli.py check
python3 scripts/plant_mgmt_cli.py reminders reset
python3 scripts/plant_mgmt_cli.py reminders repair
```

Validated reads of `reminder_state.json` are self-healing. If the file is still in a recoverable legacy shape, normal runtime reads plus `validate` and `check` rewrite it to the current v2 schema and keep a `.bak` copy of the pre-repair file. Use `reminders repair` when you want to run that normalization explicitly.

Reminder task IDs are rule-scoped and may also include a program ID:

- `watering_check:watering_profiles:plant_001`
- `neem_treatment:pest_recurring_programs:plant_001:neem_cycle`

## Command Contract

Use this form for all commands:

```bash
python3 scripts/plant_mgmt_cli.py <command> [subcommand] [options]
python3 scripts/plant_mgmt_cli.py --json <command> [subcommand] [options]
```

For rarer commands or uncommon option combinations, use the built-in CLI help:

```bash
python3 scripts/plant_mgmt_cli.py --help
python3 scripts/plant_mgmt_cli.py <command> --help
python3 scripts/plant_mgmt_cli.py <command> <subcommand> --help
```

## Data Model Notes

- `plants.json` is the registry source of truth.
- `locations.json`, `microzones.json`, and `irrigation_systems.json` provide environmental context.
- Each profile file stores one profile object per plant by default.
- `care_rules.json` contains generic evaluator bindings between rule engines, profile families, and task behavior.
- `pest_profiles.json` can contain `recurringPrograms` such as neem cycles or other preventive/treatment routines.
- `products.json` stores owned plant-care products, target issue tags, and optional photo paths.
- `reminder_state.json` tracks active and historical tasks.
- `events.json` records care history.

## Troubleshooting

- Missing dependency error: install `scripts/requirements.txt` in the host Python environment.
- Validation error on write: inspect the JSON schema named in the error and correct the command payload.
- Legacy reminder-state validation failure: rerun `validate` or `check`; recoverable `reminder_state.json` payloads now self-heal automatically and leave a `.bak` snapshot.
- Empty eval result: check that plants are active, profiles exist, and the relevant care rules are enabled.
- Unexpected reminder still open: run `eval run` again; the evaluator now closes tasks that are no longer due.
