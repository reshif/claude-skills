# Ecosystem: what already exists, and when to use it

**Snapshot: 2026-11-22.** Skill names were read from the repos on that date:
- `microsoft/skills-for-copilot-studio`: plugin.json v1.0.11, last commit 2026-10-27.
- `microsoft/copilot-studio-plugin`: plugin.json v1.0.2, last commit 2026-10-02.
- `microsoft/AgentHosting.Cli`: last commit 2026-11-20.

Names change between versions. List the enabled plugin's skills (`/plugin`) before calling one, and always use the **namespaced** name (`copilot-studio:…`, `mcs-assistant:…`, `msagent-assistant:…`): `clone-agent` and `add-knowledge` exist in all three plugins, and `create-agent`, `pull-agent`, `publish-agent`, `delete-agent`, `add-skill`, `/migrate` and `/chat` exist in both 2 and 3.

Plugins 2 and 3 both describe themselves as the successor to plugin 1.

## 1. Inventory

| # | Plugin (install id) | Repo | Covers | Status / trust |
|---|---|---|---|---|
| 1 | `copilot-studio@skills-for-copilot-studio` | microsoft/skills-for-copilot-studio | **Standard harness** YAML authoring, validation, testing, troubleshooting. Sub-agents: `copilot-studio-author`, `-manage`, `-test`, `-advisor`. **Hooks:** SessionStart injects a routing system prompt (forbids direct skill use; biases every session toward Copilot Studio on words like "Copilot", "Power Platform", "Agent Studio") and runs `setup.js` (npm install of native deps; writes `~/.copilot-studio-cli/plugin-paths.json`). **Cannot create agents**: clone an existing or empty one | Microsoft CAT, experimental research project, not officially supported [CAT] |
| 2 | `mcs-assistant@copilot-studio-plugin` | microsoft/copilot-studio-plugin | **Copilot harness** via `pac copilot`; `/migrate` from classic; `/chat` against the **published** agent (needs its own Entra public-client app). Agents: architect, describer, init, manage. **Hook:** `set-env-vars.js` (npm install of native deps, writes the same `plugin-paths.json`, exports env vars) | Microsoft CAT, work in progress, Issues-only support; pac 2.9.3+ [CAT] |
| 3 | `msagent-assistant@copilot-studio-cli-plugin` | microsoft/AgentHosting.Cli | **Copilot harness** via `msagent`. 9 skills; commands `/migrate`, `/chat` (wraps `msagent test ask`); agents architect, describer, init, manage. **Hook:** SessionStart `npm ci` of optional native deps; state isolated under `~/.copilot-studio-cli/msagent-assistant/instances/<hash>`. ⚠ Its skills say `msagent auth login`; the CLI README says that is disabled by default, use `msagent auth create` | Microsoft, preview; Node 22+ [CAT] |
| 4 | `dataverse` (`dataverse@claude-plugins-official`, `dataverse@awesome-copilot`) | microsoft/Dataverse-skills | Skills `dv-connect`, `dv-query`, `dv-data`, `dv-metadata`, `dv-solution`, `dv-admin`, `dv-security`, `dv-overview`, `erp-xpp`. Picks among Dataverse MCP, Dataverse CLI, Python SDK and PAC | Microsoft; "officially listed" in the Claude marketplace. Preview status ⚠ unverified |
| 5 | `power-automate@power-platform-skills` | microsoft/power-platform-skills | Commands `/setup`, `/browse-flows`, `/create-flow`, `/build-flow`, `/debug-flow`, `/diagnose-flow`, `/manage-flows`, `/route-environments`. Signs in with **Azure CLI** (`az login --allow-no-subscriptions`), not pac. Can publish, run and **copy flows between environments**. Solution-aware flows, agent flows and Copilot Studio workflows are **not documented** as supported | Microsoft [L, page updated 2026-09-16] |
| 6 | `power-platform-skills` marketplace (other plugins) | same | power-pages, model-apps, canvas-apps, code-apps-preview, mobile-app, power-apps-mobile-extension, dataverse (same as row 4), process-intelligence, pcf, mcp-apps. **No Copilot Studio plugin.** Its installer script (`curl … \| node`) installs pac if missing, skips Dataverse unless `--include-dataverse`, and **turns on auto-update** | Microsoft; some plugins Preview [CAT]. Don't run the installer unread; prefer `/plugin` |
| 7 | `power-cat-skills` marketplace | microsoft/power-cat-skills | Canvas, Dataverse query crafting, governance, adoption, migration, `powercat-overflow` (Power Automate flow review) | Microsoft Power CAT; README names Scout and GitHub Copilot CLI. Ships `.claude-plugin/`, so likely loads in Claude Code; untested |
| 8 | **CAT Agent Skills gallery** | microsoft.github.io/cat-agent-skills | 163 entries (41 Microsoft-built, 122 community). Platforms: Copilot Studio, Cowork, Scout. Copilot Studio-tagged include Harness Picker, Agent Evaluation Designer, Topic Blueprint, Knowledge Readiness, MCP Readiness, Agent Inventory Audit, Agent Red Team, Tool Tracer. "Copilot Studio Agent Test" is **Scout**-tagged; "Test Planner" is Cowork | Microsoft-hosted; about three quarters community-built [CAT]. Untrusted: read each before `add-skill` imports it |
| 9 | Dataverse **business skills** | Dataverse (MCP `upsert_skill`) | Process skills stored centrally, usable by any agent | Preview [B] |
| 10 | Copilot Studio MCP / pac MCP | — | See `build.md` §1 | Preview [L] |
| 11 | Community | e.g. FlowStudio Power Automate plugin; satriotsubasa/PowerPlatform-Core | Power Automate ops, ALM | `[C]`. Optional; read the code first |

