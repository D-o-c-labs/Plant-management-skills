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

Use this skill to manage household plants through a validated Python CLI. The AI handles judgment and messaging. The Python code handles data integrity, schema validation, reminder state, and deterministic evaluation.

## Rules

- Never edit JSON files in `$PLANT_DATA_DIR` directly.
- Always run commands from the skill root with `python3 scripts/plant_mgmt_cli.py ...`.
- If the CLI reports missing dependencies, install `scripts/requirements.txt` into the host Python environment before continuing.
- Prefer `--json` output when you need to reason over command results.

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

## Command Contract

Always use this form:

```bash
python3 scripts/plant_mgmt_cli.py <command> [subcommand] [options]
python3 scripts/plant_mgmt_cli.py --json <command> [subcommand] [options]
```

### Data directory

```bash
python3 scripts/plant_mgmt_cli.py init [--force]
python3 scripts/plant_mgmt_cli.py init --from-existing /path/to/source
python3 scripts/plant_mgmt_cli.py validate
python3 scripts/plant_mgmt_cli.py check
python3 scripts/plant_mgmt_cli.py migrate /path/to/source
```

### Plants

```bash
python3 scripts/plant_mgmt_cli.py plants list [--status active|recovering|archived|dead] [--location <locationId>]
python3 scripts/plant_mgmt_cli.py plants get <plantId>
python3 scripts/plant_mgmt_cli.py plants add --name "basilico" --location rear_balcony [--species "basil"] [--scientific-name "Ocimum basilicum"] [--sublocation rear_balcony_kitchen] [--irrigation-mode manual|automatic|mixed] [--irrigation-system rear_balcony_irrigation] [--indoor-outdoor indoor|outdoor] [--attached-to-irrigation] [--notes "..."]
python3 scripts/plant_mgmt_cli.py plants update <plantId> --data '{"status":"recovering","notes":"Moved out of direct sun"}'
python3 scripts/plant_mgmt_cli.py plants archive <plantId> [--reason "Died from frost"]
python3 scripts/plant_mgmt_cli.py plants move <plantId> --location <locationId> [--sublocation <microzoneId>]
```

### Locations, microzones, irrigation

```bash
python3 scripts/plant_mgmt_cli.py locations list
python3 scripts/plant_mgmt_cli.py locations get <locationId>
python3 scripts/plant_mgmt_cli.py locations add --id rear_balcony --name "Rear balcony" --type balcony [--indoor-outdoor outdoor] [--exposure south]
python3 scripts/plant_mgmt_cli.py locations update <locationId> --data '{"notes":"Hot after 14:00"}'

python3 scripts/plant_mgmt_cli.py microzones list [--location <locationId>]
python3 scripts/plant_mgmt_cli.py microzones add --id rear_balcony_wall --location rear_balcony --name "Against wall" [--data '{"lightClass":"high"}']
python3 scripts/plant_mgmt_cli.py microzones update <microzoneId> --data '{"heatLoad":"high"}'

python3 scripts/plant_mgmt_cli.py irrigation list
python3 scripts/plant_mgmt_cli.py irrigation get <systemId>
python3 scripts/plant_mgmt_cli.py irrigation update <systemId> --data '{"enabled":false}'
```

### Profiles

Profile IDs are supported, but by default a profile’s `profileId` equals its `plantId`. The plant record stores the linked profile ID in fields like `wateringProfileId`.

```bash
python3 scripts/plant_mgmt_cli.py profiles list watering [--plant <plantId>]
python3 scripts/plant_mgmt_cli.py profiles get watering <plantId-or-profileId>
python3 scripts/plant_mgmt_cli.py profiles set watering <plantId> --data '{"baselineSource":"container citrus","seasonalBaseline":{"winter":{"level":"low","baseIntervalDays":[10,14]},"spring":{"level":"medium","baseIntervalDays":[5,8]},"summer":{"level":"high","baseIntervalDays":[2,4]},"autumn":{"level":"medium","baseIntervalDays":[6,9]}}}'
python3 scripts/plant_mgmt_cli.py profiles remove watering <plantId-or-profileId>
```

