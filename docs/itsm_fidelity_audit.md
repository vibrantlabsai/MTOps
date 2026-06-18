# ITSM Port — Tool Logic Fidelity Audit

**Question being answered:** when the ITSM tools were ported from the original ServiceNow MCP
server into in-memory Python functions, was each tool's *business logic* preserved — or were the
ports reduced to "take input → return a pydantic object"?

**Short answer:** the tool *inventory* and *happy-path* behaviour are faithful, but a consistent
set of **input-validation and write-semantics** behaviours were simplified away. These are real,
reproducible divergences from the reference server. They are concentrated in error/edge paths, not
the success path — which is why earlier testing (happy-path only) did not surface them.

---

## 1. Method & confidence

The reference (ground truth) is the original MCP server's own code, extracted from the published
Docker image (`enterpriseops-gym-mcp-itsm`) as compiled `.pyc`. Its real logic lives in
`apis/<category>/router.py` (endpoint wrappers) and `database/managers/<category>_manager.py`
(domain logic); the `tools/*.py` files are only MCP tool *declarations* (name/description/schema).

Two independent passes were run for every tool category:

1. **White-box** — the decompiled reference logic vs the ported Python, function by function.
2. **Black-box** — every suspected divergence was reproduced **live** against the running
   reference server (seeded with the canonical DB) and compared to what the port does.

Across the categories audited this way, **85 claimed divergences were confirmed live and 86 were
refuted** (≈ half thrown out). The refuted half matters as much as the confirmed half: it means
several "obvious" concerns are *not* real, and the confirmed list below is what actually needs
attention.

> Coverage note: 18 of 19 categories were audited end-to-end. `incidents` was verified manually
> (the automated agent failed on an API error but its findings were reproduced by hand);
> `locations` was not separately audited and should be filled in.

---

## 2. How the port was built, and what was tested

- The tools were hand-ported from the decompiled reference.
- The original port shipped a **Docker-gated differential conformance harness** (`itsm_oracle.py`
  + per-category `test_itsm_*_conformance.py`) that ran identical scenarios against both the port
  and the live server and asserted identical resulting DB state. This was the fidelity gate.
- **Blind spot:** those scenarios were **happy-path only** — valid enums, valid foreign keys, no
  no-op updates, no empty fields, a single organization. Every divergence below lives in an
  error/edge path that the scenarios never exercised.
- That harness was later **removed**. Restoring and *extending* it (with negative/edge cases) is
  the single highest-leverage fix, because it converts every item below into an automatically
  enforced invariant.

---

## 3. A claim that did NOT hold up

A representative worry was that "an incident cannot move `new → resolved`" and that the port was
missing this rule. **Live test:** an incident with status `new` was updated to `resolved` and it
**succeeded with no error**. The reference server has **no status state machine anywhere** — its
update path is itself a plain field-assignment loop. There is no transition rule to preserve. This
is a useful calibration: structural intuition pointed at a real *class* of problem (validation),
but the specific example was not one of them.

---

## 4. Confirmed divergences, by theme

Ordered by impact. "Impact" = whether, for a plausible agent or gold action, the port would
produce a **different DB state** or a **different success/error outcome** than the reference.

### 4.1 Enum validation (27 confirmed, 0 refuted — fully systemic) — HIGH
The reference enforces every enum-typed field (status, priority, impact, urgency, category,
channel, risk, role, group type, notification type/status, knowledge state, CI status, service
status/classification, SLA metric, `used_as`, …) as a **case-sensitive** pydantic enum at the
request boundary. Invalid *or wrong-case* values are rejected with no write.

The port types these fields as free-form `str` and writes them verbatim. So `status='active'`,
`priority='urgent'`, `impact='High'` are all **accepted** by the port and **rejected** by the
reference.

- Live: `create_change(priority='urgent')` → enum error, no row. `register_configuration_item(status='active')` → enum error, no write. `add_new_user(role='superuser')` → enum error, no user.
- Note: the reference **rejects** non-canonical case; it does **not** silently lowercase. (One
  exception observed: `incident_sla.stage` accepts `'Breached'` and stores `'breached'`. Treat the
  canonical sets — including the casing — as authoritative per field.)

### 4.2 Input validation / integrity (22 confirmed) — HIGH/MEDIUM
The reference enforces invariants the port omits:
- **Duplicate detection:** knowledge article (title+owner) → `DUPLICATE_ARTICLE`; group email →
  `DUPLICATE_GROUP_EMAIL`; change number → `DUPLICATE_NUMBER`; incident-SLA (incident, sla_def)
  pair on update. Port inserts/updates the duplicate.
- **Numeric bounds:** CI `cost` must be ≥ 0 (create/update/filter). Port has no guard.
- **Empty-value handling:** the reference coerces empty-string FKs to `NULL` (e.g.
  `create_change(service='')` creates a row with `service=NULL`); the port instead raises
  `INVALID_REFERENCE` (a case where the **port is stricter** than the reference). It also
  normalizes empty/whitespace text to `NULL` (`update_service(description='   ')` → `NULL`); the
  port stores the literal string.
- **Date-range validation:** an inverted `created_after`/`created_before` range errors; the port
  silently returns an empty list.

