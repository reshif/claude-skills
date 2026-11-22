# Build, test and release (lifecycle stages 0, 3–7)

Rules here are cited as **build 0.1–0.10**; SKILL.md rules are **SKILL R1–R12** and take precedence where they differ. Facts shared with design (harness capabilities, error codes, credentials) live in `catalog.md` (B-sections). For which Microsoft plugin skill to call at each step, see `ecosystem.md`.

## 0. Ground rules

1. **Mutating calls go to DEV only, for every tool.** This covers `pac`, VS Code Apply, `msagent`, Dataverse MCP `create_*`, `update_*`, `delete_*` and `upsert_skill`, Copilot Studio MCP, `pac copilot mcp`, and any plugin.
   - TEST and PROD are reached only through §9. Exceptions are listed in SKILL R4 (the §5.0 spike and the §9.4 (b) msagent route to TEST). PROD steps are always run by a human.
   - Before the first call in a session, print the target environment ID, org URL, agent name and schema name, and get the user's confirmation. Do it again if the target changes.
2. **Deploying is not publishing.** `pac copilot push`, VS Code **Apply** and `msagent agent deploy` all change the agent in the cloud. They are not the same as publishing:
   - Apply/push: "The apply action isn't the same as a publish operation in Copilot Studio, and doesn't publish the agent."
   - msagent: "Deploying updates the cloud draft. Publishing is what makes changes available to users."
   - Publishing (`pac copilot publish`, `msagent agent deploy --publish`, or the UI button) needs a separate yes from the user, every time, in every environment (SKILL R5). Gate 2 approval is not publish approval.
3. **Commit before you pull.**
   - VS Code **Get** asks to overwrite uncommitted local changes [L].
   - `pac copilot pull` does a three-way merge into your files [L].
   - `msagent agent pull` replaces local workflow files [CAT].
   - So run `git status` and commit or stash first, every time.
4. **One toolchain per workspace.** Pick `pac`, `msagent` or VS Code for each workspace and never mix them. The msagent docs say not to use the PAC CLI together with it for these commands [L/CAT].
5. **Ignore local sync state.** Before the first commit, add `**/.mcs/` and `**/.config/agent.config.json` to `.gitignore` [L msagent source-control]. Treat `.mcs/conn.json` as machine-local: never commit, print or edit it. Plugin 1 and `/migrate` read tenant and environment IDs from it; that is expected. It is also the real push target, so if you can't confirm the target another way, ask the user to confirm the environment shown in Copilot Studio for that agent.
6. **No secrets in files or chat.** Keep keys, tokens and passwords out of YAML, JSON, settings files and Git. Use connection references, environment variables (Key Vault-backed for secrets) and the CI secret store. Never echo tokens.
7. **Follow your clone, not the docs.** Learn's sample file names are inconsistent. Copy the names, folders and `kind:` values from a fresh clone, init or `msagent agent create` of the user's agent. Never invent a schema; copy an existing component of the same kind.
8. **Where commands run.** Run `--help` before the first use of any command on a machine (SKILL R11).
   - The VS Code extension and `msagent` are documented for **Windows and macOS only** [L]. `pac` and CI agents also run on Linux.
   - A cloud sandbox with no route to Power Platform can't push. In that case, deliver the files plus an exact runbook, or use a linked device shell.
   - **Never claim a push, import or publish happened unless you saw its output.**
   - Cloud operations cost credits and touch real data. "Running them from a local terminal doesn't make them a dry run."
9. **Small diffs.** One component or feature per commit, a clear commit message, and validation (§6) before every push.
10. **Stop at handoffs.** When a step needs UI work (§4.2), emit the handoff task and **wait** for confirmation before continuing.

---

## 1. Toolchain by harness