Supported profile types: `watering`, `fertilization`, `repotting`, `pest`, `maintenance`, `healthcheck`.

### Events

Use `events log` when the user reports an action and there is no reminder task to confirm.

```bash
python3 scripts/plant_mgmt_cli.py events log --type watering_confirmed --plant plant_001 --scope "manual watering" [--details '{"method":"watering_can"}']
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

### Reminders

Use `reminders confirm` when the user is confirming an existing reminder task. This command automatically logs the canonical care event for the task type.

```bash
python3 scripts/plant_mgmt_cli.py reminders list [--status open|done|expired|cancelled]
python3 scripts/plant_mgmt_cli.py reminders get <taskId>
python3 scripts/plant_mgmt_cli.py reminders confirm <taskId> [--details "Watered thoroughly"]
python3 scripts/plant_mgmt_cli.py reminders cancel <taskId> [--reason "Heavy rain made this irrelevant"]
python3 scripts/plant_mgmt_cli.py reminders reset
```

### Evaluation

```bash
python3 scripts/plant_mgmt_cli.py --json eval run [--weather '{"tempC":32,"humidity":35,"condition":"sunny"}'] [--dry-run]
python3 scripts/plant_mgmt_cli.py --json eval status
```

`eval run` returns:

- `actions`: due items that should be pushed now
- `suppressedActions`: due items blocked by push policy
- `noAction`: evaluated plants that are not due
- `stateChanges`: tasks opened, updated, or closed by this evaluation
- `summary`: counts

Interpretation:

- `low`: mention casually
- `medium`: worth checking now
- `high`: action should happen soon
- `critical`: urgent and should be phrased directly

Judgment rules:

- Recovering plants: prefer “check first” over “water now”
- Drought-tolerant plants: do not override conservative baselines with generic thirsty-plant advice
- Heat stress and harsh placement can require shade or movement, not just water
- If confidence is limited, ask for a manual check or photo instead of bluffing certainty

Messaging rules:

- One message per evaluation run, not one message per plant
- Group by location and action type
- For 1-2 simple actions, one natural sentence is fine
- For 3+ plants or mixed actions, use a schematic grouped format
- If `actions` is empty, stay quiet unless the user explicitly asked for status

### Lookup

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

## Confirmation Workflow

Use this decision tree:

1. If the user is confirming an open reminder task, run `reminders confirm <taskId>`.
2. If the user is reporting care that did not come from a reminder, run `events log`.
3. If the user’s wording is broad but still actionable, map it deterministically.

Typical free-text mappings:

- “I watered it” / “innaffiato” / “dato acqua” -> `watering_confirmed`
- “It rained” / “ha piovuto” -> `rain_confirmed`
- “Neem done” / “neem fatto” -> `neem_confirmed`
- “Fertilized” / “concimato” -> `fertilization_confirmed`
- “Repotted” / “rinvasato” -> `repotting_confirmed`

If the user says “I watered the balcony”, apply it to the active plants in that location if the target set is obvious. Ask only when the target plants are genuinely ambiguous.

## Onboarding Workflow

When adding new plants:

1. Identify the plant from a photo or text description.
2. Use `lookup search` and `lookup care` if species/care info is unclear.
3. Create the plant record with `plants add`.
4. Create at least a watering profile. Add fertilization or other profiles if you know them.
5. Re-run `eval run --dry-run` to verify the plant is now part of evaluation.

Prefer onboarding one location at a time.

## Data Model Notes

- `plants.json` is the registry source of truth.
- `locations.json`, `microzones.json`, and `irrigation_systems.json` provide environmental context.
- Each profile file stores one profile object per plant by default.
- `care_rules.json` contains the evaluator rules. The seed data ships with generic watering/fertilization rules enabled and a neem rule example disabled.
- `reminder_state.json` tracks active and historical tasks.
- `events.json` records care history.

## Troubleshooting

- Missing dependency error: install `scripts/requirements.txt` in the host Python environment.
- Validation error on write: inspect the JSON schema named in the error and correct the command payload.
- Empty eval result: check that plants are active, profiles exist, and the relevant care rules are enabled.
- Unexpected reminder still open: run `eval run` again; the evaluator now closes tasks that are no longer due.
