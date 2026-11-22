---
description: Measure how many planted faults the poptest suite catches, and which kinds it misses
argument-hint: [--n 40] [--approaches cases,population] [--file path.py]
---

Use the `mutation-score` skill from this plugin in the current poptest project. Options: $ARGUMENTS

After the run, go through the faults nobody caught and say for each whether it is harmless, a missing case, or a missing check.