| Need | Standard harness (classic) | Microsoft Copilot harness (new experience) |
|---|---|---|
| IDE sync | **Copilot Studio VS Code extension**, GA. Every Learn page for it is scoped to standard-harness agents and agent flows [L] | Not documented on Learn as of the snapshot. ⚠ `mcs-assistant`'s `add-skill` text assumes the extension can clone and push CLI agents. Verify before relying on it; never mix it with pac in one folder |
| CLI | `pac copilot clone / init / pull / push / pack / publish / status / list / quarantine` [L] | **Path A:** `pac copilot init --authoring-mode cli-copilot` (CliCopilot = GitHub/Microsoft Copilot harness shape [CAT]), then pull/push/publish [L]. **Path B:** `msagent` (Copilot Studio CLI, preview, .NET 10 SDK) [L] |
| Coding-agent plugin (install **one**) | `copilot-studio@skills-for-copilot-studio`. Experimental, Node 18+, uses the VS Code extension for sync [CAT] | `mcs-assistant@copilot-studio-plugin` (pac 2.9.3+, includes `/migrate` from classic) **or** `msagent-assistant@copilot-studio-cli-plugin` (msagent) [CAT]. Both are work in progress |
| Power Platform CLI MCP | `pac copilot mcp --run` exposes `pac` commands to an MCP client [L]. It is **not** Copilot Studio MCP | Same |
| **Copilot Studio MCP** | — | `npx -y @microsoft/copilot-studio-mcp@latest` (stdio). Tools: `get_copilot_studio_skills` (call it first), `manage_agents`, `manage_workflows`, `discover_resources`, `get_consumption` [L]. Sign in with a browser, then select the environment [L]. Drafting is separate from publishing [L]. Announced as public preview [B] |
| Packaging | `pac copilot pack` → solution zip [L]. Whether the zip is managed is ⚠ unverified (§9.1) | Path A: same ⚠. Path B: no solution packaging; it promotes to named deployment targets [L/CAT] |
| Hooks | n/a (the standard harness has none) | **No documented file format.** Mark `GAP` and build in the UI (B2.7) |

**Plugin install commands, hooks and conflict rules:** `ecosystem.md` §2–3 (one authoring plugin enabled per user profile).

---

## 2. Setup, identity and preflight

### 2.1 Tools
- **`pac`** 2.9.3 or later; check by running `pac`. **VS Code** 1.80+ with the extension `ms-CopilotStudio.vscode-copilotstudio` from publisher **Microsoft** (standard harness only) [L]. **Git**.
- **msagent:** `dotnet tool install --global Microsoft.Agents.Hosting.Cli --prerelease`, then `msagent --version` [L].
- **Copilot Studio MCP:** add it to the MCP client, for example in VS Code `.vscode/mcp.json`:
  ```json
  {"servers":{"copilot-studio-mcp":{"command":"npx","args":["-y","@microsoft/copilot-studio-mcp@latest"]}}}
  ```
  Learn doesn't document a Claude Code registration [L/CAT].

- msagent sends telemetry by default; `msagent telemetry disable` turns it off.

### 2.2 Interactive auth (maker in DEV)
- **pac:** `pac auth create --name DEV --environment <dev>`, then `pac auth who`.
  - `clone`, `pull` and `push` need a profile; `init` needs one only with `--environment`; `pack` needs none [L].
- **msagent:** ⚠ Learn says `msagent auth login`, but the repo README (20 Nov) says `msagent auth create --name Dev` and that `login` is off by default. Run `msagent auth --help`, then `msagent env list` and `msagent env select '<env-id>'` [L/CAT].
- **VS Code:** Copilot Studio icon → **Sign In** in the browser, with MFA [L].

### 2.3 Fields the Blueprint must supply (fill from design.md A4.3 if any is missing)
- DEV, TEST and PROD environment IDs.
- **Solution name and publisher prefix** (for example `ReturnsDesk` / `sup`).
- Schema name.
- Git repo and branch strategy.
- Toolchain: pac, msagent, MCP or UI.
- Deploy identity per tier.
- Connection-reference logical names and their **owners** per environment.
- Environment-variable names and values per environment.
- Evaluation set path and thresholds.
- Approvers for TEST and PROD.
- Release route (§9.4) and the spike result (§5.0).

