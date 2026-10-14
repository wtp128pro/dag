# Dag — a personal Claude Code marketplace

A [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
hosting reusable skills. Add it once, then install any plugin from it.

> **Marketplace name:** `dag` · **Repo:** `wtp128pro/dag`

## Plugins

| Plugin | Version | Description | Invoke |
|--------|---------|-------------|--------|
| [`dag`](plugins/dag) | 1.15.0 | Gated, multi-phase task execution — **formally enforced** (JSON Schemas + FSM + validator; TLA+ TLC-machine-checked, Alloy machine-checked), **universal Socratic dialogue** with **socratic-guardrail enforcement** (**offline I35–I40**: bounded Socratic dialogue transcript, consequential-gap ask-first, non-goal solicitation, anti-drift), **cross-repo orchestrator conduct** (18 lazy-loaded rules distilled from 92 learnings across three stores, a **continuation contract** + **RESUME banner**), atomic work-unit DAG, budget-capped subagents, independent adversarial verification (**default distinct-lens panel-of-3 on high-stakes units, coverage-first, loop-until-dry**) with **offline I41 panel-dissent accounting** and **I42 evidence-digest integrity**, **enforced verification currency** (**offline I43/I44/N-I45/I46/N-I47**: an executed unit's aggregated `verify.json` must adjudicate the iteration its debrief claims, sign-off obliges every executed unit to carry a current verify at any phase — with a loud per-unit `accepted_incomplete` override — version-skew visibility, non-converged `PASS`, and a ledger-desync advisory; `validator_version` re-stamps on phase advance so a run cannot escape the invariant it ships; honest ceiling filed as **Limitation AA** — completeness is made *legible*, never *true*), **frozen per-unit case sets** (**offline I48**, eight clauses: a brief may freeze a `case_set[]` of named checks carrying the observations each must be able to make and the observations it forbids, and a debrief must discharge every entry back with an `outcome`, its `evidence` and a `non_vacuity` statement; the evidence floor is derived from `check_form` and a command-form row whose counterfactual was never run cannot be `discharged`; version-gated at `validator_version >= 1.13.0`, so archived runs below that stamp are unaffected — completeness/adequacy of a case set stays open as **Limitation AC** boundary (iv)), **drift & autonomy controls** (**offline I49–I54, I56–I59**: a `horizon` record so a dialogue's rejected alternative survives in the artifact, measurable plain-language prose bounds, a **disjoint machine-decision channel** that lets a fully-automatic run reach `DONE` without forging a human attestation — the set's one declared **REVISES** — a bounded per-unit projection contract for the orchestrator's context, a directive ledger so an explicit maintainer request outranks self-generated investigation, a **recomputed** deliverable clock, a cap on consecutive non-shipping units per requirement, an exit-neutral run-composition NOTE, and re-sequencing eligibility with the pre-amendment wave map that makes it decidable; two mechanisms are **deferred with stated adoption triggers** rather than quietly dropped), **blast-radius checks** (**offline I60–I64** plus an exit-neutral **N-I65** summary: each unit declares a write frame; the file footprint captured for it is checked against that frame, and the out-of-frame consumers an impact scan finds in it are settled by the existing guardrail lens; at Phase 8 `integrate.py` re-runs every passed command-form check at the tip and runs the project's declared regression commands and censuses at base and tip — checks over declared, visible surfaces only, with integration blindness beyond them left open as **Limitation AE**), **bounded self-learning loops** (`all`/`U0X`/`tag:` selectors enforced), **bounded mid-run graph amendments** (fuel-budgeted, tamper-evident, machine-checked quiescence), anti-hallucination evidence standards, **large-dataset map-reduce partitioning**, a **mechanical Phase-8 sign-off gate**, durable **per-unit loop state**, and an **executable HOME-isolated test harness** (both validator backends) | `/dag:dag <task>` |

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
│       │   │   ├── scripts/         # init_run.sh, validate_run.sh/.py, run_tests.sh, run_formal.sh, spec_check.py, frame_match.py, footprint.py, impact_scan.py, integrate.py
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
