# Feature catalog (dated, source-tagged)

Volatile facts. Verify anything load-bearing before asserting it (SKILL R1). Tags: [L] Learn, [B] blog, [CAT] Microsoft CAT/repos, [C] community, [U] unverified.


## B1. Harnesses
Learn lists **three** harnesses [L harnesses-overview]: the **Microsoft Copilot harness**, the **Customer Conversation harness** and the **standard harness**. "Copilot Chat harness" appears in some secondary sources but **not on Learn**; extending M365 Copilot Chat is a separate surface, so verify before recommending it.

| | Microsoft Copilot | Customer Conversation | Standard |
|---|---|---|---|
| Status | GA [B, Sept 2026] | ⚠ GA announced 18 Nov 2026 [B]; Learn What's new (12 Nov) still says Preview | GA, fully supported |
| Best for | Long, multi-step, multi-tool processes; file work | Customer voice and chat, contact centre | Rule-based, scripted, predictable conversations |
| Behaviour | Goal → plan → adjust, retry, try other paths | Sub-agents, defined escalation to a human | Follows the topics and paths you define |
| Automation | Workflows (new designer) | Connectors, knowledge, MCP, connected agents | Agent flows (classic designer) |
| Skills / memory / hooks | Yes / Yes / Yes (Preview) | Yes / Yes / not documented | No / no focus / **No** |
| Topics | **No** (skills, hooks and workflows replace them) | Yes | Yes (the core) |
| Files in a sandbox (Word, Excel, PowerPoint, PDF) | Yes | No | No |
| Channels | **Fewer** than standard (B8) | Web chat, phone number | Broadest |
| Billing | Copilot Credits, usage-based (building, testing, evaluating and running all consume them) | Copilot Credits | Standard-harness licensing |

**Upgrade** (Preview, October 2026) [L faqs-copilot-harness]:
- Creates a **copy** on the Copilot harness and carries over instructions, tools and suggested prompts, with a migration report.
- **Not migrated:** knowledge sources, Power Fx and child agents.
- Topics can be rebuilt as skills or workflows.
- Uses credits.
- Published standard agents are unaffected.
- Other than this, agents can't be converted in either direction [L].

**Performance claims** [B/CAT, internal and unverified]:
- Knowledge quality 66.0 → 86.4.
- Multi-tool task success 87.0% → 98.9%.
- "45% fewer input tokens" is `[U]`.

**Choosing a harness**
- **Copilot harness** for multi-step processes, provided the channel is supported.
- **Customer Conversation** for external customers on voice or web.
- **Standard** for scripted conversations, Power Fx and topic control, channels the Copilot harness doesn't support, or simple high-volume Q&A where extra reasoning adds cost and latency. See Learn's *choose a harness* guidance.

## B2. Agent features (Copilot harness unless noted)

### B2.1 Instructions and model [L What's new]
- Set on the Build tab. A model dropdown has existed since September 2026.
- Models:
  - Claude Sonnet 5 (GA)
  - GPT-5.5 Chat (GA; default on the standard harness since October 2026)
  - Claude Opus 4.8 (GA)
  - GPT-5.3 Chat (Preview)
  - Experimental: GPT-5.5 Reasoning Deep, Mistral Medium 3.5
- After a forced model upgrade, agents can stay on their current model for up to 30 days. Re-run evaluations after any model change.
- Example instruction: "You are the Returns Desk agent for support reps. You never promise refunds. You always call *Approve refund request* to process money."

### B2.2 Skills [L skills-overview; B]
- Open Agent Skills format: a `SKILL.md` file, or a ZIP with `SKILL.md` at the root.
- Build tab → Skills → *Create from blank* / *Upload a skill*. Skills can be exported.
- Marketplace sharing: Preview (October 2026). Central approval in Agent 365: GA [B].
- Use for procedures that need judgment. Example: a `refund-policy` skill shared by two agents.
- Skills guide behaviour; they don't guarantee it.
- Don't confuse them with the old Bot Service "skills".

### B2.3 Memory [L memory-overview, updated 20 Nov 2026]
- Rolling out to GA; may still be Preview in some regions.
- Per-user context by default.
- Agents with an **agent account** use **shared memory** across everyone they work with, with no opt-out during preview [L authoring-agent-account].
- Use memory for preferences only. Never keep business state there.