### 2.4 Preflight (stop on any failure)
- [ ] Harness known and toolchain chosen (§1). (The §5.0 spike is Stage 3 and is checked at Gate 2, not here.)
- [ ] Exactly one Copilot Studio authoring plugin enabled, its commit recorded, its hooks read (`ecosystem.md` §2).
- [ ] For plugin 1 chat/eval tools: app registration with MakerOperations and Copilots.Invoke; for `/chat`: its own Entra public-client app; `test-auth` passes.
- [ ] msagent telemetry setting agreed with the user.
- [ ] Dataverse exists in DEV, TEST and PROD, with **Dataverse search** on.
- [ ] New experience toggle and release channel verified (Early, if any Frontier feature is used).
- [ ] DLP in all three environments allows every connector, HTTP endpoint and MCP endpoint the design uses: Dataverse, Approvals, Outlook, Copilot Studio connector and so on.
- [ ] Managed Environments are on, if Power Platform pipelines will be used.
- [ ] CI app registration exists and is an **Application User** with a least-privilege role in TEST and PROD (§9.2).
- [ ] Service accounts exist for user-delegated connections (§9.2).
- [ ] Non-maker test users exist, with roles.
- [ ] Teams admin approval path is named.
- [ ] Maker licence and read/write on the agent [L].
- [ ] Git repo is clean and `.gitignore` covers build 0.5.
- [ ] Every open *Verify in tenant* item is confirmed by a named person or accepted as a risk.

---

## 3. Workspace layouts (your clone is authoritative)

### 3.1 Standard harness (VS Code / pac classic) [L]
```
<agent>/
├── agent.mcs.yml            # kind: GptComponentMetadata [CAT]
├── settings.mcs.yml
├── connectionreferences.mcs.yml
├── icon.png
├── actions/                 # connector tools
├── topics/                  # kind: AdaptiveDialog
├── trigger/                 # kind: ExternalTriggerConfiguration
├── knowledge/ └── files/    # new files here upload on Apply/push
└── workflows/<Name>/        # metadata.yaml + workflow.json
```
**Topic skeleton** [L]. Copy and modify it; give every node a new ID.
```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnConversationStart
  id: main
  actions:
    - kind: SendActivity
      id: sendMessage_M0LuhV
      activity:
        text:
          - Hello, I'm {System.Bot.Name}. How can I help?
```

### 3.2 Copilot harness, pac CliCopilot [CAT]
- `settings.mcs.yml` holds the instructions. Check that it has a `template:` starting with `cliagent-` and `configuration.authoringModel: CliCopilot`.
- `agent.sync.yaml`: never hand-edit it.
- `behaviors/` holds skills (`kind: InlineAgentSkill`).
- `capabilities/knowledge/`, `capabilities/tools/`, `workflows/`.
- **No topics.** Never edit `.mcs/`.

### 3.3 msagent project
Use the layout that `msagent agent create` or `msagent agent pull` produces. Don't hand-edit the sync or config folders (build 0.5).

**Notes**
- Knowledge documents uploaded in the UI are not downloaded automatically. Get them from *Remote Knowledge Files* [L].
- Prefer building flows and workflows in the designer, then pulling. Hand-edit `workflow.json` only for small, verified changes.

---

## 4. Blueprint → Build Plan

