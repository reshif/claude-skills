# Rehearsal report: bulk-export

**Question:** Will admins adopt bulk export without a support-ticket spike or a data-exposure incident?  
**Run:** `20261122-bulk-export`
**Recommended:** B

## Summary

Not as specified. Variant A fails outright for the ~30% of orgs above 50k users because the CSV is built inside the HTTP request (the INC-42 pattern). Variant B can meet the goal, but only with five changes: export links that are user-bound, expire in 24h and are freshly minted from a safe export list; streamed generation into one CSV; a visible status list; gated impersonation; and an audited way to share with external auditors. Shipped as written, B is likely to cause a data-exposure incident through forwardable non-expiring links. Caveat: seven critics on one model converged heavily on the same two issues; this is a rehearsal of foreseeable risks, not a forecast.

## Variants

| Variant | Verdict | Summary |
|---|---|---|
| A — synchronous download from the admin page | no-go | Times out above ~80k users and can never serve the 1.2M-user org (P1); retries repeat INC-42 (P2); recovering closed downloads would mean storing PII with no controls (R50). Gets worse under the what-if. |
| B — background job, email the admin a download link | go-with-changes | Right shape, unsafe as specified: non-expiring unbound links (P6), in-memory build dies at worker limits (P7), silent jobs drive SUP-77 tickets (P8), impersonation still open (P9). The 1.2M what-if is survivable only with streaming (P7). |

## Predictions

| ID | Variant | Kind | Severity | Likelihood | Statement | Evidence |
|---|---|---|---|---|---|---|
| P1 | A | unhappy_path | critical | 90% | Exports for orgs above ~80k users hit the 30s gateway timeout, and the 1.2M-user org can never complete an export | R1, R2, R13, R20, R21, R29, R31, R39, R41 |
| P2 | A | risk | high | 70% | Admins retry timed-out exports and multiply DB load across orgs, repeating INC-42 during audit season | R22, R30, R40 |
| P4 | A | defect | high | 60% | Accented names garble when the 62% of admins who use Excel open the CSV, so auditors reject the file | R4, R33 |
| P3 | A | risk | high | 55% | A support agent impersonating an admin downloads the full-org PII CSV with no ticket and no audit entry naming them | R5, R11, R12, T1, T2, T10 |
| P5 | A | risk | high | 30% | If A is served through the existing /dl token, a leaked URL exposes the org's PII indefinitely | R14, R32, T9 |
| P6 | B | risk | critical | 80% | The emailed link reuses non-expiring, unbound tokens, so a forwarded or leaked email gives anyone the org's names, emails and phones, violating the data-sharing policy | R6, R15, R26, R36, R46, T5, T6, T13, T14 |
| P7 | B | unhappy_path | critical | 70% | A 1.2M-row export built in memory is killed at the 2 GB / 15 min worker limit and the admin gets no file | R7, R17, R24, R34, R44, R45, R58 |
| P10 | B | risk | critical | 45% | The export list's re-download and resubmit-dedup features become a second delivery path that hands out the old unbound token | R49, R53 |
| P8 | B | unhappy_path | high | 75% | With no visible job status, admins whose export is slow or dead resubmit or open 'where is my export' tickets like SUP-77 | R8, R25, R35, R48, R57 |
| P12 | B | unhappy_path | high | 70% | Policy-compliant links (24h, user-bound) don't fit auditors who take days and have no account, so admins download and forward the CSV by email or chat | R19, R54, R55 |
| P9 | B | risk | high | 55% | An impersonating support agent queues a full-org export with no ticket, and user-bound links don't stop it because the session passes as the admin | R9, R16, R27, R37, R47, R52, R56, T7, T15 |
| P11 | B | defect | high | 50% | Partial and checkpoint files from killed jobs are left at rest with PII, and phone-number exports from failed jobs go unaudited | R18, R51 |
| P13 | B | defect | medium | 60% | The emailed CSV still garbles accented names in Excel unless it is written as UTF-8 with a BOM | R10, R38, R48 |

## Unhappy paths → acceptance

