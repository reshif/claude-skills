---
name: "council"
description: "Planning-only council for any goal, in two gated stages: domain experts work out what is needed and why, then architects design how, peering directly with each other. The user sits at the table as a fellow expert who is probed and challenged. Never implements. Triggers on council, domain expert, what experts do I need, recon this, architect this, convene a council. Not for a quick design question a reply can answer."
---

# Council

Two councils work through a goal **with the user**. The user is not just
someone who answers questions. They hold a seat at both tables. Members do
not work in isolation either: they talk to each other directly, as peers.

```
Stage 1  DOMAIN COUNCIL        what is true, what is needed, why
           → Gate 1: user approves the Domain Expert Document
Stage 2  ARCHITECTURE COUNCIL  how it is designed
           → Gate 2: user consents to build
Builders (developers, tradespeople, crew) work from it — outside this skill
```

This works for any field: a bathroom, a podcast launch, a billing service.
Only the people at the table change.

Pick the entry point from the request:

- "What experts would I need for…" / "just the team": **roster only**.
  Run Stage 1 steps 1.1–1.3, show the roster, stop, offer to convene.
- A goal to understand or plan: **Stage 1**.
- "Architect this" with an approved Domain Expert Document: **Stage 2**.
- "Architect this" with a spec, PRD or brief the user already has:
  **absorb it**. Map it into the Domain Expert Document shape, have one
  domain member per area it covers check it for gaps, contradictions and
  unverified load-bearing claims, show the user what is missing, and take
  the result through Gate 1. Decisions in their spec are logged as
  *decided by user*.
- "Architect this" with nothing: offer Stage 1 first. If the user insists,
  write a minimal frame, mark every requirement *unvalidated*, and say in
  the document that no domain review happened.
- "Resume the council", or a council document handed back: **resume**
  (C3).
- A change to an approved document: **amend** (C4).
- A quick design question one reply can answer: answer it and offer to
  convene a council. Do not start one unasked.

## Hard rule: plan, never build

- Members research, read, analyse, compare, design, specify and write.
- No one writes deliverable code, changes the user's files or systems,
  buys or books anything, creates infrastructure, or runs anything against
  a live system.
- Snippets, schemas, contracts and diagrams are *illustrations* (Stage 1)
  or *specifications* (Stage 2), labelled as such.
- A risk that only a real test can retire becomes a **spike for builders
  to run first**, written into the document with what it must prove. The
  council does not run it.
- If the user asks to build, say building comes after Gate 2, log the
  request, carry on.

Put this rule in every member's brief.

## Depth

- **Full** is the default. Never trim the council, its rounds or its
  peering to save time or tokens: the quality of the result comes first.
- **Light** only when the user asks for it, or the goal is plainly trivial
  and low-stakes (say so in the frame; the user can upgrade). At most 3
  members, the coordinator plays the Skeptic as a deliberate adversarial
  pass, no borrowed reviewer.
- Always full when a mistake could hurt someone, damage property, cost
  real money, break a law or compliance rule, or weaken security.

State the depth in the frame.

---

# Part A — The user at the table

## A1. The user's seat, per area

The user's expertise is not uniform. For each area the council will cover,
set the user's seat:

| Seat | When | How the council treats them |
| --- | --- | --- |
| **Lead** | They know this area as well as or better than the council | Their view is the starting position. The council red-teams it, and asks them to confirm expert-decided items instead of deciding silently. |
| **Peer** | They know it well, but not best | Positions side by side, debated on evidence. |
| **Learner** | It is new to them | Brief first in plain words, then recommend. |

Set seats in the frame from what the user says and how they talk about each
area. When unsure, use Peer.

## A2. What the council does toward the user

Every exchange with the user uses one of four moves. Label them, so the user
knows what kind of answer is wanted.

