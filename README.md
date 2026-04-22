# Plant Management Skill

A portable plant registry and reminder engine for AI agents and humans. The skill keeps plant data in JSON files, validates every mutation against schemas, writes atomically, and exposes a single Python CLI for registry changes, events, reminders, evaluation, and species lookup.

## What It Is

This repository is designed to be copied into an agent skill directory or used directly from a normal shell. The AI layer should never modify plant JSON files directly. It should always call the CLI in `scripts/plant_mgmt_cli.py`.

Core responsibilities:

- Plant registry CRUD
- Location, microzone, and irrigation metadata
- Care profile storage
- Product inventory for plant-care supplies
- Event logging
- Reminder state management
- Deterministic care evaluation
- External species and care lookups

## Repository Layout

```text
plant-management-skills/
├── AGENTS.md                Contributor-facing repository contract
├── README.md                Human-facing setup and usage guide
├── _meta.json               Skill package metadata
└── skill/                   Packaged skill root
    ├── SKILL.md             Agent-facing runtime instructions
    ├── schemas/             JSON Schema definitions
    ├── seeds/               Seed JSON files for new installations
    └── scripts/
        ├── plant_mgmt_cli.py    Single CLI entry point
        ├── requirements.txt     Python dependencies
        ├── plant_mgmt/          Python package
        └── tests/               Unit tests
```

The rest of this README describes the packaged skill layout inside `skill/`. If you are working directly from this repository root, prefix repo-local paths with `skill/`.

## Requirements

- Python 3.10+
- A host Python environment with the packages from `scripts/requirements.txt`

Install dependencies into the host environment:

```bash
python3 -m pip install -r scripts/requirements.txt
```

If you prefer a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r scripts/requirements.txt
```

## Environment Variables

| Variable                      | Required | Description                                                     |
| ----------------------------- | -------- | --------------------------------------------------------------- |
| `PLANT_DATA_DIR`              | Yes      | Directory containing the runtime JSON data files                |
| `PLANT_SKILL_DIR`             | No       | Skill root override. Defaults to auto-detection from `scripts/` |
| `PLANT_TIMEZONE`              | No       | IANA timezone override for evaluation                           |
| `PLANT_LOCALE`                | No       | Locale hint for host-side messaging                             |
| `TREFLE_API_KEY`              | No       | Trefle API key                                                  |
| `PERENUAL_API_KEY`            | No       | Perenual API key                                                |
| `OPENPLANTBOOK_CLIENT_ID`     | No       | OpenPlantbook client ID                                         |
| `OPENPLANTBOOK_CLIENT_SECRET` | No       | OpenPlantbook client secret                                     |
| `TAVILY_API_KEY`              | No       | Tavily API key                                                  |

## Quick Start

Set the data directory:

```bash
export PLANT_DATA_DIR=/path/to/plant-data
```

Initialize a new installation:

```bash
python3 scripts/plant_mgmt_cli.py init
python3 scripts/plant_mgmt_cli.py validate
```

Inspect the fresh install:

```bash
python3 scripts/plant_mgmt_cli.py check
python3 scripts/plant_mgmt_cli.py --json eval status
```

Add a location and a plant:

```bash
python3 scripts/plant_mgmt_cli.py locations add --id rear_balcony --name "Rear balcony" --type balcony --indoor-outdoor outdoor
python3 scripts/plant_mgmt_cli.py plants add --name "basilico" --location rear_balcony --species "basil" --scientific-name "Ocimum basilicum"
```

Attach a watering profile:

```bash
python3 scripts/plant_mgmt_cli.py profiles set watering plant_001 --data '{
  "baselineSource": "container basil",
  "seasonalBaseline": {
    "winter": {"level": "very_low", "baseIntervalDays": [12, 18]},
    "spring": {"level": "medium", "baseIntervalDays": [4, 7]},
    "summer": {"level": "high", "baseIntervalDays": [2, 4]},
    "autumn": {"level": "low", "baseIntervalDays": [6, 9]}
  }
}'
```

Preview due work:

```bash
python3 scripts/plant_mgmt_cli.py --json eval run --dry-run
```

## CLI Usage

The only supported invocation format is:

```bash
python3 scripts/plant_mgmt_cli.py <command> [subcommand] [options]
python3 scripts/plant_mgmt_cli.py --json <command> [subcommand] [options]
```

### Data Directory Commands

```bash
python3 scripts/plant_mgmt_cli.py init [--force]
python3 scripts/plant_mgmt_cli.py init --from-existing /path/to/source
python3 scripts/plant_mgmt_cli.py migrate /path/to/source
python3 scripts/plant_mgmt_cli.py validate
python3 scripts/plant_mgmt_cli.py check
```

Behavior:

- `init` copies seed files into `PLANT_DATA_DIR` and validates the result
- `migrate` imports recognized files from an existing directory and initializes missing files from seeds
- `validate` and `check` auto-repair recoverable legacy `reminder_state.json` payloads before reporting results
- `check` reports missing files and validation results

### Plant Registry

```bash
python3 scripts/plant_mgmt_cli.py plants list [--status active|recovering|archived|dead] [--location <locationId>]
python3 scripts/plant_mgmt_cli.py plants get <plantId>
python3 scripts/plant_mgmt_cli.py plants add --name <name> --location <locationId> [--species <name>] [--scientific-name <name>] [--sublocation <microzoneId>] [--irrigation-mode manual|automatic|mixed] [--irrigation-system <systemId>] [--attached-to-irrigation] [--indoor-outdoor indoor|outdoor] [--notes <text>]
python3 scripts/plant_mgmt_cli.py plants update <plantId> --data '{"status":"recovering"}'
python3 scripts/plant_mgmt_cli.py plants archive <plantId> [--reason <text>]
python3 scripts/plant_mgmt_cli.py plants move <plantId> --location <locationId> [--sublocation <microzoneId>]
```

### Locations, Microzones, Irrigation

```bash
python3 scripts/plant_mgmt_cli.py locations list
python3 scripts/plant_mgmt_cli.py locations get <locationId>
python3 scripts/plant_mgmt_cli.py locations add --id <id> --name <name> --type balcony|room|other [--indoor-outdoor indoor|outdoor] [--exposure south]
python3 scripts/plant_mgmt_cli.py locations update <locationId> --data '{"notes":"Gets harsh sun after lunch"}'