- **P1 (A)** Exports for orgs above ~80k users hit the 30s gateway timeout, and the 1.2M-user org can never complete an export  
  _Must hold:_ no export builds the file inside the HTTP request; orgs up to 1.2M users get a complete file
- **P7 (B)** A 1.2M-row export built in memory is killed at the 2 GB / 15 min worker limit and the admin gets no file  
  _Must hold:_ generation streams in batches to storage within worker limits and produces one complete CSV with row count and checksum shown to the admin
- **P8 (B)** With no visible job status, admins whose export is slow or dead resubmit or open 'where is my export' tickets like SUP-77  
  _Must hold:_ an in-app export list shows queued, running with percent, failed or killed-at-limit, and a failed job never blocks a retry
- **P12 (B)** Policy-compliant links (24h, user-bound) don't fit auditors who take days and have no account, so admins download and forward the CSV by email or chat  
  _Must hold:_ admins can mint a fresh link without rerunning the job and create a named, logged, expiring share to an auditor's email

## Risk heatmap

| Variant | low | medium | high | critical |
|---|---|---|---|---|
| A | 0 | 0 | 4 | 1 |
| B | 0 | 1 | 4 | 3 |

## Open questions for the human gate

- Compliance: is a named, logged share to an external auditor allowed under the data-sharing policy, and for how long can the file be retained (P12)?
- Ops: what per-org concurrency cap and read strategy (replica or batched reads) should exports use (R28)?
- No static scan was run (Semgrep and STRIDE GPT not installed); threat findings come from adversary review of the code only.

## Dismissed findings

- R50: Valid constraint on A, folded into A's no-go verdict rather than a separate prediction
- R59: Preference statement (favours B), reflected in the recommendation

## Evidence

