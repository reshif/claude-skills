---
name: mutation-score
description: Measure how good a poptest suite is by planting small faults in a Python target (mutation testing) and counting how many the cases and the simulated users catch; report detection power per approach and the kinds of fault the suite is blind to, then close the gaps. Use for "can I trust these tests", "how good is the suite", "we found nothing, is that real", "what are we missing".
---

# Mutation score: testing the tests

"The run was clean" means little until you know what the suite would have caught. This plants one small fault at a time in a copy of the target (a flipped comparison, a removed line, a number off by one, a condition forced true or false, an and/or swap, a dropped `not`, a return value removed), runs the suite against each faulty copy, and counts. CLI path: the `poptest` skill.

## Requirements

A target whose logic is in a **Python source file that poptest can copy**. The original files are never changed: each fault goes into a copy.

| Target | What to pass | How the faulty copy is run |
|---|---|---|
| `python` adapter | nothing (the entry file), or `--file` for the file that holds the logic (for example when the entry is a wrapper) | the folder is copied, the faulty file swapped in, the entry loaded from the copy |
| `http` adapter with a `start` command | `--file path/to/service.py` (required) | the folder holding that file is copied, the faulty file swapped in, and the **same start command** is launched on the copy: the working directory and any command argument or `env` value pointing into that folder are redirected |
| `cli` adapter | `--file path/to/program.py` (required) | as for http |

- `--file` is looked up in the project folder, the current folder and the target's folder.
- If the command runs from a folder above the file (a repo root, a package), name that folder so that it is what gets copied: `"mutate": {"root": "../service"}` in `poptest.json` (relative to the project; it must contain the file). `runs/`, `.git`, `node_modules` and virtualenvs are not copied.
- With a fixed `port` or `tools_port` the faulty copies run one at a time; with `{port}` they run in parallel (`--jobs`).
- **Not possible:** a target with no Python source to change (a compiled or remote service, another language), an http target that poptest does not start itself (a bare URL), and faults in prompts or models. Say so rather than report nothing; for those, compare releases instead (`compare-releases`).

The unmodified target should pass the suite first (problems it already shows are not counted as catches). If the target has declared noise replies they are handled for every faulty copy as in a normal run.

## Run

```
poptest mutate --n 40
poptest mutate --n 60 --approaches cases,population --budget 600 --reps 2 -v
poptest mutate --file ../service/server.py --n 30        # an http or cli target
```

Each faulty copy runs in its own process with a time limit; one that hangs counts as caught. Output: `runs/<name>/mutation.md` and `mutation.json`.

## Read

- **Detection power** per approach: faults caught out of faults planted. Compare written cases with simulated users on the same faults.
- **By kind of fault**: which kinds slip through.
- **Faults no approach caught**: file line and source text for each.

## Close the gaps

For each missed fault, open the line and decide:

1. **Harmless**: the changed code cannot change behaviour (a default never used, a display-only limit). Note it and move on. Some of every batch are like this; 100% is not the goal.
2. **A situation no case creates**: write the case that reaches that line with the fault mattering (`generate-cases`). Typical: the far side of a limit, a second user, a second window, a state nobody set up.
3. **A result no check looks at**: the faulty behaviour happened in some conversation but nothing compared it with the truth. Add a fact or an invariant (`write-rules`). Typical: a stated number or status with no fact rule.

Rerun with the same `--seed` to confirm the fault is now caught, then with a new seed for a fresh sample.

## Report to the person

Detection power per approach, the kinds of fault most often missed, how many misses were harmless versus real gaps, what you added, and the number after the additions. State the limit: this is power against small code faults in that file, measured on this suite.
