# Dag — a personal Claude Code marketplace

A [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
hosting reusable skills. Add it once, then install any plugin from it.

> **Marketplace name:** `dag` · **Repo:** `wtp128pro/dag`

## Plugins

| Plugin | Version | Description | Invoke |
|--------|---------|-------------|--------|
| [`dag`](plugins/dag) | 1.6.0 | Gated, multi-phase task execution — **formally enforced** (JSON Schemas + FSM + validator; TLA+ TLC-machine-checked, Alloy machine-checked), **universal Socratic dialogue**, atomic work-unit DAG, budget-capped subagents, independent adversarial verification (**default distinct-lens panel-of-3 on high-stakes units, coverage-first, loop-until-dry**), **bounded self-learning loops** (`all`/`U0X`/`tag:` selectors enforced), **bounded mid-run graph amendments** (fuel-budgeted, tamper-evident, machine-checked quiescence), anti-hallucination evidence standards, **large-dataset map-reduce partitioning**, a **mechanical Phase-8 sign-off gate**, durable **per-unit loop state**, and an **executable HOME-isolated test harness** (both validator backends) | `/dag:dag <task>` |

### Skills in the `dag` plugin

The plugin ships two skills — full details are in the
[plugin README](plugins/dag/README.md):

- **`dag:dag`** — the gated multi-phase execution pipeline described above.
  Invoke `/dag:dag <task>`.
- **`dag:personas`** — curate the reusable Dag personas that the pipeline's
  Phase 1 discovers: **list / add / edit / remove** persona definitions across the project
  library (`.dag/personas/`), your personal library (`~/.claude/dag/personas/`),
  and the built-in catalog, through a short Socratic dialogue. Invoke `/dag:personas`.

## Install

### 1. Add the marketplace

Inside Claude Code:

```
/plugin marketplace add wtp128pro/dag
```

Or from your shell (non-interactive):

```bash
claude plugin marketplace add wtp128pro/dag
```

Other accepted sources: a full git URL (`https://github.com/wtp128pro/dag.git`),
SSH (`git@github.com:wtp128pro/dag.git`), or a local path for testing
(`/plugin marketplace add ./dag`).

### 2. Install a plugin

```
/plugin install dag@dag
```

The syntax is `plugin-name@marketplace-name`. Run `/plugin` for the interactive manager,
or `/plugin list` to see what's installed.

### 3. Use it

Plugin skills are namespaced `/<plugin>:<skill>`:

```
/dag:dag Build me a rate limiter with tests
```

Run it with no argument and it will ask you for the task.

## Configure via settings.json (team / non-interactive setup)

```json
{
  "extraKnownMarketplaces": {
    "dag": {
      "source": { "source": "github", "repo": "wtp128pro/dag" }
    }
  },
  "enabledPlugins": {
    "dag@dag": true
  }
}
```

## Updating

When a new version is published to this repo, refresh the marketplace catalog and reload:

```
/plugin marketplace update dag
/reload-plugins
```

There is no `/plugin update` command; marketplace plugins with auto-update enabled pick up the new
version once the catalog is refreshed (otherwise re-enable/re-install from the `/plugin` menu).

## Repository layout

```
dag/
├── .claude-plugin/
│   └── marketplace.json           # marketplace manifest (lists plugins)
├── plugins/
│   └── dag/
│       ├── .claude-plugin/
│       │   └── plugin.json         # plugin manifest (name, version, …)
│       ├── skills/
│       │   ├── dag/        # the pipeline skill in its entirety
│       │   │   ├── SKILL.md
│       │   │   ├── DESIGN.md
│       │   │   ├── references/
│       │   │   ├── schemas/         # JSON Schemas (artifact sidecars)
│       │   │   ├── spec/            # SSR registry: fsm.json, invariants.json (dev-time drift source)
│       │   │   ├── templates/
│       │   │   ├── scripts/         # init_run.sh, validate_run.sh/.py, run_tests.sh, run_formal.sh, spec_check.py
│       │   │   └── formal/          # TLA+ / Alloy formal models (Pipeline, WorkGraph, Amendment) + AlloyRun.java
│       │   └── personas/        # manages reusable persona JSON files
│       │       └── SKILL.md
│       ├── README.md
│       └── CHANGELOG.md
├── wiki/                           # in-repo project wiki (16 pages; the wiki's home lives here)
├── CHANGELOG.md
├── LICENSE                         # MIT
└── README.md
```

## Versioning

Each plugin is independently versioned with [SemVer](https://semver.org) in its
`plugin.json` and mirrored in the marketplace manifest. See the top-level
[CHANGELOG.md](CHANGELOG.md) and each plugin's `CHANGELOG.md`.

## License

[MIT](LICENSE) © 2026 wtp128pro

## Trademarks & affiliation

Not affiliated with, endorsed by, or sponsored by Anthropic. "Claude" and "Claude Code" are
trademarks of Anthropic, used here nominatively only to describe compatibility. All other product
names are the property of their respective owners.

## Provenance

Built with heavy AI assistance (Claude Code). Design, direction, review, and curation by
`wtp128pro`, who is responsible for what ships here. The formal-verification claims aren't asserted
on faith — the TLA+ model check is independently reproducible in seconds: see
[**Verify the formal claims yourself**](plugins/dag/README.md#verify-the-formal-claims-yourself)
in the plugin README, and [`references/formal-models.md`](plugins/dag/skills/dag/references/formal-models.md)
for the full transcript and traceability.