### 4.1 Mapping (every Blueprint item gets one row; none left out)
| Blueprint item | Where it lives | How | Verify |
|---|---|---|---|
| **Solution + publisher** | Solution | Portal (Solutions → New) or `pac solution init`. Create it **before** any table or flow, and set it as the preferred solution | `pac solution list` |
| Dataverse tables, columns, alternate key (business key) | Solution | Portal *inside the solution*. Turn Searchable on per column; add synonyms in the agent. Use Dataverse MCP `create_table` only in DEV and only if the solution is specified | Duplicate insert is rejected; a grounded question works |
| Security roles | Solution (roles); assignments are per environment | Portal; list assignments in the release runbook | A test user sees, or doesn't see, the right rows |
| Environment-variable definitions, connection references | Solution; values in the settings file (§9.3) | Portal inside the solution | Import asks for no unset values |
| Agent instructions, model | `agent.mcs.yml` / `settings.mcs.yml` | Edit YAML | Diff, then test pane |
| Topic (standard) | `topics/` | Copy a sibling of the same kind | Validate, then test pane |
| Skill (Copilot, pac) | `behaviors/` | Copy a sibling | Preview |
| Connector tool | `actions/` or `capabilities/tools/` + connection references | Add once in the UI, pull, then edit the description and inputs (B9) | Test call |
| Flow / workflow tool | `workflows/<Name>/` (standard). Copilot harness: ⚠ capture by pull unverified | Designer first (B3), publish, attach, pull | Run history covers every branch |
| Standalone workflow (Copilot) | msagent project | `msagent agent create --agent-type MCSWorkflow …` [L/CAT] | Real test run |
| Knowledge files | `knowledge/files/` | Drop the file in, then push | A grounded question works |
| Event trigger | `trigger/` | Copy the pattern | Fire the event in DEV |
| **Hook workflows** (Copilot) | Workflow in the solution; the binding sits in the agent | **UI only:** Add hook → New workflow (B2.7) | Inspect the Preview payload, then test in a new chat |
| Agent auth mode, channels, sharing, Teams availability | Agent settings; Teams admin centre | UI handoff | Non-maker test in Teams |
| Memory, Work IQ writes, connected agents, MCP tools | Agent settings | UI, or YAML if it appears in the clone | Behaviour test |
| Evaluation set | `/eval/<agent>.csv` in Git | Import in the UI, or `msagent agent eval run --from-csv` | Evaluation result |
| Telemetry, cost alerts, agent limits, DLP | PPAC / Agent 365 | UI handoff with a named owner | Alert fires in TEST |
| Per-environment values | `/deploy/<env>.settings.json` | `pac solution create-settings` (§9.3) | — |

### 4.2 UI handoff (for every row that needs UI work)
1. Write a numbered task: exact click path, expected value, who does it, and the evidence needed (screenshot or exported JSON).
2. Append it to `ui-state.md` in Git, with: component | DEV / TEST / PROD done-date | verifier.
3. **Stop and wait** for confirmation.
4. Where pull or unpack can't capture a component, **Git is not its source of truth.** Say so in the Build Report, and prove the component by recreating it in TEST.

---

## 5. Build loops

### 5.0 Harness ALM spike (mandatory for a Copilot-harness design, before Gate 2)
This is the one permitted pre-§9 import outside DEV (SKILL R4 a). Prefer a **dedicated spike environment**; use TEST only if there is none, and get the user's yes for that import.
1. In DEV, build a throwaway agent named `Spike_<date>` in its own solution `Spike_<date>`, with **one workflow tool, one hook and one skill**, using the chosen toolchain.
2. Try the intended release route (§9.4) from DEV to the spike/TEST environment: a managed solution export and import, or msagent deployment targets.
3. Check that the agent, workflow, hook and skill all arrive in TEST **and run**.
4. Record the result, with the exact commands, and send it to Gate 2 (design.md A4.5):
   - **PASS:** the pipeline route is allowed.
   - **PARTIAL:** the agent arrives but some components don't. Write a **Manual Release Runbook**: the §4.2 tasks for each missing component, done by a human per environment with evidence. The Blueprint must say "manual release" and be re-approved.
   - **FAIL:** stop. Go back to Stage 2 and re-choose the harness (design.md A3 rule 12), or get written approval for a manual rebuild in each environment.
5. **Clean up:** delete the spike solution in the target (managed: uninstall `Spike_<date>`; msagent: delete the deployment and agent) and in DEV, with a yes for each delete (SKILL R6). Record the deletion.

### 5.1 New agent, standard harness (pac)
**Solution first:** create the Blueprint's solution in DEV before any cloud init. Recommended: init **locally** (no `--environment`), then pack into the Blueprint's solution and import. Warn the user before running init with `--environment`: it creates its own solution from the prefix and may publish.
```powershell
pac auth create --name DEV --environment <dev>
pac copilot init --name "Contoso Support Agent" --publisher-prefix <blueprint prefix> --project-dir contoso-support          # local scaffold
pac copilot pack --project-dir contoso-support --solution-name <BlueprintSolution> ...                                        # check --help for flags
# or, after a warning and a yes:  ... init ... --environment <dev>
```
- The folder's sync engine is **pac**. If you plan to use plugin 1 (LSP) instead, init in a scratch folder, then `copilot-studio:clone-agent` into a fresh working folder (`ecosystem.md` §4).
- With `--environment`, init scaffolds, packs, imports and connects the workspace in one step. Without it, init only scaffolds locally [L].
- The directory must be empty. If the schema name already exists, init stops and points you to `clone` [L].
- On a brand-new environment you may see "Async operations are currently disabled": wait, then retry [L].
- ⚠ If init ran with `--environment`, check which solution the agent landed in and add it to the Blueprint's solution.
- Next: `git init`, write `.gitignore` (build 0.5), commit.