### 4.3 Destructive-delete guards (HIGH)
`delete_incident_slas()` and `remove_affected_ci_from_incident()` called with **no filter** are
**rejected** by the reference (the table is left intact). The port treats "no filter" as "match
everything" and **wipes the entire table**. This is the most dangerous single divergence.

### 4.4 Required-field guards (7 confirmed) — MEDIUM
The reference rejects empty `title`, empty `start_time`, and updates that supply only an identifier
("at least one field must be provided"). The port accepts these and writes a row / bumps
`updated_on`.

### 4.5 Idempotency / "no changes detected" (5 confirmed) — MEDIUM/HIGH
A no-op update (every provided field already equal to stored) is rejected with `NO_CHANGES_DETECTED`
and performs no write. The port always assigns and bumps `updated_on`, producing a different DB
state. (Caveat: on enum fields this only triggers after enum validation, so 4.5 depends on 4.1.)

### 4.6 Filter semantics (7 confirmed) — MEDIUM
- Free-text filters use **case-insensitive partial match** (`LIKE %term%`): `name='level 1'`
  matches `'Level 1 Support Team'`; `email='benjamin'` matches `benjamin.chen@…`. The port uses
  exact, case-sensitive equality.
- Date filters are **parsed as datetimes** (handles `Z`, space-separated, US formats); the port
  does lexicographic string comparison, which diverges on non-canonical inputs.

### 4.7 Cross-entity & cross-org reference rules (3 confirmed) — HIGH (narrow)
- `incident_template` create/update: `service_offering` must belong to the named `service`;
  mismatch rejected. Port only checks existence.
- `add_new_user`: `location_id` must belong to the caller's org (`CROSS_ORGANIZATION_ACCESS`).
  Port only checks existence. (This is one of the *few* genuine org checks — see §5.)
- `notification_analysis` aggregates validate that referenced incident ids exist (the port
  returns 0 / silently ignores).

### 4.8 Result ordering (2 confirmed) — MEDIUM
List endpoints return results ordered `created_at`/`created_on` **DESC**; the port returns
insertion order.

### 4.9 Error-message wording (LOW)
Many messages differ (`"Incident 'X' not found"` vs `"Incident with ID 'X' not found"`), as does
validation precedence (e.g. "at least one field" checked before not-found). Only matters if a task
asserts on the exact message; otherwise cosmetic.

---

## 5. What is faithful, and what was refuted

Reporting this so effort is not spent on non-problems:

- **Tool inventory:** ~93 tools, matching the reference.
- **Create defaults & derivations:** e.g. `create_incident` defaults (`new`/`planning`/`low`/
  `inquiry-help`) and the fact that `contact_type` is *not* derived on create — both match exactly.
- **Org-scoping is NOT a real divergence (2 confirmed / 53 refuted).** Tested across reads, lists,
  updates, and number-lookups as a different-org user, the reference returned and wrote other
  orgs' rows just like the port. This build does **not** enforce org isolation for those paths.
  (The exceptions are the *specific* checks in §4.7, plus one inverted case where the port wrongly
  org-scopes a dedup that the reference applies globally — `map_change_request`.)
- **No status state machine** (see §3).
- **ID/number generation** is global, not per-org — matching the port.

---

## 6. Why it matters for the gym (scoring)

Scoring replays the gold actions **through the port** to build the reference DB and compares it to
the agent's DB (also via the port). Because the gold DB is *recomputed* on the port, deterministic
divergences are partly self-absorbed — this is **not** "every task is broken." The damage is to
**benchmark validity**, in two directions:

- Where the port is **looser** than the reference (dropped enums, missing duplicate/required/no-op/
  delete guards), an agent can reach the goal via actions the real product would reject →
  **over-rewarding** unrealistic trajectories.
- Where the port is **stricter** than the reference (e.g. empty-string FK rejection, and any
  hand-added validators), a gold action can throw during gold replay (the replay loop swallows the
  exception and continues) → a **wrong gold DB → mis-scoring**.

---

## 7. Recommended work

**P0 — restore the safety net (do first).** Bring back the differential conformance harness and
**extend it with negative/edge scenarios** (invalid + wrong-case enums, empty fields, no-op
updates, no-filter deletes, duplicates, partial-match filters, inverted date ranges). This makes
every item below a checked invariant instead of a one-off fix.

**P1 — HIGH (state/outcome-changing):**
- Enum validation as case-sensitive allow-lists per field (§4.1) — the canonical sets can be
  extracted directly from the reference `schemas/*.pyc` / the live `tools/list` input schemas.
- No-filter delete guards (§4.3).
- No-op idempotency rejection (§4.5).
- Duplicate detection (§4.2).
- Cross-entity/cross-org reference rules (§4.7), incl. full FK coverage on `update_incident`.
- Required-field guards (§4.4).

**P2 — MEDIUM:** non-negative `cost`, empty/whitespace → `NULL` normalization, date-range
validation, case-insensitive partial filters + datetime parsing, list ordering.

**P3 — LOW:** align error-message wording and validation precedence (only where tasks assert on it).

**Out of scope (confirmed non-issues):** org-scoping for general reads/writes, and any status
state machine.
