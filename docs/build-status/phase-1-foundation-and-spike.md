# Build Status — Phase 1 & Phase 1.5

### Phase 1 — Foundation
**Status: ✅ Complete.** **Phase 1 review (2026-09-05, pre-Phase-2):** re-checked this phase
against Security, Diagnostics & Logging, and Backup & Restore above (Phase 1 predates the
chunking convention, so this review was done as a whole-phase pass rather than a per-chunk
one). Found and fixed: CORS was `allow_origins=["*"]` with no auth, tightened to
`ALLOWED_ORIGINS` (see [Security §4](../security.md#security)); uvicorn's default logging config was
silently dropping every access-log line from `logs/app.log` and the diagnostics ring buffer
(`log_config=None` fix, plus removing a since-counterproductive `WARNING` filter on
`uvicorn.access`); `requirements.txt` was floor-pinned (`>=`) rather than exact, now pinned;
`diagnostics.py` had real logic with no test coverage, now has smoke tests. Also actually ran
`restore.bat latest --yes` for the first time (list → dry run → real restore), closing out
the "tested once" deliverable below rather than leaving it assumed. See commit
`e5b70a0` for detail. No open gaps carried forward — Phase 2 can start clean.
- Project scaffold: FastAPI app, directory structure, requirements.txt
- SQLite database setup with SQLAlchemy, all tables created on startup, including:
  - the recipe-history and "suggest something" prep columns on `recipes`
    (`times_made`, `last_made_at`, `rating`, `cuisine`, `protein`)
  - soft-delete (`recipes.archived_at`)
  - audit columns (`created_at`/`updated_at`) on every mutable table
  - `stores`, `store_sections`, `product_sections` (schema only — setup/rendering UI is Phase 6)
- Logging setup: file handler + in-memory ring buffer for diagnostics UI
- Diagnostics page skeleton (component status stubs, log tail viewer)
- `.env` file for configuration (PORT, ANTHROPIC_API_KEY, ANYLIST_EMAIL, ANYLIST_PASSWORD,
  LOG_LEVEL)
- `start.bat` and `stop.bat` scripts
- Automated backup: `scripts/backup.py` + `backup.bat`, weekly via Task Scheduler, plus
  `scripts/restore.py` + `restore.bat`, restore path actually tested once (see
  [Backup & Restore](../deployment-and-operations.md#backup--restore))
- Security `[Phase 1 fix]` items applied — see [Security](../security.md#security) §1 and §3
- Static IP setup instructions for Windows 10 (as a `SETUP.md` file in project root)
- Health check endpoint: `GET /api/v1/health` returns DB status, config loaded status

**Deliverable:** Server starts, diagnostics page loads, log tail shows startup messages, backup
and restore have each been run successfully at least once.

### Phase 1.5 — AnyList derisking spike
**Status: ✅ Complete.** Finding: Python-native confirmed over the Node microservice fallback
(see [Tech Stack > AnyList integration](../project-overview.md#anylist-integration--phase-5-decision)) — no revisit
needed at Phase 5 kickoff, just implementation.
Slotted in immediately after Phase 1 because AnyList has been flagged as the highest-risk,
lowest-confidence part of the stack — it must not stay unexplored until Phase 5.
- Throwaway spike only (scratch script / notebook, not wired into the app)
- Authenticate, fetch the target list + items, add and remove a test item
- Determine Python-native vs Node-microservice approach from real results
- Write up the finding (what worked, auth/protobuf surprises, effort estimate)

**Deliverable:** A working proof-of-concept AnyList call and a short written finding that
settles the Phase 5 "native vs Node" decision. Full connector and checklist UI stay in
Phase 5. Flag the outcome before continuing to Phase 2.