### 5.2 Existing agent, standard harness
```powershell
pac copilot list --environment <dev>
pac copilot clone --bot <botId> --environment <dev> --output-dir agents --display-name contoso-support
```
- The workspace is `agents/contoso-support/`. Use that folder as `--project-dir` [L].
- The destination subfolder must be empty [L].
- `--component-collection`: Learn says both "repeat" and "semicolon-separated", so check `--help`.
- **VS Code:** copy the agent URL, then **Clone agent** (it reads the URL from the clipboard) [L].

### 5.3 Copilot harness

**Path A: pac** [L flags; CAT mapping]
```powershell
pac copilot init --name '<name>' --publisher-prefix <pp> --environment <dev> --project-dir <empty> --authoring-mode cli-copilot --instructions '<text>'
pac copilot pull --project-dir <dir>
# edit behaviors/, capabilities/, settings.mcs.yml
pac copilot push --project-dir <dir>
pac copilot pull --project-dir <dir>
```
After init, check the `settings.mcs.yml` markers (§3.2). Init may leave the agent showing as Published, so don't promise the user it is draft-only [CAT].

**Path B: msagent** (preview) [L/CAT]
```powershell
msagent agent create --agent-type MCSAgent --agent-name '<name>' --description '<d>' --initial-prompt '<instructions>' --environment-id '<dev>' --project '<dir>' --json
# or clone an existing agent:
msagent agent create --agent-type MCSAgent --mcs-clone-agent-id '<id>' --mcs-clone-environment-id '<dev>' --project '<empty dir>'
msagent deployment create --project '<dir>' --agent-name '<name>' --deployment-name develop --deployment-type dev --environment-id '<dev>'
msagent agent deploy --project '<dir>' --agent-name '<name>' --deployment-name develop --json           # draft
msagent deployment connection update --project '<dir>' --agent-name '<name>' --deployment-name develop --connection-reference '<ref>' --connection-id '<conn>'
msagent test ask --project '<dir>' --agent-name '<name>' --deployment-name develop --query '<q>' --plain
msagent agent pull --project '<dir>' --agent-name '<name>'
```
**Path C: Copilot Studio MCP.** Call `get_copilot_studio_skills` first, then `manage_agents` / `manage_workflows`. A client timeout "doesn't prove that a server-side change failed or was rolled back", so re-read the state before retrying.

**Path D: UI, then pull.** Use this for hooks and for anything the other paths can't do.

### 5.4 The inner loop (all paths)
1. `git status` is clean.
2. **Pull first** (`pac copilot pull`, VS Code Preview then **Get Changes**, or `msagent agent pull`). Resolve conflicts, then commit.
3. Edit **one** component, copying a sibling file.
4. Validate (§6). In VS Code, the Problems pane must show no errors [L].
5. Commit.
6. Push to DEV (`pac copilot push`, **Apply Changes**, or `msagent agent deploy`).
   - VS Code Apply is blocked while remote changes are un-retrieved [L].
   - `pac copilot push` stops on a conflict, so pull and resolve first; a push with nothing to send is a no-op [L].
   - ⚠ msagent test and prod deploys skip the drift check [CAT].
7. Test in the test pane, then in the **target channel** with a non-maker user (B8).
8. In a team, pull every 30–60 minutes [L]. Anyone who edits in the UI pulls and commits the same day.

### 5.5 Publish (only after a yes for this agent and environment, SKILL R5)
```powershell
pac copilot publish --bot <botId> --environment <dev>
pac copilot status --bot-id <botId> --environment <dev>
# msagent: add --publish to agent deploy
```