python3 scripts/plant_mgmt_cli.py microzones list [--location <locationId>]
python3 scripts/plant_mgmt_cli.py microzones add --id <id> --location <locationId> --name <name> [--data '{"lightClass":"high"}']
python3 scripts/plant_mgmt_cli.py microzones update <microzoneId> --data '{"heatLoad":"high"}'

python3 scripts/plant_mgmt_cli.py irrigation list
python3 scripts/plant_mgmt_cli.py irrigation get <systemId>
python3 scripts/plant_mgmt_cli.py irrigation update <systemId> --data '{"enabled":false}'
python3 scripts/plant_mgmt_cli.py irrigation update <systemId> --data '{"autoSchedule":{"cadenceDays":3,"skipOnRain":true}}'
```

Irrigation systems may include an optional `autoSchedule` object. When present on an enabled system, `eval run` logs automatic `watering_confirmed` events for eligible attached plants before normal reminder rules run. Eligible plants must be attached to the system, active or recovering, not listed in `manualExceptionPlantIds`, and not set to `irrigationMode: "manual"`.

`autoSchedule` supports:

- `cadenceDays`: default automatic watering cadence
- `skipOnRain`: skip today's automatic event when supplied weather has `"condition":"rain"`
- `seasonalSchedule`: optional `winter`, `spring`, `summer`, and `autumn` entries with `enabled` and `cadenceDays`

Season entries override the top-level cadence for that season. If a season entry has `"enabled": false`, no automatic watering event is logged during that season.

### Product Inventory

Use `products` to track owned pesticides, fungicides, fertilizers, substrates, tools, and related supplies. Product photos are copied under `media/products/` inside `PLANT_DATA_DIR`, and `photoPath` stores the relative path.

```bash
python3 scripts/plant_mgmt_cli.py products list [--category pesticide] [--target-issue spider_mites]
python3 scripts/plant_mgmt_cli.py products get <productId>
python3 scripts/plant_mgmt_cli.py products add --display-name "Olio di neem BioGarden" --category pesticide --description "Olio di neem puro 100%" --target-issues spider_mites,aphids [--photo-file /path/to/photo.jpg] [--notes "..."]
python3 scripts/plant_mgmt_cli.py products update <productId> --description "Updated label notes" --target-issues spider_mites,aphids
python3 scripts/plant_mgmt_cli.py products update <productId> --data '{"notes":"Use in evening only"}'
python3 scripts/plant_mgmt_cli.py products remove <productId>
```

Product categories are `pesticide`, `fungicide`, `fertilizer`, `soil_amendment`, `substrate`, `tool`, and `other`.

Canonical `targetIssues` keys are: `spider_mites`, `aphids`, `whitefly`, `thrips`, `scale_insects`, `mealybugs`, `fungus_gnats`, `powdery_mildew`, `downy_mildew`, `root_rot`, `leaf_spot`, `rust`, `iron_deficiency`, `nitrogen_deficiency`, `potassium_deficiency`, `magnesium_deficiency`, `sunburn`, `frost_damage`, `overwatering`, `underwatering`. Add new issue keys only as snake_case English terms.

### Profiles

Supported profile families:

- `watering`
- `fertilization`
- `repotting`
- `pest`
- `maintenance`
- `healthcheck`

Profile linking rules:

- Each profile object belongs to one plant
- If `profileId` is omitted, it defaults to the plant ID
- The matching field on the plant record is updated automatically when a profile is set or removed

Examples:

```bash
python3 scripts/plant_mgmt_cli.py profiles list watering
python3 scripts/plant_mgmt_cli.py profiles get watering plant_001
python3 scripts/plant_mgmt_cli.py profiles set fertilization plant_001 --data '{"activeMonths":[3,4,5,6,7,8,9],"cadenceDays":[21,30]}'
python3 scripts/plant_mgmt_cli.py profiles remove fertilization plant_001
```

### Events

Use `events log` when the user performed care but there is no reminder task to confirm.

```bash
python3 scripts/plant_mgmt_cli.py events log --type watering_confirmed --plant plant_001 --scope "manual watering"
python3 scripts/plant_mgmt_cli.py events log --type neem_confirmed --plant plant_001 --effective-date 2026-03-18 --effective-precision part_of_day --effective-part-of-day morning
python3 scripts/plant_mgmt_cli.py events log --type watering_confirmed --plant plant_001 --effective-datetime 2026-03-18T07:30:00 --effective-precision exact
python3 scripts/plant_mgmt_cli.py events list [--plant plant_001] [--type watering_confirmed] [--since 2026-03-01] [--limit 20]
python3 scripts/plant_mgmt_cli.py events last plant_001 [--type watering_confirmed]
```

The event logger now validates plant and location references before writing. Use `--effective-date`, `--effective-datetime`, `--effective-precision`, and `--effective-part-of-day` when the action happened earlier than the recording time.

### Reminders

Use `reminders confirm` when the user is confirming an existing reminder task. This command logs the canonical care event from task metadata, so custom recurring programs work without Python changes.

```bash
python3 scripts/plant_mgmt_cli.py reminders list [--status open|done|expired|cancelled]
python3 scripts/plant_mgmt_cli.py reminders get <taskId>
python3 scripts/plant_mgmt_cli.py reminders confirm <taskId> [--details "Watered thoroughly"]
python3 scripts/plant_mgmt_cli.py reminders confirm <taskId> --details "Neem applied this morning" --effective-date 2026-03-18 --effective-precision part_of_day --effective-part-of-day morning
python3 scripts/plant_mgmt_cli.py reminders cancel <taskId> [--reason "Heavy rain made this irrelevant"]
python3 scripts/plant_mgmt_cli.py reminders reset
python3 scripts/plant_mgmt_cli.py reminders repair
```

Validated reads of `reminder_state.json` are self-healing. If the file is in a recoverable legacy shape, normal runtime reads plus `validate` and `check` rewrite it to the current v2 schema and keep a `.bak` copy of the pre-repair file. Use `reminders repair` when you want to run the same normalization explicitly.

Reminder task IDs are rule-scoped and may also include a program ID:

- `watering_check:watering_profiles:plant_001`
- `neem_treatment:pest_recurring_programs:plant_001:neem_cycle`

### Evaluation

```bash
python3 scripts/plant_mgmt_cli.py --json eval run [--weather '{"tempC":32,"humidity":35,"condition":"sunny"}'] [--dry-run]
python3 scripts/plant_mgmt_cli.py --json eval status
python3 scripts/plant_mgmt_cli.py --json eval run | python3 scripts/plant_mgmt_cli.py eval render
python3 scripts/plant_mgmt_cli.py --json eval run | python3 scripts/plant_mgmt_cli.py --json eval render
```

`eval run` returns:

- `actions`: due tasks that should be pushed right now
- `suppressedActions`: due tasks blocked by push policy
- `noAction`: evaluated plants that are not due
- `stateChanges`: tasks opened, updated, or closed
- `autoIrrigation`: automatic watering confirmations emitted or skipped before rule evaluation
- `summary`: aggregate counts

The evaluator now closes open reminder tasks that are no longer due. Automatic irrigation events intentionally use only prior auto-irrigation events as their schedule anchor; manual watering events do not shift the system schedule.
`eval render` converts the `actions` array into a localized reminder message using `PLANT_LOCALE` / `config.locale` (supported: `en`, `it`; unsupported locales fall back to English). Without `--json` it prints raw text, and with `--json` it returns `{"message": ...}`.

Seed behavior:

- Generic watering checks are enabled by default
- Generic fertilization checks are enabled by default
- Generic pest recurring-program evaluation is enabled by default
- Neem is now modeled as a recurring program inside `pest_profiles.json`, not as a special evaluator rule

### Lookup

```bash
python3 scripts/plant_mgmt_cli.py lookup search "monstera deliciosa"
python3 scripts/plant_mgmt_cli.py lookup care "basil"
python3 scripts/plant_mgmt_cli.py lookup species "Ocimum basilicum"
```

Lookup order:

1. Trefle
2. Perenual
3. OpenPlantbook
4. Tavily

Lookup results are cached in `lookup_cache.json` inside `PLANT_DATA_DIR`.

## Architecture

### Data Integrity

All writes go through `store.write()`:

- validates against the matching schema
- writes to a temp file in the same directory
- replaces atomically
- creates a `.bak` copy before overwriting existing files

### Schemas

Each runtime data file has a matching schema in `schemas/`:

- `plants.json`
- `locations.json`
- `microzones.json`
- `irrigation_systems.json`
- `watering_profiles.json`
- `fertilization_profiles.json`
- `repotting_profiles.json`
- `pest_profiles.json`
- `products.json`
- `maintenance_profiles.json`
- `healthcheck_profiles.json`
- `care_rules.json`
- `reminder_state.json`
- `events.json`
- `config.json`

### Runtime Files

Important files in `PLANT_DATA_DIR`:

- `plants.json`: plant registry and denormalized profile references
- `care_rules.json`: enabled/disabled evaluation rules
- `reminder_state.json`: open and historical reminder tasks
- `events.json`: care history
- `products.json`: owned plant-care products and target issue tags
- `lookup_cache.json`: cached external lookup results

## Agent Usage Guidance

If this repo is copied into a skill directory:

- The agent should read `SKILL.md`
- The agent should call the CLI, not modify JSON directly
- `README.md` is for humans and setup, not the agent contract

## Typical Workflows

### Confirming a User Action

If the user says they completed a reminder:

```bash
python3 scripts/plant_mgmt_cli.py reminders confirm watering_check:watering_profiles:plant_001 --details "Watered thoroughly"
```

If the user reports care that was not tied to an open reminder:

```bash
python3 scripts/plant_mgmt_cli.py events log --type watering_confirmed --plant plant_001 --scope "manual watering"
```

### Onboarding a New Plant

1. Create the location if needed
2. Add the plant
3. Create a watering profile
4. Add fertilization or other profiles if known
5. Run `eval run --dry-run` to confirm the plant participates in evaluation

### Migrating Existing Data

Use:

```bash
python3 scripts/plant_mgmt_cli.py migrate /path/to/source
```

Migration behavior:

- imports recognized required files
- validates imported data
- copies seed files for missing required files
- copies `intake/` if present

## Testing

Syntax check:

```bash
python3 -m py_compile scripts/plant_mgmt_cli.py scripts/plant_mgmt/*.py scripts/tests/*.py
```

Unit tests:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
```

Current test coverage focuses on:

- profile ID linking
- canonical reminder confirmation events
- evaluation closing stale tasks
- migration initializing missing required files

## Limitations

- Weather data is host-provided. The evaluator accepts it but does not fetch it.
- Scheduling and message delivery stay outside the skill.
- The lookup layer depends on external APIs and host-provided credentials.
- The migration command assumes compatible JSON file shapes; it is not a full legacy-format transformer.

## Troubleshooting

### `ModuleNotFoundError`

Install the dependencies:

```bash
python3 -m pip install -r scripts/requirements.txt
```

### Validation errors

Run:

```bash
python3 scripts/plant_mgmt_cli.py validate
python3 scripts/plant_mgmt_cli.py check
```

Recoverable legacy `reminder_state.json` payloads now self-heal during validated reads, `validate`, and `check`, with the previous file saved as `reminder_state.json.bak`. If validation still fails after that, inspect the schema named in the error output.

### Empty evaluation result

Check:

- the plant is `active` or `recovering`
- the plant has the relevant profile
- the matching care rule is enabled
- the latest event history is what you think it is

## License

MIT
