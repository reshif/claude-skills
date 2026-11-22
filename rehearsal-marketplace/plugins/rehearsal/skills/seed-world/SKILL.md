---
name: seed-world
description: Seed the rehearsal's temporal fact store with what the codebase and the organisation already know about a request — affected services from anatomy or the code, plus tickets, incidents, analytics notes and decisions. Part of the rehearse flow; also use to refresh the world before a run.
---

# Seed the world

The world is a small **temporal fact store** in `.rehearsal/world/`: entities plus facts of the form *subject —predicate→ object*, each with a `source` and a `valid_from` date. Facts are expired, never deleted, so a backtest can see the world as it was. Critics may only cite facts that are in it, so what you seed decides how grounded the rehearsal is.

CLI: see the `rehearse` skill for where `rehearse` lives.

## 1. Code world (what the change touches)

- If the **anatomy** plugin or its map is available, use it to list affected modules/services, their owners, and the blast radius of the request. Otherwise use Grep/Glob and `git log` on likely paths.
- For each affected service or module: `rehearse world add-entity --name <name> --type service|module --source anatomy` (or `file:<path>`).
- Add the facts that matter for risk: dependencies, known limits, past changes. Example:
  `rehearse world add-fact --subject export-worker --predicate depends_on --object reports-db --source anatomy`

## 2. Domain world (what reality already told us)

Pull evidence about this area, newest first, from whatever is connected: issue tracker (Jira/Linear/GitHub issues), incidents (Sentry/PagerDuty/postmortems in the repo), support tickets, analytics notes, ADRs, past PR review comments. Use connected MCP tools if present; otherwise ask the user to paste or point at files. Search is cheap; stop at ~30–60 facts.

Record each as a fact with a real `source` and the date it became true:
`rehearse world add-fact --subject admins --predicate complain_about --object "not knowing when exports finish" --source ticket:SUP-77 --valid-from 2026-06-01`

For many facts at once, write JSON lines (`subject, predicate, object, source, valid_from`) and use `--file -`.

Useful predicates: `had_incident`, `complain_about`, `uses`, `depends_on`, `owned_by`, `limit_is`, `decided`, `must_comply_with`, `segment_size`, `usage_pattern`.

## 3. Keep it true

- When something stops being true (a limit raised, an incident fixed): `rehearse world expire F7 --on <date> --reason "..."`.
- One fact per claim; the object says the claim in plain words.
- No speculation: a fact you inferred is not a fact. If it matters, make it an open question for the report instead.

## Optional: Graphiti

If Graphiti MCP tools are available (see the plugin README for the docker-compose), also send each source document as an episode with `add_episode` (group id = the repo name) and use its search to find related facts you missed. The local store stays the source of truth that the CLI validates against.

Finish with `rehearse world stats` and give the user one line: how many facts, from which sources.