### 5.6 Migration from classic
- **In-product upgrade** creates a copy (B1).
- **As code:** `/migrate` (plugin 2 or 3) [CAT]. It creates the new agent **in the source agent's environment** and writes connection-reference rows there, so run it only on a classic agent in DEV; if the source is in TEST/PROD, bring it to DEV first (`ecosystem.md` "Composite skills").
- Before `/migrate`, disable plugin 1 if enabled (SKILL R7) and start a new session; recommend removing it once the new agent passes evals.
- Either way, keep the classic agent live until the new one passes the evaluation gate (§8).

---

## 6. Static checks before every push
1. YAML parses, and `kind:` was copied from a sibling component of the same type.
2. IDs are unique, and pasted nodes have been given new IDs.
3. Every referenced topic, skill, action, workflow and connection reference exists.
4. No secrets, and no hard-coded URLs, emails or thresholds; those go in environment variables. Sync metadata (`.mcs/`) is excluded from this check and from Git.
5. Power Fx expressions are balanced and their variables are defined.
6. The diff touches only the intended components.
7. Tool or workflow inputs haven't been renamed or retyped. If they have, refresh or re-add the tool after pushing (B7).
8. Knowledge files are allowed by policy and carry no blocked sensitivity labels.
9. Standard harness with plugin 1: `copilot-studio:validate` clean. Plugins 2 and 3 have no validate skill; this checklist is the gate [CAT].

---

## 7. Conflict and failure playbook
| Symptom | Action |
|---|---|
| Push stops: item changed on the server | Commit, pull (three-way merge), resolve, validate, push |
| Apply button disabled | Preview, then Get Changes, then Apply |
| "workspace not found" | Wrong folder. Use the child folder that clone created (§5.2) |
| clone/init refuses to run | Folder not empty, or schema name already exists. Use an empty folder, or clone instead |
| "Async operations are currently disabled" | Environment still warming up. Wait, then retry |
| VS Code sign-in loops | Clear browser cache, disable browser extensions, check the proxy and account type [L] |
| Errors after push | Check B7. Refresh the tool, check connection references, check DLP |
| MCP call timed out | Re-read the state before retrying [L] |
| Wrong change pushed | `git revert`, then push. Republish if it was already published. Never overwrite another maker's change |

---

## 8. Testing and the evaluation gate
1. **DEV:** exercise each changed path in the test pane; run each workflow branch at least once, including a forced failure (B3.7).
2. **Target channel:** test with a **non-maker** user, which exposes credential problems (B5).
3. **Evaluation set** at `/eval/<agent>.csv` in Git. Cases come from A4.3 and the thresholds come from the Blueprint.
   - Defaults if the Blueprint gives none, and the blocking-case rule: `design.md` A4.3 *Evaluation* (the single definition).
4. **Running evaluations:**
   - **msagent:**
     ```powershell
     msagent agent eval run --project <dir> --agent-name '<name>' --environment-id <env> --from-csv eval/<agent>.csv --name <Run> --watch --timeout-minutes 15 --output run.json
     ```
     Add `--published` to test the live version. Parse `run.json` and fail the job on your own thresholds. **The CLI's exit code is not a documented gate**, and `--watch` can return after a timeout. Test sets are capped at 20 conversations of 6 questions each [CAT].
   - **Standard harness with plugin 1:** `create-eval-set` → `run-eval` (works on the draft) → `analyze-evals`, via the Test sub-agent told to ask before pushing.
   - **Copilot harness on pac (plugin 2 has no eval skills):** import `/eval/<agent>.csv` into the Copilot Studio **Evaluation** UI (handoff, §4.2) or run the *Evaluate Agent* connector from a flow owned by the service account; record the run ID and scores.
   - **Pipelines (any harness):** the *Evaluate Agent* connector, run by the service account.
   - Chat-based tools (`chat-sdk`, `chat-directline`, `run-tests-kit`, `/chat`) need a **published** agent: get a DEV publish yes first.
   - Evaluations call real tools and spend credits (build 0.8).
