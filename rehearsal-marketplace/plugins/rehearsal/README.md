# rehearsal

This is a pre-mortem stage for a software factory. Before a big or risky request is built, grounded critics (users, stakeholders, services and adversaries, all built from your real tickets, incidents and code) attack each variant. An analyst then writes an evidence-backed outcome report. A human picks a variant at the gate, and its unhappy paths become acceptance tests. After release, calibration scores every prediction against what actually happened.

Start with `/rehearsal:rehearse <request>`, or say "rehearse this before we build it". To find out whether rehearsals pay off for you, run "backtest the rehearsal on <past feature>" first.

The CLI is `bin/rehearse.py` and uses only the Python standard library. Graphiti is optional; see `infra/GRAPHITI.md`. The marketplace root's README has the full guide.