### B2.4 Knowledge

| Source | Status / note |
|---|---|
| SharePoint, OneDrive | OneDrive honours Purview sensitivity labels (Oct 2026) [L] |
| Public websites, Bing Custom Search | [L] |
| Local uploads | Admins can restrict uploads, SharePoint/OneDrive and websites (Oct 2026) [L] |
| Dataverse tables | B4.1 |
| Azure SQL tables | [L, Aug 2026] |
| Fabric IQ | Preview [L] |
| **Foundry IQ** | ⚠ Preview per What's new (June) [L]; some Book of News sub-features are GA. Verify |
| Graph connectors | [L] |

- Knowledge **answers**; tools **act**.
- Knowledge bindings are often environment-specific, so rebind them after deployment.
- Treat web, email and uploaded content as **untrusted** (Part C).

### B2.5 Tools

| Tool | What it does | Status |
|---|---|---|
| Connectors | Single API actions | GA |
| **Workflows as tools** | Deterministic automation with typed I/O | GA [B, Aug 2026] |
| Agent flows as tools (standard harness) | Same, classic | GA |
| MCP servers | External tools; Microsoft MCP certification open for submission | GA [B] |
| Dataverse MCP | B4.2 | See B4.2 |
| **Work IQ** | User's mail, calendar, files, Teams, people | GA. **On by default, with write operations on**, for Copilot harness agents [L, Oct 2026] |
| Computer use / W365 for Agents | UIs without APIs, on a Cloud PC | Computer use GA (May 2026). W365 MCP server GA. In the Copilot harness: Preview from Dec 2026 [B] |
| Prompts | One structured AI call | GA |