5. **Cases a script can't run unaided** (a human approver, a 5-day timeout, an outage): run them in TEST with environment variables `TestMode=true`, `ApprovalTimeoutMinutes=2` and `ApproverOverride=<test approver>`. Simulate the outage with a broken connection reference in a cloned test workflow.
6. **Build Report** (Docs artifact, or `reports/<date>.md` in Git):
   - Environment, agent, schema and solution.
   - Commit SHAs.
   - Commands run, with their outcomes.
   - UI handoffs and their status.
   - Evaluation results against thresholds.
   - Whether it was published.
   - `GAP` items.
   - Catalog diffs (to update catalog.md).

---

## 9. Release (DEV → TEST → PROD)

### 9.1 Solution composition and release artifact
- **One solution per deliverable** (for example `ReturnsDesk`, publisher `sup`). It contains: tables, security roles, environment-variable definitions, connection references, workflows and the agent. DEV holds it unmanaged.
- **Release artifact = a managed export from DEV:**
  ```powershell
  pac solution online-version --solution-name ReturnsDesk --solution-version <x.y.z>   # bump every release
  pac solution export --name ReturnsDesk --managed --path out/ReturnsDesk_managed.zip
  pac solution export --name ReturnsDesk --path out/ReturnsDesk.zip
  pac solution unpack --zipfile out/ReturnsDesk.zip --folder src/solution
  ```
  Commit the unpacked unmanaged source; that's what makes reviews readable.
- `pac copilot pack` is local and needs no auth, so it's safe in CI [L]. But whether its zip is managed is ⚠ unverified, so open the first one and check. **Never import an unmanaged zip into TEST or PROD.**
- Tag each release commit.

