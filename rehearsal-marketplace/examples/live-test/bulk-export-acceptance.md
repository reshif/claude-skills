# Acceptance criteria — bulk-export (variant B)

From rehearsal `20261122-bulk-export`. Each item traces to a prediction and its evidence.

- [ ] **P6** (critical, 80%) export links expire within 24h, are bound to the requesting user and are checked against the session on every download  
  _Why:_ The emailed link reuses non-expiring, unbound tokens, so a forwarded or leaked email gives anyone the org's names, emails and phones, violating the data-sharing policy — evidence R6, R15, R26, R36, R46, T5, T6, T13, T14
- [ ] **P7** (critical, 70%) generation streams in batches to storage within worker limits and produces one complete CSV with row count and checksum shown to the admin  
  _Why:_ A 1.2M-row export built in memory is killed at the 2 GB / 15 min worker limit and the admin gets no file — evidence R7, R17, R24, R34, R44, R45, R58
- [ ] **P8** (high, 75%) an in-app export list shows queued, running with percent, failed or killed-at-limit, and a failed job never blocks a retry  
  _Why:_ With no visible job status, admins whose export is slow or dead resubmit or open 'where is my export' tickets like SUP-77 — evidence R8, R25, R35, R48, R57
- [ ] **P9** (high, 55%) impersonated sessions must give a ticket reference and reason, the audit log records the real actor at request time, and the admin sees impersonated requests in the export list  
  _Why:_ An impersonating support agent queues a full-org export with no ticket, and user-bound links don't stop it because the session passes as the admin — evidence R9, R16, R27, R37, R47, R52, R56, T7, T15
- [ ] **P10** (critical, 45%) every download from the list or a deduplicated request mints a new user-bound 24h link, rate-limited per user  
  _Why:_ The export list's re-download and resubmit-dedup features become a second delivery path that hands out the old unbound token — evidence R49, R53
- [ ] **P11** (high, 50%) partial files are deleted on failure under the same 24h retention, failure emails carry no link, and the audit entry is written at request time  
  _Why:_ Partial and checkpoint files from killed jobs are left at rest with PII, and phone-number exports from failed jobs go unaudited — evidence R18, R51
- [ ] **P12** (high, 70%) admins can mint a fresh link without rerunning the job and create a named, logged, expiring share to an auditor's email  
  _Why:_ Policy-compliant links (24h, user-bound) don't fit auditors who take days and have no account, so admins download and forward the CSV by email or chat — evidence R19, R54, R55
- [ ] **P13** (medium, 60%) the system prevents or handles: The emailed CSV still garbles accented names in Excel unless it is written as UTF-8 with a BOM  
  _Why:_ The emailed CSV still garbles accented names in Excel unless it is written as UTF-8 with a BOM — evidence R10, R38, R48
- [ ] **gate change** links user-bound, 24h, minted fresh from the export list
- [ ] **gate change** named, logged auditor share pending compliance answer