**Work IQ:** decide per agent whether it may send mail or post. If not, turn writes off, or deny with a Pre tool use hook. Enterprise controls and human approval for Work IQ are Preview [B Book of News]. (`[U]`: a recap said Work IQ MCP writes are blocked by default. Not on Learn, so don't rely on it.)

### B2.6 Connected agents [L What's new]
- A front-door agent delegates to:
  - Copilot Studio agents
  - Foundry or M365 Agents SDK agents (Oct 2026)
  - A2A agents (protocol GA April 2026; as a connected agent, Preview Oct 2026)
- Split agents only when permissions, tools or owners differ.
- ⚠ Learn's Copilot-harness FAQ says Copilot-harness connected agents can currently delegate only to agents also built on the Microsoft Copilot harness. Verify before mixing harnesses or external agents.

### B2.7 Hooks (Preview, Copilot harness only) [CAT hooks post, updated 6 Nov; CAT mcs-hooks lab]
Hooks are deterministic extension points. Each one is backed by a workflow.

| Event | Fires | Receives | Can return |
|---|---|---|---|
| Start (pre-loop) | Once, at the start of a new conversation | `event`, `timestamp`, `metadata` (includes `userAadObjectId`) | `additionalContext` |
| User prompt submitted | Every user message | `prompt` | `modifiedPrompt`, `suppressOutput` |
| **Pre tool use** | Before a tool call | `toolName`, `parameters` | `permissionDecision` (**`deny` documented**; leave empty to allow; `allow`/`ask` are `[U]`), `permissionDecisionReason`, `modifiedParameters`, `additionalContext`, `suppressOutput`. **The only event that can block** |
| Post tool use | After a tool succeeds | `toolName`, `parameters`, `result` | `modifiedResult` |
| After tool failure | When a tool call fails | `toolName`, `parameters`, `error` | `additionalContext` |
| Error | Agent error | `error`, `errorContext`, `recoverable` | `errorHandling` (`retry`/`skip`/`abort`), `retryCount`, `userNotification` |

**Setup**
1. Agent **…** → **Hooks** → **Create**.
2. Create the backing workflow from **Add hook → New workflow**. The Workflows page can't create one; the list only shows workflows whose schema matches.
3. Keep the starter field names. Every Respond in the workflow uses the same schema.
4. Publish the hook workflow, publish the agent, then start a **new** chat. Saving alone does nothing.

**Gotchas**
- **Fails open.** On errors, timeouts or unreadable responses, the call proceeds. Always re-check downstream.
- **Tool parameters arrive under internal keys by type and creation order** (`text`, `text_1`, `number`…), not display names. Inspect a real payload in Preview before branching on it.
- A User prompt hook that runs a model adds latency on every turn (one lab cites 20–30 s).
- Pre tool use with an empty Tools field applies to every tool.
- `modifiedPrompt` and `suppressOutput` don't remove the original from storage or transcripts.
- A successful hook may still show `"isContinue": false`. Check its outputs instead.

### B2.8 Files
- Users can attach Word, Excel and PowerPoint files (GA, Sept 2026) and can view files the agent creates.
- The sandbox creates and edits Word, Excel, PowerPoint and PDF, and can run code.
- Images in chat: Base64 data URI for small images; for large ones, store the file and return a link [CAT].

### B2.9 Autonomy and identity
- **Event-driven agents** (SharePoint item, email, schedule): Preview, Oct 2026 [L].
- **Entra Agent ID:** created automatically for every new agent since July 2026; no environment-level opt-out [L].
- **Agent account** (Frontier preview) [L authoring-agent-account]:
  - **Includes:** an Entra Agent ID, a mailbox, presence in Teams and the directory, scoped access, and shared memory.
  - **Prerequisites:**
    - Tenant enrolled in Frontier, with the Agent 365 terms accepted.
    - Environment on the **Early** release cycle.
    - Admin activates *Copilot Studio (Frontier)* for selected makers, then turns on Agent accounts in Power Platform admin centre (PPAC) → Copilot → Settings.
    - Maker licence: M365 E5 with the Agent 365 add-on, or M365 E7.
    - Each agent needs a **Microsoft 365 Frontier for AI Teammates** licence. Publishing fails if none is free.
    - In the EEA, Teams is licensed separately.
  - **Pricing:** account licensing is separate from usage charges. **No per-agent price is published on Learn; don't quote one.**
  - **Limits:**
    - No external users.
    - Email only in threads of up to 250 people.
    - Can't read Confidential or Internal Only labelled documents.
    - No co-authoring edits.
    - Partial Graph support.
    - The email address can't be changed after publishing.
  - Status ⚠: Frontier private preview (blog, 4 Nov); public preview from December 2026 (blog, 18 Nov).

### B2.10 Channels → see B8.

### B2.11 Quality [L; B]
- **Evaluations (GA):**
  - CSV test sets and multi-turn tests.
  - Metrics: Task Completion, Tool Accuracy, Safety, Latency.
  - Natural-language custom metrics (Preview).
  - Graders library and generated graders.
  - Can evaluate single nodes or whole automations.
  - Run through the Power Automate connector (*Evaluate Agent*, usable as a pipeline gate) or the REST API (Preview).
  - Evaluation Viewer role.
- **Review panel (GA):** blockers and warnings, stale-evaluation flags, policy blocks.
- **Analytics:** questions, reactions, CSAT, CSV export.
- **App Insights export** at environment level: Preview.

### B2.12 Governance and cost
- **Agent 365:** identity, Conditional Access, access reviews, observability.
  - Central plugin and skill approval: GA.
  - Cost Management: Preview.
- **Billing:** Copilot Credits, pay-as-you-go or prepaid. When prepaid capacity is exhausted, new workflow runs are blocked [L].
- **PPAC cost controls** [L faqs-copilot-harness]:
  - Environment credit allocations (prepaid packs only).
  - Agent limits (only after the agent has used some credits).
  - Blocking environments from drawing on the tenant pool.
  - Credit estimator.

### B2.13 Standard-harness toolkit
Topics, trigger phrases, Question and Message nodes (with condition groups), Power Fx, variables, adaptive cards, generative orchestration, agent flows and the prompt library. This skill covers the standard harness only lightly; see Part C.

## B3. Workflows (new designer)

### B3.1 Basics [L workflows-experience/flows-overview, flow-designer]
- Workflows → New workflow → set the trigger on the Start node → build (Build tab).
- A workflow is one trigger plus at least one action.
- **Enabled** gates new runs.
- Every executed action consumes credits. The Workflows page shows *Credit usage (last 30 days)*; for classic workflows, "N/A" means unknown, not zero.
- The first test run saves and publishes the workflow, installs connections, then triggers.
- ⚠ Learn pages in some locales still show a "preview" banner; en-us pages don't.

### B3.2 Triggers

| Trigger | Use |
|---|---|
| Manual / on demand | Tests, human-started runs. Inputs can include enum, multi-select and JSON object/array [CAT/L] |
| Schedule / recurrence | Reconciliations, digests |
| Connector events | Dataverse row added/modified/deleted, email, SharePoint. Filter tightly (B4.5) |
| HTTP request / HTTP webhook | Called from external systems [CAT review finding; verify the exact names] |
| **When an agent calls the flow** | The agent-callable trigger for **workflow tools, hook workflows and classic agent flows alike** [L workflows-experience/flow-agent; L faq-workflows]. A panel may label it "When an agent calls the workflow — Trigger as a tool from an agent". **Both labels mean the same trigger.** What tells tool, hook and flow apart is where the workflow was created and its schema. Selecting it adds *Respond to the agent* |

### B3.3 AI nodes

| Node | What it does |
|---|---|
| Prompt | One AI call |
| **Agent** | Hands a step to an existing agent **or one defined inline**. The agent returns structured output, then the workflow continues |
| Microsoft 365 Copilot | Prompt grounded in the **running user's** M365 data. Can target Researcher, Analyst or Agent Builder agents (Advanced parameters → Agent). Needs an M365 sign-in and a time zone [L] |
| Copilot (Preview, Sept 2026) | Runs a Copilot Chat or Cowork task, including Researcher and Analyst |
| Extract | Pulls named values and tables from documents |
| Classify | Decision-scoring classification |
| Computer use (Preview) | A computer-using agent as a step |
| **Respond to the agent** | Returns typed outputs. Send it **once per path** |

### B3.4 Human in the loop

| Action | What it does |
|---|---|
| Request for information (Human in the loop connector) | Pauses and asks named people for typed inputs through Outlook |
| Run a multistage approval | Manual and/or AI stages (AI stages use credits) |
| Start and wait for an approval (Approvals) | Teams, falling back to email. Follow it with a Switch on Outcome **with a Default case** |

All of these outlast the synchronous window, so use A6.1. When a flow containing these actions is shared, the recipient may have to recreate the multistage approval [L].

### B3.5 Built-ins
- If/Else, Switch (always with Default), loops, data operations, date and time, child workflows.
- Expressions: use the `fx` icon or type `/`. Copilot can write them.

### B3.6 Error handling (general Power Automate practice)
- **Run after:** route each action on succeeded / failed / skipped / timed out.
- **Try/Catch scopes.**
- **Retry policies** on actions that get throttled.
- A failed Scope cancels the rest of its actions; find the first one that failed.
- The Catch scope must still return a result to the agent **exactly once** (A7).

### B3.7 Run history
- Each run shows its status and every action's inputs and outputs.
- Force a failure during the build so you know what the error looks like.
- On the agent side, debug with the Preview pane, the evaluation activity map and App Insights.

### B3.8 Classic agent flows and Power Automate
- **Trigger:** *When an agent calls the flow*, plus a *Respond to the agent* action.
- **For the flow to show up as a tool:**
  - It is **published** [L].
  - It uses the trigger and the response.
  - Async is **Off** while you attach it [CAT].
  - It is in a solution [CAT].
  - It runs under the Copilot Studio plan [CAT].
- **Express mode** (Preview): for logic-heavy flows on new infrastructure.
- **Async response** [L flow-asynchronous-response]:
  - Supported only in new-infrastructure environments.
  - Toggle: Respond to the agent → Settings (Learn also says **Networking**; ⚠ the label drifts).
  - Callbacks are formally tested only in Teams and are **not supported in M365 Copilot or telephony**.
  - If the user sends a new message, the agent answers only the latest one.
- **Execute Agent callback** (Copilot Studio connector, reusing `System.Conversation.Id`) [U]: used in Microsoft lab material and tested in Teams in this skill's patterns. Delivery back into **M365 Copilot** chat is undocumented; treat it as unsupported there and use an out-of-band notification (Teams message or email) instead.
- **Power Automate cloud flows** can be converted to agent flows. For Copilot-harness agents, rebuild them as workflows instead.

## B4. Dataverse

### B4.1 Tables as knowledge [L knowledge-add-dataverse]
- Needs **Dataverse search** on, **Searchable** turned on per column, and synonyms and glossary entries (the biggest quality lever).
- Virtual tables: Finance & Operations only.
- Multiline Text and File columns: unstructured reasoning is Preview.
- Good for lookups; bad for aggregations (use B4.2 or a workflow).

### B4.2 Dataverse MCP server [L power-apps data-platform-mcp]
- Add tool → MCP → **Dataverse MCP Server**. The Preview variant adds preview tools. An onboarding wizard handles multiple environments.
- Admins enable the server and its allowed clients per environment. (⚠ "Enabled by default for Copilot Studio" appears on Learn's disable page; verify in your tenant.)
- Endpoint: `https://{org}.crm.dynamics.com/api/mcp`.
- **Tools:**

| Tool | Purpose |
|---|---|
| `search_data` | Data search |
| `search` | Metadata search: schemas **and business skills** |
| `describe` | Replaces `describe_table`, `list_tables` and `fetch` |
| `read_query` | Supported SQL `SELECT` only. Use for counts, top-N and grouping |
| `create_record`, `update_record` | Write rows |
| `delete_record`, `delete_table` | Need explicit approval |
| `create_table`, `update_table` | Change schema |
| `upsert_skill`, `delete_skill` | Manage business skills |
| `init_file_upload`, `commit_file_upload`, `file_download` | Files |
| `invoke_api` | Custom API |

- **Billing:** `search_data` is billed per use; every other tool is billed at the basic rate per 10 responses.
- **Gotchas:** update allow/deny lists after the 2026 renames, and restrict which tables are reachable.

### B4.3 Writes inside workflows
- Dataverse connector actions: List rows, Get a row, Add a new row, Update a row, Delete a row, plus row triggers.
- **Any write with business consequences happens only in a workflow.**

### B4.4 Security
- Dataverse enforces the security roles of the **identity behind the connection** (B5).
  - End-user credentials → the user's own roles.
  - Service or maker connection → that account's roles, so keep them least-privilege.
- For row visibility per user or region, use end-user credentials plus business units, teams or ownership. **Never filter data through instructions.**
- Mind the Dataverse service protection limits at high volume (Part C).

### B4.5 Schema, triggers, idempotency
- Prefix all names with your publisher prefix.
- The Status choices must include **every outcome** the workflows return.
- Every process table needs a quotable key, `approvedby`, timestamps and `source`.
- Keep an `AgentAuditLog` table.
- **Loop guard** for row triggers: Select columns, plus Filter rows, plus a marker that the workflow itself writes.
- **Idempotency:** look up the business key before creating a row.

## B5. Identity and credentials [L configure-no-maker-authentication; L configure-enduser-authentication]

| Layer | Facts |
|---|---|
| Agent authentication | Authenticate with Microsoft / manually / none. Teams needs one of the first two. A separate admin control for agent authentication exists (Preview) [L power-platform admin security] |
| Tool credentials | **End-user** (on-behalf-of; the user signs in when needed; Copilot Studio stores no credentials) or **maker-provided** (the maker's connection is reused for everyone, so it overshares) |
| Admin credential control | Allow end-user only, maker only, or both (both is the default), per environment or environment group; the group setting overrides. **If maker credentials are blocked:** scheduled, autonomous and background agents fail, and a flow used as a tool requires each user to sign in to every connection that flow uses [L] |
| Inside flows | Each action has its own connection reference [CAT]. ⚠ How the tool-level setting interacts with those references varies; see the row above. Verify with a test user who isn't the maker |
| Agent identity | Entra Agent ID is automatic. An agent account gives the agent its own identity (B2.9); tools that use end-user authentication still need each person's consent |

**Design rules**
- Interactive and user-scoped → end-user credentials.
- Autonomous → a dedicated least-privilege service connection or an agent account, with the policy allowing it.
- The M365 Copilot node always runs as the running user.

## B6. ALM

**Track 1, standard harness (documented)** [L authoring-solutions-*; CAT ALM labs]
1. Environments: DEV, TEST and PROD.
2. A custom solution and publisher. Agents start in the default solution.
3. Environment variables and connection references.
4. Managed solutions downstream. Managed agents can't be edited in the target.
5. Power Platform pipelines (Copilot Studio → Solutions → Pipelines). Pre-deployment validation asks for the environment-variable and connection-reference values.
6. Git: Dataverse Git integration with Azure DevOps or GitHub. Microsoft's `copilot-alm-starter` repo has templates.
7. Import custom connectors first. Topic names containing a period block export.

**Track 2, Microsoft Copilot harness (new experience)**
- ⚠ Learn does **not** document solution or pipeline support for new-experience agents and workflows. Verify solution export in your tenant before you promise pipelines.
- **As-code paths** (all preview; commands are in build.md §1, §5.3):
  - **`msagent`**, the Copilot Studio CLI (`Microsoft.Agents.Hosting.Cli`, Windows and macOS, .NET 10) [L]: local files, Git, named dev/test/prod deployment targets, CLI evaluations. No solution packaging, and no supported service-principal deploy yet.
  - **`pac copilot init --authoring-mode cli-copilot`**, then pull, push and pack [L; harness mapping CAT].
  - **Copilot Studio MCP** (`@microsoft/copilot-studio-mcp`) [L].
  - Agents can also be created from Cowork or Code (public preview).
- The **VS Code extension is documented on Learn for the standard harness only.** ⚠ `mcs-assistant`'s text assumes it handles CLI agents; verify before relying on it (catalog diff).
- Commands are in build.md §5 and §9.

**Both tracks, after every deployment:** rebind knowledge, check connections, run the evaluations (the *Evaluate Agent* connector can act as a gate).

## B7. Limits and error codes [L flow-agent; L error-codes; L flow-asynchronous-response]

| Item | Value |
|---|---|
| Agent → workflow/flow synchronous response | **100 seconds** (Learn flow-agent page and error codes). ⚠ The async page and training say "two minutes". Design for **under 100 s** |
| Tool input types, classic agent flows | Text, Boolean, Number |
| Tool input types, new workflows designer | Text, Number, Yes/No, plus **Date, Email, File** [CAT lab]. ⚠ The training module says Number/String/Boolean. Verify. Serialise tables and records as JSON text either way |
| Copilot Studio connector | 300 calls per connection per 60 s [L] |
| Prepaid capacity exhausted | New workflow runs are blocked [L] |
| Large data | Pass links, not content. Channel message size is limited (Part C) |

| Error | Cause → fix |
|---|---|
| `FlowActionTimedOut` | Over 100 s → make it faster, use Express mode, go async only where the channel supports it (Teams; not M365 Copilot or telephony, B8), or use A6.1 with an out-of-band notice |
| `FlowActionBadRequest` | Inputs or outputs changed after attaching, or an unsupported type → Refresh the tool and fix the types |
| `BindingKeyNotFoundError` | Inputs added, removed or renamed → remove and re-add the tool |
| `FlowActionException` | Error inside the flow → check run history |
| `ExecutionTimeout` | The tool exceeded its configured timeout |
| `AsyncResponsePayloadTooLarge` | Payload too large → select fewer columns, limit row count, return links |
| `DataLossPreventionViolation` | DLP policy → align the connector groups or the policy |
| `ContentError` | Topic content errors: missing node properties, bad YAML, Power Fx |
| Users asked to "connect" in a loop [C] | Credential mode or Teams runtime → test in Teams with a non-maker user |
| Tool missing from the agent | Not **published**, wrong trigger, no Respond, async on, not in a solution, not on the plan (B3.8) |

## B8. Channels × harness

| Channel | Microsoft Copilot harness | Standard | Customer Conversation |
|---|---|---|---|
| Microsoft 365 Copilot | Yes [L] | Yes | — |
| Teams | Yes [L] | Yes | — |
| Demo website / web embed | Yes [L] ⚠ msagent-assistant README says Teams and M365 Copilot are the only supported channels for this harness; verify | Yes | Website chat |
| Telephony / voice | **No** (use another harness) | Yes (real-time voice, D365 Contact Center) | Phone number |
| MCP / A2A channel (expose agent) | Preview (Oct 2026) [L]; check per harness | — | — |
| WhatsApp via ACS | — | No new connections after 23 Oct 2026 [L] | — |

- **Async callbacks:** Teams only (tested). **Not** M365 Copilot or telephony [L]. In M365 Copilot, notify out of band (B3.8).
- Check the Learn page *Available channels for agents* before choosing a harness. This table is a summary only.

## B9. Writing instructions and descriptions [L generative-mode-guidance; L authoring-instructions]

The orchestrator picks tools, knowledge and agents by **name and description**, and names weigh more.

**Instructions**
- Cover purpose, audience, boundaries, escalation, tool-use rules and response format.
- Use specific verbs, and tool names exactly as they appear.
- Keep a short list of things the agent must never do.
- Procedures belong in skills; enforcement belongs in workflows and hooks.
- Instructions can't change platform fallback messages.
- Describe knowledge sources generically.
- List every outcome the tools can return, and say how to respond to each, including callbacks.

**Descriptions**
- One or two sentences: what it does, when to call it, and its key inputs.
- Input descriptions include an example value and format.
- Output descriptions explain how the agent should use the result.

---

# PART C — KNOWN GAPS (be honest about these; research before relying on them)

- **Credit math.** This skill holds no rates. Use the Learn billing-rates page (`requirements-messages-management`) and the Copilot Credit estimator. A workflow's cost is actions per run × runs. Dataverse MCP non-search tools are billed per 10 responses. (Reported, `[U]`: workflows need no separate Power Automate licence.)
- **Environment strategy.** Managed Environments, environment groups and rules, early-release environments (needed for Frontier), region and data residency, new-infrastructure eligibility, and locking down the default environment.
- **DLP specifics.** How DLP gates HTTP, MCP, knowledge sources, channels and event triggers; endpoint filtering. Enforcement errors show up as `DataLossPreventionViolation`.
- **Trigger and node details.** Trigger conditions, concurrency, pagination, run-duration limits, loop limits, channel message size (`OutgoingMessageSizeTooBig`).
- **Security (general practice; apply it always).**
  - **Prompt injection:** email, web, uploads and tool results are untrusted. Never let untrusted content alone trigger writes; keep writes in workflows with deterministic checks; deny risky tools in a Pre tool use hook; least privilege everywhere.
  - Not yet covered: Purview audit and DSPM, transcript retention, customer-managed keys, Conditional Access for agent identities.
- **Testing.**
  - Test each workflow node; use test data, not production.
  - Add evaluation gates in pipelines through *Evaluate Agent*.
  - Load-test against the 300-per-60-s connector limit and Dataverse service protection limits.
- **Operations.** Alerting runbook, rollback of managed solutions, connection ownership when a maker leaves (prefer service principals), hook latency budget.
- **Standard harness depth.** Topics and Power Fx are covered only lightly. For a deep classic build, read Learn's classic authoring docs.

---


**Key sources** (as of 2026-11-22):
- learn.microsoft.com/microsoft-copilot-studio/: whats-new · harnesses-overview · agents-experience/faqs-copilot-harness · agents-experience/authoring-agent-account · agents-experience/memory-overview · workflows-experience/flow-agent · workflows-experience/faq-workflows · flow-asynchronous-response · error-codes · configure-no-maker-authentication · knowledge-add-dataverse · guidance/alm
- learn.microsoft.com/power-apps/maker/data-platform/data-platform-mcp
- microsoft.github.io/mcscatblog/posts/hooks-in-copilot-studio/ · microsoft.github.io/mcs-labs/labs/mcs-hooks/ · microsoft.github.io/mcscatblog/posts/combining-agent-flows-and-agents-gotchas-errors-and-patterns/
- Copilot Studio blog 18 Nov 2026 ("Build and manage business processes with Microsoft Copilot Studio") · Ignite 2026 Book of News