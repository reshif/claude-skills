# Acceptance criteria — bulk-export (variant B)

From rehearsal `20261122-bulk-export`. Each item traces to a prediction and its evidence.

- [ ] **P1** (critical, 60%) the system prevents or handles: A forwarded export email exposes the org's user list  
  _Why:_ A forwarded export email exposes the org's user list — evidence T1
- [ ] **P2** (medium, 75%) an in-app export history shows status and a re-download link  
  _Why:_ Admin closes the tab and cannot find the export later — evidence R2
- [ ] **gate change** signed links expire after 24h
