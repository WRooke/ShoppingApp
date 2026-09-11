# Comprehensive Codebase Review Prompt

Perform the most thorough review of this codebase you are capable of. This is not a quick pass — assume issues exist that a normal review would miss, and your job is to surface them. Read every file that contains logic, configuration, or tests; do not sample or skim. Where a file is too large to hold in full context at once, read it in sections rather than skipping parts.

Do not fix anything during this pass. This is a review-and-report exercise only. At the end, produce a written report (format specified below) plus a proposed fix plan — do not start making changes.

## Ground rules

- No issue is too minor to report. If you notice it and have to ask yourself "is this worth mentioning?", the answer is yes — include it and let severity ranking do the filtering, not your judgment about what's worth surfacing.
- Every finding needs a concrete location (file + line/function/section) and a concrete reason it matters — no vague "this could be cleaner" without specifics.
- Distinguish between "this is definitely wrong," "this is a risk," and "this is a style preference" — and label which is which.
- Don't pattern-match to generic best-practice complaints that don't actually apply to this codebase's context, scale, or stated goals. If there's a project spec, README, or design doc, read it first and treat any deviation from it as a first-class finding, not an afterthought.
- Where you're not sure whether something is a bug or intentional, say so explicitly rather than guessing silently in either direction.
- Trace actual runtime/data flow, not just what the code appears to do in isolation — many real bugs only show up when you follow a request or a piece of data through multiple layers.

## Review categories

### 1. Correctness & logic bugs
- Off-by-one errors, incorrect boundary conditions, wrong operator precedence, inverted conditionals.
- Incorrect handling of null/None/undefined/empty values.
- Race conditions, TOCTOU (time-of-check-to-time-of-use) issues, unsafe shared state, missing locks/mutexes where concurrency exists.
- Integer overflow/underflow, floating-point precision issues, unsafe type coercion.
- Incorrect assumptions about ordering, uniqueness, or idempotency.
- Logic that works for the happy path but silently produces wrong results (not crashes) on edge cases — these are the most dangerous and easiest to miss.
- Copy-paste errors: a block duplicated with one variable name not updated to match.

### 2. Error handling & failure modes
- Swallowed exceptions (empty catch/except blocks, catching too broad an exception type).
- Errors that are logged but not surfaced, or surfaced but not logged.
- Silent failures — anywhere a failure results in a default/fallback value instead of a visible error, when that's not the explicit intent.
- Retry logic without backoff, without a cap, or that can retry non-idempotent operations unsafely.
- Resource leaks on the error path (file handles, DB connections, sockets, locks not released if an exception occurs mid-function).
- Inconsistent error handling patterns across the codebase (some modules raise, others return error codes, others return None).
- Missing timeout handling on any network call, DB query, or external API call.
- Whether error messages are actionable (tell you what happened, where, and why) or generic ("something went wrong").

### 3. Warnings, linter output & static analysis
- Run or simulate the project's linter/type-checker/compiler and report every warning verbatim, no matter how trivial — unused variables/imports, shadowed names, implicit type conversions, deprecated API usage, unreachable code.
- Any suppressed warnings (`# noqa`, `// eslint-disable`, `@ts-ignore`, `#[allow(...)]`, etc.) — flag each one and assess whether the suppression is still justified or has become a hiding place for real problems.
- Compiler/interpreter version-specific deprecation notices.
- Inconsistent or missing type annotations where the language/tooling supports them.

### 4. Testing
- Coverage gaps: which functions, branches, and error paths have zero test coverage — especially failure paths, not just happy paths.
- Tests that assert too little (e.g., only check "no exception thrown" rather than checking actual output correctness).
- Tests that are tautological or test the mock instead of the real behavior.
- Flaky tests: anything with timing dependencies, unseeded randomness, or reliance on external state/network.
- Missing edge case tests: empty inputs, maximum-size inputs, unicode/encoding edge cases, concurrent access, malformed input.
- Test isolation problems: tests that depend on execution order or leak state between runs.
- Integration/end-to-end coverage vs. unit coverage — is there a meaningful test at the boundary between major components, or only within them?
- Are tests actually run in CI, and would a broken test actually block a merge/deploy?

### 5. Architecture & component connections
- Map out how the major components/services/modules actually communicate (not how documentation says they do) — flag any mismatch.
- Tight coupling: places where a change in one module requires an unrelated change elsewhere, or where two components share implicit assumptions not enforced by an interface/contract.
- Unclear ownership: pieces of state or logic that multiple components can modify with no single source of truth.
- Layering violations: lower-level modules reaching into higher-level ones, business logic embedded in presentation/UI layers, or database queries scattered outside a data-access layer.
- Circular dependencies between modules/packages.
- Inconsistent patterns for the same kind of problem solved differently in different parts of the codebase (e.g., three different ways of making an HTTP call).
- Single points of failure — is there a component that, if it fails, silently degrades the whole system versus failing loudly and locally?