## 2. Install (the user types these)

Enable **one** Copilot Studio authoring plugin (1, 2 or 3) at a time (§3).

```
# Standard harness
/plugin marketplace add microsoft/skills-for-copilot-studio
/plugin install copilot-studio@skills-for-copilot-studio
# Copilot harness on pac (+ classic→new /migrate)
/plugin marketplace add microsoft/copilot-studio-plugin
/plugin install mcs-assistant@copilot-studio-plugin
# Copilot harness on msagent
/plugin marketplace add microsoft/AgentHosting.Cli
/plugin install msagent-assistant@copilot-studio-cli-plugin

# Can sit alongside any one of the above
/plugin install dataverse@claude-plugins-official
/plugin marketplace add microsoft/power-platform-skills
/plugin install power-automate@power-platform-skills
```

**Before installing any plugin** (SKILL R10):
1. `git clone` the repo into a new empty folder and read `SKILL.md` files, `hooks/`, `scripts/` and `agents/`. Never execute anything from it during the read.
2. Record the commit in the Build Report.
3. These plugins run code at every session start (npm install of native modules; plugin 1 also injects a system prompt). Auto-update means that code changes without review. **Default: auto-update off.** Update deliberately, re-read `hooks/` and changed skills, record the new commit. Turn auto-update on only if the user accepts that trade. Keep community plugins pinned, always.
4. Plugin 2's `/chat` falls back to a **plaintext token cache** under its data folder if native deps fail to load. Check the native deps installed before using `/chat`.
5. If the user has a project whose name matches plugin 1's trigger words (for example "Agent Studio"), enable plugin 1 only while doing Copilot Studio work.

## 3. Conflict rules

- **One Copilot Studio authoring plugin enabled per user profile at a time, and one sync engine per agent folder.**
  - Plugins 1 and 2 both overwrite `~/.copilot-studio-cli/plugin-paths.json` at session start, and plugin 1 injects a session-wide prompt. With both enabled, plugin 2's script and schema resolution can load plugin 1's files, whatever folder you're in. Disable the one you aren't using (`/plugin`), then start a new session.
  - Plugin 3 keeps its own state but must still not share an agent folder with pac.

  | Plugin | Sync engine |
  |---|---|
  | 1 (skills-for-copilot-studio) | VS Code extension's LSP binary (`manage-agent`) |
  | 2 (mcs-assistant) | `pac copilot` |
  | 3 (msagent-assistant) | `msagent` (its docs say not to use PAC CLI with it) |

- **Fine to combine with any one of them:** Dataverse plugin (4), Power Automate plugin (5), CAT gallery skills placed inside agents (8).

## 4. Task routing