### 9.2 CI identity and connection ownership
- **One Entra app registration per tier.** Add it as an **Application User** in the target environment with a least-privilege role that has import rights; avoid System Administrator in PROD.
- **Prefer federated credentials** (Microsoft's `copilot-alm-starter` does) [CAT]:
  ```powershell
  pac auth create --name ci-test --tenant <tid> --applicationId <appId> --githubFederated --environment <test>
  # or --azureDevOpsFederated / --managedIdentity ; secret fallback: --clientSecret $SECRET (CI secret store only)
  ```
- **User-delegated connections** such as Approvals, Outlook and the Copilot Studio connector (*Execute Agent* callbacks) can't be owned by an app. Give each environment a **dedicated non-personal service account** as owner. Record it in the identity map and create the connection interactively once.
  - Connections must be owned by, or shared with, the owner of the connection reference [L].
  - Never use a maker's personal connection in TEST or PROD.
  - If a connector can't run under the chosen identity, it's a **go-live blocker**.
- **msagent:** service-principal deployment is "on the roadmap" per Learn. The repo's hidden `AH_CLI_FEATURES=appusersupport` flags are not supported, so msagent releases are interactive (§9.4b).

### 9.3 Per-environment settings and import
1. Generate a settings file: `pac solution create-settings --solution-zip out/ReturnsDesk_managed.zip --settings-file deploy/test.settings.json`.
2. Fill in `EnvironmentVariables[].Value` and `ConnectionReferences[].ConnectionId` for each environment.
3. Commit it **without secrets**; secret values come from Key Vault-backed environment variables.
4. Check the solution: `pac solution check --path out/ReturnsDesk_managed.zip`.
5. Import:
   ```powershell
   pac solution import --path out/ReturnsDesk_managed.zip --settings-file deploy/test.settings.json --activate-plugins --publish-changes --async --max-async-wait-time 60
   # upgrades: add --stage-and-upgrade   (verify flags with pac solution import --help)
   ```
   Alternative: Power Platform pipelines (needs Managed Environments), supplying the values at deploy time [L].
6. **Post-import checklist, per environment:**
   - Connection owners set.
   - Role assignments done.
   - Dataverse search on.
   - Knowledge rebound.
   - User authentication reconfigured.
   - Environment-variable values correct.
   - Reference and seed data loaded (solutions don't carry data).
   - Test users ready.
   - Agent shared to the right security group.
   - Teams app approved.
   - Agent republished (needs the SKILL R5 yes naming agent and environment; PROD is run by a human).

### 9.4 Release route (decided at Gate 2 and recorded)
- **(a) Solution route.** For the standard harness, and for the Copilot harness if the spike passed: run §9.1–9.3 through the pipeline.
- **(b) msagent route.** Copilot harness. Unmanaged, preview, interactive sign-in only, and an **exception to build 0.1 / SKILL R4 (TEST only) that needs the user's written sign-off**. For PROD on this route, the agent prepares the commands and a human types them:
  ```powershell
  msagent deployment create --project <dir> --agent-name '<name>' --deployment-name test --deployment-type test --environment-id <test>
  msagent agent deploy --project <dir> --agent-name '<name>' --deployment-name test
  msagent agent deploy --project <dir> --agent-name '<name>' --deployment-name test --publish   # after approval
  ```
  Test and prod deploys don't check for cloud drift, need `--overwrite` to replace cloud edits, and reject managed agents [CAT].
- **(c) Manual Release Runbook.** If the spike was PARTIAL (§5.0), or the user skipped the spike with written risk acceptance.

For routes (b) and (c), the release record (§9.7) replaces the pipeline run as Stage 6 evidence: commands typed by the human (b) or completed runbook tasks with evidence (c).

### 9.5 Gates and sign-off
| Tier | Done when |
|---|---|
| **DEV** | Validation is clean, changes are pushed, DEV evaluations meet thresholds, and the Build Report is issued |
| **TEST** | The managed import is clean, the post-import checklist is complete, the evaluation gate passes (run by the service account), the non-maker Teams test passes, forced-failure runs have been seen, and actual credit use has been compared with the Blueprint's formula |
| **PROD** | All of the below |

PROD requires:
- A named **business owner and platform owner** sign the go-live checklist.
- A change-record ID.
- The ID of a **Dataverse backup taken before the import**.
- A rollback owner on call.
- Telemetry and cost alerts switched on.
- A smoke test that passes **without writing test data**.

**The agent never runs the PROD deploy step.** It prepares the artifacts, then waits for a human to trigger the protected pipeline stage.

### 9.6 Rollback = roll forward
**Never downgrade or uninstall a solution that owns tables holding data;** uninstalling deletes the data. In order:
1. **Fast disable:**
   - Turn the workflows off.
   - Unpublish or quarantine the agent: `pac copilot quarantine --bot-id <id>` [L]. The `--status` syntax is unclear, so check `--help`.
   - Remove its Teams availability.
2. **Roll forward:** rebuild the last good commit with a **higher** version and import it as an upgrade.
3. **Data:** restore from the backup taken before the import, or run a data-reversal runbook for changes the agent made.

Keep the last three managed zips, the backup IDs and the settings files used.

### 9.7 Release record (for each environment)
Commit, CLI versions, solution version, target environment and agent, settings file used, evaluation results, approver, change record and backup ID.

---

## 10. Operating
- **Ownership:** flows and connections in TEST and PROD belong to service accounts or principals, never to makers.
- **Monitoring:** telemetry export to App Insights (Preview; fallback: the Analytics tab plus run history); cost alerts and agent limits (B2.12).
- **Hotfixes:** managed agents can't be edited in the target. Fix in DEV, then release through §9 using the expedited approvers.
- **Re-run the evaluation gate** after any model change, schema change or connector update.
- **Branching:** trunk-based, with short feature branches. Each maker or feature gets its own DEV environment where possible. Release tags map to PROD imports.

---

**Sources** (2026-11-22):
- **Learn, Copilot Studio:** VS Code extension pages (overview, install-configure, clone-agent, edit-agent-components, synchronization); `agents-experience/copilot-studio-mcp`.
- **Learn, Power Platform:** `power-platform/developer/cli/reference/copilot`, `/auth`, `/solution`; `power-platform/developer/howto/use-mcp`; `power-platform/alm/conn-ref-env-variables-build-tools`.
- **Learn, msagent:** `microsoft-365/copilot-managed-runtime/developer/agents/cli/` (quickstart, deploy, source-control, evaluate, standalone-workflows, command-reference).
- **GitHub:** `microsoft/skills-for-copilot-studio`, `microsoft/copilot-studio-plugin`, `microsoft/AgentHosting.Cli`, `microsoft/copilot-alm-starter`.