### 6. Security
- Injection risks: SQL, command, template, and log injection — anywhere user input reaches a query, shell command, or template without sanitization.
- Authentication/authorization: missing checks, checks that can be bypassed, privilege escalation paths, insecure session handling.
- Secrets management: hardcoded credentials/API keys/tokens, secrets committed to version control, secrets logged in plaintext.
- Insecure defaults: permissive CORS, overly broad file permissions, services bound to all interfaces when they should be local-only.
- Dependency vulnerabilities: outdated packages with known CVEs, unpinned versions that could pull in a compromised release.
- Insecure deserialization, unsafe use of `eval`/`exec`/dynamic code execution.
- Insufficient input validation on any boundary that accepts external data (API endpoints, file uploads, webhooks, CLI args, environment variables).
- Sensitive data exposure: PII or credentials in logs, error messages, or client-side code.

### 7. Performance & inefficiency
- N+1 query patterns, redundant network/database round-trips that could be batched.
- Unbounded loops, unbounded memory growth (unbounded caches, lists that grow without eviction).
- Unnecessary re-computation of values that could be cached or memoized, and conversely, caching that's gone stale or is never invalidated correctly.
- Blocking calls in code paths that should be async/non-blocking, or the reverse (unnecessary async overhead for trivial work).
- Inefficient data structures for the access pattern actually used (e.g., linear search where a hash lookup would do).
- Large payloads being transferred, parsed, or held in memory when a subset would do.

### 8. Code bloat, duplication & dead code
- Duplicated logic that should be extracted into a shared function/module — and conversely, over-abstracted code (an interface, base class, or config layer built for a flexibility need that doesn't exist).
- Dead code: unreachable branches, unused functions/classes/exports, commented-out code left in place, feature flags for features that shipped or were abandoned long ago.
- Unused dependencies still listed in the manifest.
- Overly long functions/files/classes that are doing too many unrelated things and should be split.
- Configuration or constants duplicated in multiple places instead of defined once.

### 9. Data & schema
- Schema design issues: missing indexes on frequently-queried columns, missing foreign key constraints, nullable columns that shouldn't be nullable, lack of any migration strategy.
- Data integrity: is invalid data actually rejected at the boundary, or can bad data get persisted?
- Migration safety: are migrations reversible, and would running one against production-sized data be safe (locking, downtime)?
- Backup/restore: is there one, has it actually been tested, does it cover everything needed to recover?

### 10. Documentation & maintainability
- Is there a README/spec, and does the code actually match what it describes? Flag every divergence.
- Comments that are wrong, stale, or explain *what* the code does instead of *why* — versus places genuinely non-obvious logic has zero explanation.
- Public functions/APIs without docstrings or type signatures explaining expected inputs/outputs.
- Naming: misleading variable/function names, inconsistent naming conventions across the codebase.
- Onboarding friction: could a new contributor understand the setup, build, and test process from what's written down?

### 11. Dependency & environment health
- Outdated major-version dependencies, deprecated packages, or packages with better-maintained alternatives now available.
- Version pinning strategy — are versions pinned appropriately (not so loose that builds aren't reproducible, not so strict that security patches are blocked)?
- Environment/config drift: differences between how dev, test, and production are configured that could cause "works on my machine" failures.
- Build/CI pipeline: are all necessary checks (lint, type-check, test, security scan) actually wired into CI, and would a failure in each actually block a merge?

### 12. Workflow & operational overhead
- Anything that requires manual intervention, babysitting, or tribal knowledge to operate day-to-day.
- Diagnostics: when something fails in production/at runtime, is it immediately obvious *when*, *where*, *why*, and *how* it failed — or would debugging require guesswork?
- Logging quality: is logging structured, appropriately leveled (debug/info/warn/error used correctly), and free of noise that would drown out real signals?

## Output format

Structure the final report as follows:

1. **Executive summary** — the 5–10 most serious findings across the entire review, one line each, ordered by severity.
2. **Findings by category** — using the numbered categories above as headers. For each finding include:
   - **Location**: file, function/class, and line number(s)
   - **Severity**: Critical / High / Medium / Low / Nitpick
   - **Issue**: what's wrong, stated precisely
   - **Why it matters**: concrete consequence if left unaddressed
3. **Cross-cutting observations** — patterns that show up repeatedly across multiple files/categories (e.g., "error handling is inconsistent project-wide," "no module has test coverage for its failure paths") rather than being one-off findings.
4. **Proposed fix plan** — an ordered, actionable plan that groups findings into logical batches, for example:
   - Quick wins (low-risk, high-value, can be done immediately)
   - Requires design/spec discussion before touching
   - Requires a schema/data migration
   - Requires broader refactoring or architectural change
   
   For each batch, note dependencies between fixes (what must happen before what) and flag anything especially risky to change without additional test coverage first.

Take as much space as the findings genuinely warrant — do not compress or omit findings for the sake of brevity. Thoroughness matters more than concision for this task.