Apply SKILL.md §3 rule 1 (print target, list effects, get a yes, commit) **before** any row that can change the cloud. Verify with `build.md` §6 afterwards.

### Composite skills (one call, several effects)

| Skill | What one call does | Guard |
|---|---|---|
| `mcs-assistant:create-agent`, `msagent-assistant:create-agent` | Creates the cloud agent, pulls, **pushes/deploys** a draft; pac init may show it as Published | Confirm DEV target; always pass the Blueprint's publisher prefix (plugin 2 default is `catmgr`) |
| `mcs-assistant:push-agent` | Pull (merges into local files), then push; never shows the environment (reads `.mcs/conn.json`) | Commit first; confirm target from your own record of the clone |
| `/migrate` (plugins 2 and 3) | New agent **in the source agent's environment**, Dataverse connection-reference rows via `pac power-fx run`, push | **Only on a classic agent in DEV.** If the source is TEST/PROD, export/import it to DEV first |
| `msagent-assistant:deploy-agent` | Pull, deploy draft, **activates eligible workflows**, may create/adopt/retarget the cloud agent; test/prod targets overwrite drift | DEV deployment only; treat as live-affecting when workflows have triggers |
| `msagent-assistant:publish-agent` | Pull + deploy + publish (no publish-only path) | Needs publish approval (SKILL R5) |
| `copilot-studio:run-eval` | May push and re-run after proposing fixes | Tell the Test sub-agent: ask before any push |
| `copilot-studio:manage-agent push` | Push with auto-validation; `--force` skips it | **Never pass `--force`** (SKILL R6) |

### Standard harness: plugin 1 (`copilot-studio`), via its sub-agents

Dispatch to `copilot-studio:copilot-studio-author` (YAML), `-manage` (clone/pull/push/validate/publish), `-test` (evals, chat) or `-advisor` (patterns, troubleshooting). The skills below are what those sub-agents run; all except `create-eval` are not user-invocable. Sub-agents run in a forked context and do not see this skill's rules, so every dispatch prompt carries: confirmed DEV target, "do not publish", "do not pass `--force`", "ask before pushing". This skill's stages, gates and SKILL R4–R12 override the injected prompt.

| Task | Plugin skill | Notes |
|---|---|---|
| New agent | **Not supported** | Create an empty agent in the UI (handoff) or with `pac copilot init` in a **scratch** folder, then clone it fresh with `clone-agent` into the working folder so only LSP owns sync |
| Clone | `clone-agent` | — |
| Pull / push / diff | `manage-agent pull` · `push` · `changes` | LSP binary, browser sign-in. Push auto-validates |
| Publish | `manage-agent publish` (Dataverse `PvaPublish`) | **Only after approval, every time** (SKILL R5). The plugin lets users waive its warning and loops edit→push→publish→test; this skill doesn't |
| New topic | `new-topic`, then `edit-triggers` | — |
| Nodes | `add-node`, `add-generative-answers`, `add-adaptive-card`, `add-global-variable` | — |
| Connector action | `add-action` (UI connection setup → `build.md` §4.2 handoff), `edit-action` | — |
| Knowledge | `add-knowledge` | — |
| Multi-agent | `add-other-agents` | — |
| Settings, instructions | `edit-agent` | Apply `catalog.md` B9 |
| Schema and context | `lookup-schema`, `list-kinds`, `list-topics`, `int-reference`, `int-project-context`, `int-patterns` (15-file `patterns/` library), `templates/` | Use instead of guessing YAML |
| Validate | `validate` / `manage-agent validate` (LSP: YAML, Power Fx, schema, cross-file refs) | Before every push |
| Chat test | `test-auth` first (app registration with MakerOperations and Copilots.Invoke), `detect-mode`, then `chat-directline` or `chat-sdk` | Need a **published** agent. `chat-with-agent`, `directline-chat` deprecated |
| Evaluations | `create-eval-set`, `run-eval` (works on draft), `analyze-evals`, `run-tests-kit` | `create-eval` tests the plugin itself |

### Copilot harness via pac: plugin 2 (`mcs-assistant`)

