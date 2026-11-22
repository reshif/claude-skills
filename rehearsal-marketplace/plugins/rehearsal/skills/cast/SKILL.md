---
name: cast
description: Cast the rehearsal's critics — user, stakeholder, service and adversary personas built from facts in the world store, weighted by past calibration. Part of the rehearse flow.
---

# Cast the actors

Decide who acts in this world (the ontology), then create 4–8 personas. Each persona must be **grounded**: it cites the fact ids that justify its goals and concerns. A persona with nothing to cite is invented; leave it out.

CLI: see the `rehearse` skill.

## 1. Read the world

`rehearse world query --run <run>` (respects the run's as-of date for backtests). Read `.rehearsal/scores.json` if it exists: `weights.by_role` lowers the weight of roles that predicted badly before.

## 2. Pick the cast

Choose only roles the facts support. A typical cast:

| Role | Examples | Grounded in |
|---|---|---|
| `user` | power admin, first-time admin, impatient admin | analytics, support tickets |
| `stakeholder` | support lead, security, ops/SRE, PM, compliance | incidents, policies, decisions |
| `service` | one per affected service from anatomy | dependencies, limits, incidents |
| `adversary` | external attacker, malicious insider, abuser | the data and access the change exposes |

Always include at least one stakeholder, one service and one adversary when the facts allow. Stay within the budget (default 8, `rehearse` will refuse more).

## 3. Write them

One JSON object per persona:

```json
{"id": "support-lead", "role": "stakeholder", "name": "Support lead",
 "goals": ["fewer 'where is my export' tickets"],
 "concerns": ["admins can't tell if an export is running"],
 "voice": "practical, quotes ticket volumes",
 "grounded_in": ["F2", "F9"]}
```

`id` is lowercase-with-dashes. `weight` (0–1) is filled from calibration automatically; set it only to override. Save with `rehearse cast add <run> --file -` (JSON list or JSON lines).

Tell the user the cast in one line (roles and names).