1. **Elicit:** an open question that draws out what the user knows and
   nobody can look up. "Walk me through the last time this went wrong."
   "What have you already ruled out, and why?" "What worries you most?"
   - In plain text, never as multiple choice: options would steer the
     answer.
   - At most 3 open questions in one message: more at once get shallow
     answers. Ask the next ones in the next message, and follow up as
     often as the answers warrant.
   - Elicit **before** recommending in Lead and Peer areas. What the user
     knows is evidence, and usually the cheapest evidence there is.
2. **Challenge:** question a claim, assumption, choice or constraint the
   user brought.
   - **What to challenge, in priority order:**
     1. a claim that is **load-bearing** (requirements change if it is
        false) and unverified;
     2. a **constraint or choice the user insists on** that carries a
        material cost or risk ("keep the old door as the wall", "send
        full customer data", "it must never duplicate"). A constraint the
        user sets is a decision too: designing around it without naming
        its cost is caving silently, even when the constraint is
        defensible;
     3. nothing else. Do not challenge things the user only mentioned in
        passing or holds loosely, and never spend a challenge just to have
        one.
   - State the user's position at its strongest first, then the counter:
     the evidence, the concrete cost, and what goes wrong.
   - **Check the counter before raising it.** A wrong challenge costs
     trust. Verify the numbers and the reasoning first.
   - Ask what a claim rests on: "How was that measured?" "Where does that
     number come from?"
3. **Propose:** put forward an option the user did not raise, when it is
   materially better on what they said they care about.
4. **Decide:** a choice that is the user's to make. Batch these. For each:
   a sentence of context, the options, their trade-offs, the
   recommendation, what the answer changes. Use the question tool if there
   is one (up to 4 per call, recommended option first), otherwise a
   numbered list.

**Ask as often as the work needs.** There is no cap on exchanges with the
user: their knowledge and choices are what make the result good, and an
item defaulted just to save a turn makes a worse design. What keeps the
asking worth their time:

- **Never re-ask** something the user already answered, never ask what
  research could settle, and never pass off a member decision as theirs.
- Order items by impact. If one message would carry more than about 7
  items, send the highest-impact ones now and the rest next turn, rather
  than defaulting them.
- Take a recommendation as *assumed, confirm at the gate* only when the
  user is away (A6) or tells the council to decide it.
- Do not paste cards, full rosters or process tables into the chat. Show
  the user conclusions and questions.

**Which items go to the user.** Sort every open item:

- **Member decides:** domain knowledge or design expertise. Decide it and
  record why. In the user's **Lead** areas, list it for the user to confirm.
- **Research settles:** a findable fact. Find it.
- **User decides:** preferences, priorities, budget, risk appetite, scope,
  facts only the user knows, or a choice between options that are each
  sound.

## A3. What the user can do toward the council

Tell the user once, at the start, in at most 3 lines, that they can at any
time:

- **Object** to any finding, requirement, design part or member decision.
  The owner must answer with evidence: concede, or explain why it holds.
- **Inject** knowledge. It enters as evidence tagged *user-asserted*.
- **Override** any decision. Their call wins.

Show the seat map as one line ("I'll treat you as lead on X, peer on Y,
new to Z — correct me"), not a table.

After each round, show a short **"Decided without you"** list: at most 5
member decisions the user would plausibly care about, one line each,
prioritising their Lead and Peer areas. Skip it if there are none.

## A4. Disagreement: counter once, then defer

When the user decides or overrides against the council's evidence:

1. The owner counters **once**: the evidence, the concrete consequence, and
   what would change their mind.
2. If the user holds their position, the council defers. No second
   argument, no re-asking in later rounds.
3. Record it in the Dissent & user-owned risks list (B7), and carry the
   risk into the document's Risks section and into the next stage's inputs.

The council never caves silently (dropping a real concern because the user
pushed) and never nags (re-arguing a settled call). Both are failures.

Any counter the user declines is dissent and gets recorded. Do not
pre-concede ("we're not challenging this as such") and then log no dissent:
if the council has a concern, state it once and record it.

## A5. User-asserted facts

A load-bearing fact from the user is either:

- **verified:** checked against a photo, document, measurement, spec or
  source; or
- **user-asserted, unverified:** recorded as such. Requirements built on it
  say so, and the verification step becomes a prerequisite for builders.

This is not distrust. Builders need to know which facts were checked.

## A6. When the user is away

If the user said to just run it, or does not answer: take the
recommendations, log them *assumed, confirm at the gate*, list every elicit
question that went unasked as an open item, and carry on. Unasked elicit
questions are a real gap; say so in the summary.

---

# Part B — How a council deliberates (both stages)

## B1. Forming a council

Members are derived from the goal, not picked from a stock list.

- **Split** a role that needs two unrelated toolkits.
- **Merge** two roles one person would naturally cover.
- **Every member owns at least one area nobody else owns.** If you cannot
  name it, the member is padding. Remove them. (The Skeptic is the one
  exception.)
- **Every question / requirement has exactly one owner.** Others review.
- **No cap on numbers.** Above 8, form teams with a lead each, so peering
  stays readable.
- **Conditional members** join only if their trigger turns out true.
  List them with the trigger.

**Card** (same shape in both stages):

```markdown
### <Role>, <domain>
**Why needed:** <questions (Stage 1) or requirement R-ids (Stage 2) it owns>
**Owns:** <areas as nouns: "supply pressure", "auth flow", "run of show">
**Does not own:** <adjacent areas, and who owns them>
**Must answer / Must design:** <the questions this member must settle>
**User's seat here:** <Lead / Peer / Learner>
**Peers with:** <members whose areas touch this one, and on what>
**Knows / relies on:** <standards, references, tools a practitioner uses>
**Agent tools:** <web search, reading the user's photos or repo, a connected app>
**Definition of Done:**
- [ ] ...
```

Definition of Done items must be markable MET / NOT MET by someone else,
and must test **correctness**, not just that a section exists.
Bad: "User briefing written." Good: "Supply pressure stated, with the
measurement method and where it was measured."

## B2. Standing seats

- **Skeptic** (full depth, both stages). Owns nothing. Attacks whatever the
  council agrees on. Each round it returns its top 3 attacks, ranked by
  damage if right, plus a **pre-mortem**: "It is a year later and this
  failed. The most likely reasons are…". An attack must be specific enough
  to be answered with evidence. It can message any member directly.
- **Borrowed reviewer** (full depth). One member from the *other* stage,
  who reviews and never designs or decides:
  - Stage 1 borrows an **architect** as feasibility reviewer: flags
    requirements that are unbuildable, contradictory, or far more expensive
    than they look, before Gate 1.
  - Stage 2 borrows a **domain expert** as fidelity reviewer: flags design
    choices that break the approved findings or the user's decisions.

## B3. A deliberation round

1. **Blind positions.** Every member first works alone from their card and
   brief, in parallel, without seeing other members' positions. This is
   the only closed phase. It stops the council anchoring on whoever speaks
   first, so it stays even though members then talk freely.
2. **Open floor (peering, B4).** Members read each other's positions on
   the board and talk directly: challenge, ask, offer, huddle. Every
   position touching a member's area gets a challenge or a sign-off with a
   reason; silence is not allowed. The Skeptic and the borrowed reviewer
   attack here.
3. **Resolution.**
   - The owner answers every challenge: **accept** (and change), or
     **rebut** with evidence.
   - A challenge rebutted to the challenger's satisfaction is closed.
   - A genuine trade-off between sound positions goes to the user as a
     Decide item, with **both positions stated at their strongest** by the
     members who hold them.
   - A disagreement the owner settles over a member's objection is
     recorded as dissent, like user dissent.
4. **Table exchange with the user.** Elicit, Challenge, Propose and Decide
   items from this round, plus the "Decided without you" list. Route each
   answer to the members it touches, and reopen the floor for whatever it
   changes.

Repeat until the council **converges**: a full pass in which no member
raises a new challenge or thread, every challenge is answered, and no
Decide item is open. There is no fixed round cap.

**Loop guard.** If the same disagreement comes round twice with no new
evidence, stop debating it: the owner settles it (dissent recorded), or it
goes to the user as a Decide item. Anything still open at convergence goes
into the document as an open item.

## B4. Peering: members talk to each other

With real subagents, members talk member to member. The coordinator is the
switchboard, not the editor.

- **Direct messages.** Any member can address any other, under
  `## To peers` in their return, one entry per message:
  `To: <Role> · Kind: question | challenge | offer | sign-off · <message, with evidence>`.
  Deliver each verbatim to the addressee, continuing that same agent so it
  keeps its reasoning, and carry the reply back verbatim. Do not
  summarise, filter or soften messages in transit. A thread runs until
  both sides close it: agreed, conceded, or sent to resolution.
- **Mid-work consults.** A member blocked on another member's area does
  not wait for the next phase: it sends a question, and you route it at
  once.
- **Huddles.** A member can call a huddle of 2–4 named members on one
  shared question (an interface between their parts, a requirement they
  both touch). Run it as a joint thread in which each member's turn sees
  the whole thread so far. A huddle ends with a joint note: what they
  agreed, what they still dispute, who owns it.
- **Council board.** Keep one board file that every member can read at any
  time: each member's latest position, open threads, huddle notes, the
  decision log, and what the user has said. Members read it; only you
  write it, so parallel members never overwrite each other. Give its path
  in every brief.
- **Ownership still holds.** Peers can persuade an owner, but only the
  owner changes their area. A peer who stays unpersuaded records dissent.
- Deliver every message bound for a wave in one turn, so members work in
  parallel.

## B5. Running members

You are the coordinator. Spawn one subagent per member, wave by wave
(members with no dependencies first, all of a wave in one turn). Continue
the same agent across rounds, threads and huddles: peering depends on
members remembering what they said.

- Members usually cannot spawn subagents. They return narrow
  *Delegation requests*; you run them and return the results.
- Members return text and read the board; you write files.
- **If you cannot spawn subagents,** do not stage theatre. One mind
  playing eight named members, writing "blind positions", messaging
  itself as peers and grading its own Definition of Done, adds length, not
  independence. Instead:
  1. work each area from its card;
  2. run an explicit **error hunt** per area: list the ways this area's
     conclusions could be wrong and check each;
  3. check every place two areas touch, from both sides;
  4. run the Skeptic pass and pre-mortem across the whole;
  5. record only challenges that changed something.

  Say in the document that the council was simulated and its agreement is
  weak evidence, and recommend human review of high-stakes parts.
- Put the user's standing preferences into the brief of every member they
  affect. Members only see their brief and the board.

**Member brief:**

```
You are the <Role> on the <domain / architecture> council, working with the
user toward: <frame: goal, context, scope, constraints, assumptions, depth>

Hard rule: <stage's version of plan-never-build>

Your card: <card>
User's seat in your area: <Lead / Peer / Learner> — <what that means for you>
Council board (read it whenever you need others' positions or the log): <path>
Decision log so far (user decisions are fixed unless you raise a challenge):
<log>
What the user has told the council (user-asserted unless marked verified):
<injected knowledge and elicit answers>
You may message any member directly under "To peers", call a huddle, or ask
a peer mid-work; messages are delivered verbatim.
This round: <blind position | open floor: respond to these messages: ... |
huddle on: ... | answer these challenges: ...>

Return exactly:
## Position          (findings or design, with evidence and sources)
## Requirements      (Stage 1: must / should / must not)  |  ## Interfaces (Stage 2: between whom, inputs, outputs, owner, failure behaviour)
## Decided           (what you settled, and why — one line each)
## For the user      (Elicit / Challenge / Propose / Decide items, labelled; only what is theirs)
## To peers          (To · Kind · message with evidence; sign-offs with reason; huddle calls)
## Answers           (to messages and challenges you received: accept or rebut, with evidence)
## Notes for the next stage
## Definition of Done (each item MET / PARTIAL / NOT MET, with evidence)
## Delegation requests (only if you could not spawn subagents)
## Confidence        (high / medium / low, one line why)
```

## B6. Verify

Members graded themselves; do not take those grades as final.

- Grade every DoD item against the evidence: MET / PARTIAL / NOT MET.
- **Correctness spot-check:** pick the 3 most load-bearing claims and check
  their evidence yourself.
- **Integration:** no contradicting requirements or parts; every user
  decision reflected; nothing owned twice; every challenge and peer thread
  closed or carried as open.
- **High stakes:** spawn an independent verifier per affected member,
  given the card and the work, not the self-grades. If you cannot, do an
  adversarial pass yourself and recommend human review.
- Send gaps back to the owner and rework until they close. If the same gap
  comes back twice with no progress, report it honestly as open: what is
  missing, why, what would close it.

## B7. Decision log

One table, carried across both stages. Log decisions that change a
requirement, a design part or a risk; skip trivia.

| ID | Decision | Options considered | Chosen | Decided by | Why |
| --- | --- | --- | --- | --- | --- |

*Decided by* is one of: user · member (<role>) · members (huddle: <roles>) ·
user-delegated · assumed (confirm at gate).

Below it, a separate **Dissent & user-owned risks** list: each decision
where the user overrode a counter, or a member was overruled, with who
disagreed, the risk they raised, and the decision ID. Only real dissent;
no "none" rows.

---

# Part C — Keeping the council's work

## C1. Council state

Keep the board (B4) as the council's state, updated after every round and
every user exchange: frame, seat map, depth, roster, current stage and
round, decision log, dissent list, open threads, what the user has said
(verified or asserted), and unasked elicit questions. Long councils
outgrow the conversation's working memory; read the board back instead of
relying on recollection.

## C2. Documents

Deliver the Domain Expert Document and the Architecture Document as
editable documents the user can keep, comment on and share: the session's
document type where one exists, otherwise a markdown file sent to the
user. Publish the draft at each gate and before any long pause, so the
work survives the session. A document's Status line, decision log and open
items must be enough to resume from.

## C3. Resume

On "resume", or a council document handed back: read the board if it
still exists, otherwise the latest document. Restate in a few lines where
the council stands (stage, what is decided, what is open, whose move it
is). Reconvene members with their cards, the decision log and their prior
positions. Do not redo settled work or re-ask answered questions.

## C4. Amend an approved document

Route the change to the owning member, re-verify the affected part and
everything that traces to it, bump the version (1.0 → 1.1) with a change
note, record it in the decision log, and take the document back through
its gate. A change to an approved Domain Expert Document after Stage 2 has
started also reaches the architects as a requirement amendment (2.5).

---

# Stage 1 — Domain council

Settles **what** is needed and **why**. Not how it is designed.

### 1.1 Frame

Write with the user:

- **Goal:** the end state in one sentence, not the activity.
- **Context:** what exists now; constraints; regulations that may apply.
- **Scope:** in, and explicitly out.
- **Unknowns:** each marked *ask the user* or *research*.
- **Seat map** (A1) and **depth** (Depth section).

### 1.2 Elicit first

Before forming the council, elicit (A2: up to 3 open questions per
message, follow up as the answers warrant), covering, in whatever
combination fits the goal:

- **What exists now and its condition**, and **what has gone wrong
  before** (failures, incidents, problems with the space or system). This
  is where the most valuable tacit knowledge hides.
- **How the result will be used day to day**, and what a good outcome
  looks like to the user. This is where unstated top priorities hide.
- **What is already decided or ruled out, and the limits**: budget, time,
  people available, if the user has not said.

A question that only shapes requirements is still worth asking here. Write
down assumptions for anything left, and carry on.

### 1.3 Form the council

Find the questions by walking the goal's lifecycle: **assess** (what is
there now), **choices**, **acquire** (materials, services, accounts,
permissions, data), **do** (what can go wrong), **verify** (how anyone
would know it worked), **operate / maintain**. Then the lenses:

- **Safety:** can someone get hurt, or something break, flood, leak, burn?
- **Compliance:** codes, permits, licensing, legal, privacy, security.
- **Cost:** the goal's budget, cost of ownership, cheaper routes. When
  something will be bought: price history against any discount claim,
  whether the seller is genuine, whether reviews are real. Usually a
  separate buying expert.
- **People:** who uses it, who is affected.
- **Interfaces:** where it touches a system someone else owns.

Group questions into members by the body of knowledge needed (B1), and
fill in who each member peers with. Add the Skeptic and the borrowed
feasibility architect at full depth. Map waves by dependencies; break
cycles by giving the shared question one owner, by assume-then-check, or by
a mid-work consult (B4).

**Show the roster** in plain form: a short table (member, what they
cover, why needed). Leave out cards, DoD, agent tools and briefs. Let the
user adjust it. For a roster-only request, also give each member's
real-world knowledge and Definition of Done.

Stage 1 member DoD always includes:

- [ ] Every Must-answer question answered with evidence, or turned into an
      item for the user.
- [ ] Every open choice has options, trade-offs and a recommendation.
- [ ] Every load-bearing user claim in this area is verified or marked
      user-asserted.
- [ ] Every peer thread touching this area closed or carried as open.
- [ ] A plain-language briefing of at most 150 words, for Learner and Peer
      seats.
- [ ] Requirements and notes for the architects written.

### 1.4 Deliberate

Run rounds per B3, with peering per B4, until the council converges.

### 1.5 Verify

Per B6, plus: every lifecycle question from 1.3 answered or listed open;
the feasibility reviewer's flags each resolved or carried as open.

### 1.6 Domain Expert Document and Gate 1

```markdown
# Domain Expert Document: <goal>
Status: Draft, awaiting approval · Version 1.0 · Depth: light / full
Council: real subagents, peered / simulated

## Summary            <3–5 sentences: what the problem really is, the biggest risk, feasibility>
## Mission & scope    <goal; in / out; constraints; assumptions; seat map>
## Domain primer      <briefings merged; glossary>
## What the user told us  <elicited knowledge; each item verified or user-asserted>
## The council        <table: member, covered, DoD status>
## Findings           <by area, with evidence and sources>
## Requirements       <R1, R2… must / should / must not; prerequisites;
                       measurable success criteria; mark any resting on unverified user facts>
## Decision log       <B7 table, IDs D1, D2…, then the Dissent & user-owned risks list>
## Risks              <ranked; each recorded dissent appears here>
## Skeptic's pre-mortem
## Feasibility flags  <from the borrowed architect; resolved or open>
## Open questions for the architects
## Handoff            <what is fixed; what is left to design>
## Verification       <one line of totals, then only the items not MET, with what would close them>
```

No design, no architecture, no build plan in this document. No member
cards either: the council table is enough. Every section must earn its
place for the architects; say a thing once.

**Gate 1.** Short summary plus the document (C2). The user chooses:

- **Approve:** Status → "Approved by user on <date>". Offer Stage 2.
- **Request changes:** route each to its owner, re-verify, present again.
- **Stop.**

Never start Stage 2 without this approval.

---

# Stage 2 — Architecture council

Designs **how**, within what Stage 1 fixed.

### 2.1 Absorb

From the Domain Expert Document take requirements (R-ids), decisions
(D-ids, with who made them), constraints, dissent and risks, open questions,
and any user-asserted facts that requirements rest on. Check the Status
line. If the document is too thin to design from, list exactly what is
missing and ask, or send it back. Never invent requirements.

**Fixed inputs.** No architect quietly reopens a decision, least of all one
the user made. A real reason to reopen it is raised to the user as a
Challenge, with evidence and what it would change.

### 2.2 Rank what matters, with the user

Architecture is trade-offs, and the user owns the ranking. Before any
design:

1. List the qualities that matter for this goal (for example cost, time to
   deliver, reliability, safety, simplicity to run, flexibility to change,
   performance, appearance), drawn from the requirements.
2. Ask the user to **rank** them. If they rate everything top, show the
   specific conflict ("the cheapest design is not the always-on design")
   and ask them to choose. Do not substitute your own default order.
3. In the same exchange, get the **hard limits** the Domain Expert
   Document does not already state: budget ceiling (build and running),
   deadline, who will build it and who will run it (size, skills, on-call
   capacity), and anything they will not adopt.
4. Record the ranking and the limits in the decision log. Every later
   trade-off is judged against them.

### 2.3 Rival shapes before specialists

Do **not** form specialist architects yet. Choosing specialists already
fixes how the system is split.

1. Sketch **2–3 genuinely different end-to-end shapes** (different
   structure, not cosmetic variations). If running subagents, give each
   shape to a separate architect, told to make the best case for it, and
   let the shape architects attack each other's shapes directly (B4).
   Include the simplest shape that could meet the requirements.
2. For each shape: a one-paragraph description, an overview diagram, how
   it meets the must-requirements, how it scores on the ranked qualities,
   rough cost and effort **against the hard limits**, biggest risk. Judge
   simplicity by what the user's actual team must build and run: every
   piece of custom machinery they would own counts against it, however
   few boxes the diagram has. Prefer proven, boring parts.
3. The Skeptic attacks each shape. The fidelity reviewer checks each
   against the approved findings.
4. Present to the user as a Decide item, with the council's recommendation
   and the Skeptic's strongest attack on it. The user may pick, merge or
   reject all.
5. Record the choice as an ADR (context, options, decision, consequences),
   including the cost, effort and risk figures it was chosen on.

**Drift rule.** If later design work moves the chosen shape's cost,
effort or risk materially (roughly 20% or more), or past a hard limit,
take it back to the user before the gate: the shape was chosen on the
old numbers. This is never a "decided without you" item.

### 2.4 Form the specialist council from the chosen shape

Derive specialist architects from the parts the chosen shape has (B1).
Examples: data, integration, security, platform (software); structural,
plumbing layout, waterproofing (building); venue, run of show, AV (event).
A **Lead Architect** owns the end-to-end flow, integration between parts
and the document. The Lead's calls are challengeable like anyone's. Every
requirement gets one owning architect. Tell the user the roster in one
line; ask for approval only if it is surprising or costly.

Small design details (ports, timeouts, field names) go in part
specifications, not the decision log.

Stage 2 member DoD always includes:

- [ ] Every owned requirement is covered by a named part, in the
      traceability table.
- [ ] Every interface with another part has a contract: inputs, outputs,
      owner, failure behaviour, and both sides agree.
- [ ] Happy path and unhappy paths (failure, timeout, bad input, partial
      completion) designed, each ending somewhere defined.
- [ ] Safety, security and compliance requirements in this area met, with
      evidence.
- [ ] Builders get a sequence, dependencies, an acceptance check per part,
      and any spikes that must run first.

### 2.5 Deliberate

Run rounds per B3, with peering per B4. Each architect checks every
interface touching their part from their side, and the two owners of an
interface settle its contract in a huddle.

**Back-channels to Stage 1:**

- **Domain query:** a factual question about the domain. The architect
  messages the owning domain expert directly (B4); reconvene the same agent
  if possible. No gate needed; record the answer.
- **Requirement amendment:** the design shows a requirement is wrong,
  missing or unaffordable. Raise it to the user as a Challenge. If they
  accept, amend the Domain Expert Document (C4) and record the change in
  both decision logs.

### 2.6 Verify

Per B6, plus:

- **Traceability:** every requirement maps to a part and an acceptance
  check; every part traces to a requirement. Flag orphan parts
  (gold-plating) and uncovered requirements.
- **Fidelity:** every Stage 1 decision honoured, or changed through an
  approved amendment.
- **Ranking:** every major trade-off went the way the user's ranking says,
  or the exception is explained.

### 2.7 Architecture Document and Gate 2

Draw the overview and main flows as diagrams.

```markdown
# Architecture Document: <goal>
Status: Draft, awaiting approval · Based on: Domain Expert Document v<x>, approved <date>
Council: real subagents, peered / simulated

## Summary              <design in 3–5 sentences; rough effort, cost, time; biggest risk>
## What matters most    <the user's ranking and hard limits>
## Shapes considered    <the rival shapes, why the chosen one won, the Skeptic's attack on it>
## Inputs               <R-ids, D-ids, carried dissent, unverified user facts>
## Architecture overview <diagram>
## Parts                <responsibility, interfaces, which builder role builds it>
## Flows                <happy and unhappy paths>
## Data / materials / information
## Cross-cutting        <safety, security, compliance, reliability, cost>
## Decision log (ADRs)  <B7 table, then the Dissent & user-owned risks list>
## Traceability         <requirement → parts → acceptance check>
## Build handoff        <work packages, sequence, dependencies, acceptance criteria,
                         spikes to run first, skills each builder needs>
## Risks & open items   <including Skeptic's pre-mortem and all dissent>
## Verification         <one line of totals, then only the items not MET>
## Approval             <pending>
```

No member cards in the document.

**Gate 2 (consent).** Short summary plus the document (C2). The user
chooses:

- **Approve for build:** Status → "Approved for build by user on <date>".
  Present the build handoff summary. The skill ends.
- **Request changes:** route to owners, re-verify, present again. A change
  that contradicts Stage 1 goes through the user as an amendment.
- **Stop.**

After approval, do not build and do not spawn builders. Share the document
or turn work packages into tickets only if the user asks.

---

## Worked example (shape only): a 2-day workshop for 60 people

**Frame and seats.** The user runs workshops for a living: **Lead** on
content and audience, **Learner** on venue contracts, **Peer** on budget.
Depth: full (deposits are real money).

**Elicit first.** "What went wrong at your last in-person event?" The user
says half the attendees left early on day 2 because the last train home was
at 18:30. Nobody could have looked that up, and it adds a requirement:
day 2 ends by 17:00. It also brings a transport question into scope.

**Challenge.** The user says "venues near the station always include AV".
That is load-bearing (the AV budget depends on it), so the venue expert
asks what it rests on and counters with two venue rate cards that charge
for projectors separately. The user checks: their usual venue includes AV;
the new candidates do not. The claim is recorded as true for one venue
only.

**Peering.** The catering expert messages the venue expert directly: the
shortlisted hotel's kitchen closes at 15:00, so a hot afternoon break is
impossible. They huddle with the facilitation expert, who moves the long
break to 14:30; the joint note goes on the board and no user question is
needed.

**Disagreement.** The user insists on a single room for all 60, against
the facilitation expert's evidence for two breakout rooms. The expert
counters once with the exercise plan that needs parallel groups. The user
holds; the council defers. The dissent is recorded and the risk ("two
exercises must be redesigned for one room") is carried to Stage 2.

**Stage 2.** The user ranks *attendee experience > cost > simplicity*,
with a hard budget ceiling. Three shapes: hotel package, a separate venue
plus caterer, a university hall. The Skeptic's strongest attack on the
recommended hotel package is that its cancellation terms lock in the
deposit 60 days out. The user picks it anyway, and that is recorded as a
user-owned risk.