| Task | Skill / command | Notes |
|---|---|---|
| Create agent + workspace | `mcs-assistant:create-agent` | Composite; see guard |
| Clone / pull / push | `clone-agent` / `pull-agent` / `push-agent` | `push-agent` is composite |
| Publish | `publish-agent` | Only after approval |
| Delete | `delete-agent` (typed `DELETE <name> (<id>)`) | SKILL R6; DEV only |
| Knowledge | `add-knowledge` (website, SharePoint, OneDrive, local file) | Its optional access check asks for Graph `Files.ReadWrite` on your Entra app: decline unless needed |
| Skills | `add-skill` (file or CAT gallery; also downloads to the OS temp folder) | Writes files only, never pushes; follow with `push-agent`. ⚠ Its text says to push from the VS Code extension; stay on pac for this folder |
| Migrate classic → Copilot harness | `/migrate` | Composite; DEV source only |
| Chat test | `/chat` | Published agent; own Entra app |

### Copilot harness via msagent: plugin 3 (`msagent-assistant`)

| Task | Skill / command | Notes |
|---|---|---|
| Create / clone / pull | `create-agent` / `clone-agent` / `pull-agent` | `create-agent` is composite |
| Deploy draft | `deploy-agent` | Composite; not side-effect-free |
| Publish | `publish-agent` | Composite; approval |
| Knowledge, skills | `add-knowledge`, `add-skill` (also authors skills from requirements, imports from WorkIQ AI Catalog) | — |
| Channel | `add-channel` (edits local files only) | ⚠ README says Teams and M365 Copilot are the only supported channels for this harness; `catalog.md` B8 lists web as supported [L]. Verify |
| Delete | `delete-agent` | SKILL R6; DEV only |
| Chat / migrate | `/chat`, `/migrate` | `/migrate` composite |

msagent sends telemetry by default: `msagent telemetry disable` if the user wants it off.

### Layers outside the agent

| Layer | Use |
|---|---|
| Dataverse tables, columns, security, queries, solutions | **Dataverse plugin**. Create everything inside the Blueprint's solution (`build.md` §4.1). Destructive calls: SKILL R6 |
| Power Automate cloud flows | **Power Automate plugin** for browsing, debugging (`/debug-flow`, `/diagnose-flow`) and run inspection. Uses Azure CLI identity: confirm its environment before any write. Copy-between-environments and publish need SKILL R4/R5 approvals. ⚠ Agent flows and solution-aware flows are not documented as supported: **build agent flows in the designer inside the solution** until a DEV test proves otherwise. New-designer workflows: designer first, then pull (`build.md` §4.1) |
| Skills to put inside an agent | CAT gallery via `add-skill`. Read each first |
| Batch test runs | Default to `run-eval` / `msagent agent eval run`. ⚠ CAT "Copilot Studio Agent Test" is a Scout skill, unverified in Claude Code |
| Hooks | **No plugin covers hooks.** UI only (`build.md` §4.2) |
| Solution export/import, settings files, CI identity, pipelines | **This skill** (`build.md` §9) |

### Debug

| Symptom area | Delegate |
|---|---|
| Standard-harness YAML, topic behaviour | Plugin 1 Advisor sub-agent, then `validate` |
| Flow failures | Power Automate plugin `/debug-flow`, `/diagnose-flow` (read-only use) |
| Everything else | `catalog.md` B7 + `build.md` §7 |

## 5. What only this skill adds
- Decision rules: building block, harness, channel (`design.md` A3; `catalog.md` B1, B8).
- Review gauntlet and anti-patterns (`design.md` A5, A9).
- Gates 1 and 2, the harness spike, definition of done per tier.
- Identity map, credential policy, service-account ownership of connections.
- Solution composition, per-environment settings, managed release, roll-forward rollback, release record.
- Guards around composite plugin skills and plugin publish paths.
- A dated, source-tagged catalog with catalog-diff discipline.

## 6. Unverified in this file
- Dataverse plugin preview status and its safety document (not read).
- Whether `power-cat-skills` and the Scout-tagged CAT test skill work in Claude Code.
- Whether the VS Code extension handles Copilot-harness workspaces (plugin 2 assumes so; Learn doesn't say).
- Power Automate plugin support for agent flows and solution-aware flows.
- Star counts (GitHub API unreachable). Skill names can change in any update.