- **R1** [review/A] _support-lead_: Any org over roughly 80k users times out at the 30s gateway because the whole CSV is built in memory in the request; 30% of orgs exceed 50k, so nearly a third of admins hit a failed download and open tickets. (← F1, F7, F11)
- **R2** [review/A] _support-lead_: The 1.2M-user org's admin clicks export, gets a timeout, and retries; as in INC-42 the retries double DB load and the export never completes. (← F1, F7, F11)
- **R4** [review/A] _support-lead_: 62% of admins open the CSV in Excel, so accented names garble and land on support as another SUP-81 style ticket unless the export handles encoding. (← F9, F12)
- **R5** [review/A] _support-lead_: Support agents impersonating an admin pass org_admin checks, so a full-org PII export without a ticket (as in INC-57) is possible, and a synchronous export has no audit entry for the phone numbers. (← F3, F10, F5)
- **R6** [review/B] _support-lead_: Download tokens never expire and are not bound to a user, so the emailed link for a full-org PII export can be forwarded or leaked and still work, which breaks the 24h, user-bound link policy; support will own the incident. (← F2, F4)
- **R7** [review/B] _support-lead_: The 1.2M-user org's job can hit the 15 min hard timeout or the 2 GB worker limit with no progress reporting, so the admin waits for an email that never arrives and files 'where is my export' tickets. (← F6, F11, F8)
- **R8** [review/B] _support-lead_: Admins cannot see a long-running job, so unless there is an in-app list of exports with status, the missing-email case becomes a flood of tickets like SUP-77, which already had 41 in Q2. (← F8, F6)
- **R9** [review/B] _support-lead_: A support agent impersonating an admin can queue the full-org export and have the link emailed or retrieved, repeating INC-57, and the phone-number export needs an audit log entry that nobody has specified for the job path. (← F3, F10, F5)
- **R10** [review/B] _support-lead_: The emailed CSV still garbles accented names for the 62% of admins who open it in Excel, so the Excel tickets land on support again. (← F9, F12)
- **R11** [review/A] _security-officer_: A support agent impersonating an admin passes org_admin checks and can pull the full 1.2M-user PII CSV instantly with no ticket, a direct repeat of INC-57. (← F3, F10)
- **R12** [review/A] _security-officer_: Synchronous export of phone numbers has no specified audit log entry, so the download violates policy and cannot be reconstructed after an incident. (← F5)
- **R13** [review/A] _security-officer_: When the largest org exports, the whole CSV is built in memory inside the request, exceeds the gateway timeout, and admins retry, causing duplicate full-PII builds and doubled DB load. (← F1, F7, F11)
- **R14** [review/A] _security-officer_: If A reuses the existing download-token mechanism, the resulting link never expires and is not bound to the user, so a leaked URL exposes all users' PII indefinitely; nobody has specified whether A uses tokens. (← F2, F4)
- **R15** [review/B] _security-officer_: The emailed download link would use existing tokens that never expire and are not bound to a user, so a forwarded or leaked email gives anyone permanent access to the entire org's PII, violating the 24h and user-binding policy. (← F2, F4)
- **R16** [review/B] _security-officer_: An agent impersonating an admin can trigger the job and the link goes to the admin's inbox or can be redirected, leaving no ticket linkage, so INC-57 can recur with a durable artifact and no accountable requester. (← F3, F10, F5)
- **R17** [review/B] _security-officer_: The 1.2M-user export may hit the 15 min hard timeout or 2 GB worker limit with no progress reporting, failing silently, and admins resubmit, producing multiple PII files with live links. (← F6, F11, F2)
- **R18** [review/B] _security-officer_: Unspecified whether the generated file at rest is deleted when the link expires or on failed jobs, and whether the audit entry is written at request time, generation time or download time, given phone numbers require logging. (← F5, F4)
- **R19** [review/B] _security-officer_: If the emailed link is unbound, the lost-tab pattern (admins can't find reports) will push admins to re-request or share links by email and chat, spreading PII copies beyond the audit trail. (← F8, F2)
- **R20** [review/A] _sre_: The 1.2M-user org clicks export and the service builds the whole CSV in memory inside the HTTP request, so the web worker runs out of memory or hits the gateway timeout and takes other requests down with it. (← F1, F11)
- **R21** [review/A] _sre_: Orgs above 50k users (30% of admin orgs) time out at the 30s gateway, the admin retries, and DB load doubles again, which repeats INC-42 across many orgs at once. (← F7, F11)
- **R22** [review/A] _sre_: A full-table user scan per click has no rate limit or concurrency cap, so a few admins exporting at once during an audit season spike DB load. (← F1, F7)
- **R24** [review/B] _sre_: The 1.2M-user export, if still built in memory, can exceed the 2 GB worker memory or the 15 min hard timeout and be killed mid-run, and with no progress reporting nobody knows it died. (← F6, F1, F11)
- **R25** [review/B] _sre_: With no progress reporting, a killed or slow job looks like silence, so admins re-submit or file tickets, and the duplicate jobs add DB load and queue contention on the shared workers. (← F6, F8, F7)
- **R26** [review/B] _sre_: The emailed download link uses tokens that never expire and are not bound to a user, so a forwarded or leaked email exposes 1.2M users' phone numbers indefinitely, which breaks the 24h, user-bound policy. (← F2, F4)
- **R27** [review/B] _sre_: A support agent impersonating an admin passes org_admin checks and can queue a bulk export with no ticket, as in INC-57, and nothing guarantees the required audit log entry for phone data. (← F3, F10, F5)
- **R29** [review/A] _big-org-admin_: I click export on my 400k-user org and the whole CSV is built in memory inside the HTTP request, so it hits the gateway timeout and I never get the complete file the auditors need. (← F1, F7, F11)
- **R30** [review/A] _big-org-admin_: With no feedback during a long wait I retry or close the tab, which doubles DB load as in INC-42 and leaves me with no way to find the report again. (← F7, F8)
- **R31** [review/A] _big-org-admin_: At 1.2M users the in-request build exhausts memory and times out for every attempt, so the largest org can never export at all. (← F1, F11, F7)
- **R32** [review/A] _big-org-admin_: Download tokens never expire and are not bound to a user, so a link containing every user's phone and email that leaks or is forwarded exposes my whole org's personal data and breaks the 24h user-bound policy. (← F2, F4)
- **R33** [review/A] _big-org-admin_: Accented names garble when the auditors open the CSV in Excel, so the file is rejected as broken. (← F9, F12)
- **R34** [review/B] _big-org-admin_: For my 1.2M-user org the job hits the 15 min hard timeout or the 2 GB worker memory limit, fails midway, and I get no complete file for the auditors. (← F6, F11, F1)
- **R35** [review/B] _big-org-admin_: The job queue has no progress reporting, so after I submit I wait with no status and cannot tell whether it is running, failed or lost, and I file a ticket or resubmit. (← F6, F8)
- **R36** [review/B] _big-org-admin_: The emailed link uses non-expiring tokens not bound to a user, so a forwarded or leaked email lets anyone download my org's personal data indefinitely, violating the 24h user-bound policy. (← F2, F4)
- **R37** [review/B] _big-org-admin_: A support agent impersonating me passes org_admin checks and can trigger an export that is emailed to my address or attributed to me, with no ticket and a misleading audit trail, as in INC-57. (← F3, F10, F5)
- **R38** [review/B] _big-org-admin_: The emailed CSV still garbles accented names in Excel for most of us, and the auditors get a file with broken names. (← F9, F12)
- **R39** [review/A] _export-service_: The 1.2M-user org exports synchronously: the service builds the full CSV in memory inside the HTTP request, so a single request holds the entire dataset (hundreds of MB) and runs far past the 30s gateway timeout. (← F1, F7, F11)
- **R40** [review/A] _export-service_: Gateway times out, the admin sees an error and retries, and each retry rebuilds the full CSV in memory and re-queries the DB, so concurrent retries multiply memory and DB load as in INC-42. (← F7, F1)
- **R41** [review/A] _export-service_: At 80k users a sync report already breached the gateway timeout, so the 30% of orgs above 50k users hit the failure well below the 1.2M extreme. (← F7, F11)
- **R44** [review/B] _export-service_: If the job builds the CSV in memory as the current service does, 1.2M rows plus string and encoding overhead can exceed the 2 GB worker limit and the OOM-killed worker loses the export with no result; the build must stream to storage. (← F1, F6, F11)
- **R45** [review/B] _export-service_: The 1.2M-user export can exceed the 15-minute hard timeout, and with no progress reporting and no checkpointing the job is killed with nothing to resume from and the admin is never told why. (← F6, F11)
- **R46** [review/B] _export-service_: Emailed download links use the existing token scheme, which never expires and is not bound to a user, so a forwarded or leaked email exposes 1.2M users' phone numbers and violates the 24h, user-bound link policy. (← F2, F4)
- **R47** [review/B] _export-service_: A support agent impersonating an admin passes the org_admin check and can trigger the job, and the link is then emailed to the impersonated admin or the agent can retrieve it, repeating INC-57 with no audit entry unless the job records the real actor. (← F3, F10, F5)
- **R48** [review/B] _export-service_: With no progress reporting and a job that may fail or be killed silently, admins who never get the email file tickets, and Excel users (62%) see garbled accented names unless the CSV is written with a UTF-8 BOM. (← F6, F8, F9, F12)
- **R49** [review/B] _security-officer_: The in-app exports list that R8/R35 want becomes a second, unreviewed delivery path if it re-serves the file or mints links by wrapping the existing unbound token; it must issue only user-bound 24h links with a session check on every click. (← R8, R35, R6, T6, F2, F4, F8)
- **R51** [review/B] _security-officer_: Checkpointed or partial export files left after OOM/timeout kills hold PII at rest; they need the same 24h expiry and deletion, failure notices must carry no links, and the audit entry must be written at request time, not on success. (← R7, R45, R48, R18, F5, F6, F4)
- **R52** [review/B] _security-officer_: Binding the link to the admin does not stop an impersonating agent, whose session passes as that admin, so closing INC-57 also needs a ticket reference and reason on the request, the real actor in the audit log, and delivery only to the verified address. (← R47, R16, T15, T7, F3, F4, F10)
- **R53** [review/B] _security-officer_: Deduplicating resubmits by handing back an existing job's link could give a previously issued link to a different session; dedup must reuse the job but mint a new user-bound link, rate-limited so the inbox is not flooded with PII links. (← R28, R25, T16, F2, F4, F3)
- **R54** [review/B] _big-org-admin_: A 24h link expiry clashes with auditors who take days; unless I can regenerate a fresh link from the export list without rerunning the 1.2M-row job, I will re-request exports and create more load and PII copies. (← R6, R15, R19, T5, T16, F4)
- **R55** [review/B] _big-org-admin_: A user-bound link gives my external auditor a 403, so I will download and forward the CSV by email or chat, which is worse for PII; the design needs a named, audited share to an auditor email. (← R15, R19, T6, T14, F4)
- **R56** [review/B] _big-org-admin_: Impersonation controls must gate only impersonated sessions, not add an approval step to my own exports, and the export list should show me when an impersonated session requested one. (← R37, R47, T7, T15, F5)
- **R57** [review/B] _big-org-admin_: A per-org concurrency cap must not block my retry when the first job died unnoticed; the list must show queued, running %, failed or killed-at-limit, failed jobs must not count against the cap, and a retry must replace the partial file. (← R28, R17, R24, R25, F6)
- **R58** [review/B] _big-org-admin_: Splitting a 1.2M-row job into several files to fit worker limits breaks my need for one complete file; generation must assemble a single CSV and show a row count and checksum so auditors can verify completeness. (← R45, R44, R34, F6, F11)
- **T1** [threat/A] _insider_: (E) While impersonating an org admin I inherit org_admin, so I can pull the full user CSV including phones with no ticket, exactly as in INC-57. (← F3, F10, file:app/auth/roles.py:3)
- **T2** [threat/A] _insider_: (R) Impersonated exports look like the admin's own action, and with no audit entry required until F5 is implemented, nothing ties the download to me. (← F5, F3, F10)
- **T5** [threat/B] _insider_: (I) Download links never expire and are not user-bound, so a link I copy while impersonating works for me or anyone later, outside the admin's session, with no check on who opens it. (← F2, F4, file:app/export/links.py:6)
- **T6** [threat/B] _insider_: (S) The token is the only credential and resolve() never checks the caller, so holding a forwarded or leaked emailed link is enough to act as the admin. (← F2, file:app/export/links.py:9)
- **T7** [threat/B] _insider_: (E) Impersonating an admin lets me trigger the job and then fetch it later from any session, and the role check passes with no ticket. (← F3, F10, file:app/auth/roles.py:3)
- **T9** [threat/A] _forwarder_: (I) If the download is served via a /dl/<token> link, anyone who gets a forwarded or leaked URL or a proxy/browser-history log entry can fetch the full user list, because resolve() does no user, org or session check. (← F2, file:app/export/links.py:6, file:app/export/links.py:10)
- **T10** [threat/A] _forwarder_: (E) An outsider who persuades a support agent to impersonate an admin gets the org_admin export without the org's knowledge, and require_role waves them through with no ticket or reason check. (← F3, F10, file:app/auth/roles.py:3)
- **T13** [threat/B] _forwarder_: (I) The emailed download link never expires and is not bound to the requesting user, so a forwarded email gives the recipient the full CSV of names, emails and phones indefinitely, and it breaks the 24h and user-bound policy. (← F2, F4, file:app/export/links.py:6)
- **T14** [threat/B] _forwarder_: (S) Because resolve() accepts a bare token with no identity check, whoever holds the forwarded email can act as the admin who requested the export, and the audit trail cannot tell the two apart. (← F2, F5, file:app/export/links.py:10)
- **T15** [threat/B] _forwarder_: (R) Impersonated-admin jobs emailed to an admin address can send exports to a mailbox the attacker controls with no ticket, and the link works from any recipient, so who actually downloaded cannot be proven. (← F3, F10, F5, file:app/auth/roles.py:3)
