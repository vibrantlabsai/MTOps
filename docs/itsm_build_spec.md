# ITSM Port — Implementer Contract (ground truth from the live MCP)

This is the single source of truth for reimplementing the ITSM domain natively (pydantic +
in-memory) faithfully to the original ServiceNow MCP server. Everything here was extracted
from the live Docker image `shivakrishnareddyma225/enterpriseops-gym-mcp-itsm` (running as
container `eops-itsm`, host **:8016** → container 8005) on 2026-06-02.

## Oracle access (for differential testing)
- Seed a DB: `POST http://localhost:8016/api/seed-database` with
  `{"database_id","name","description","sql_content"}`.
- JSON-RPC at `POST http://localhost:8016/mcp`: `initialize` → `notifications/initialized` →
  `tools/list` / `tools/call`. Headers: `x-database-id`, `x-itsm-user-token`,
  `Accept: application/json, text/event-stream` (responses are SSE `data:` lines).
- Admin token in the canonical seed: `admin_token_marcus_2024_secure` (USER_001, ORG_001).
- Inspect resulting state: `docker cp eops-itsm:/app/mcp_databases/itsm_<dbid>.sqlite .`

## Schema
- 24 tables. Authoritative DDL: `docs/itsm_schema.sql`. Tool catalog (93 tools, exact
  signatures + JSON schemas): `docs/itsm_tool_catalog.json`.
- Timestamp columns differ per table: `incident` uses `created_at`/`updated_at`; most others
  use `created_on`/`updated_on`. Match exactly.
- Constraints: `ci.cost >= 0`; email `LIKE '%@%'`; `UNIQUE(users.phone)`;
  `UNIQUE(org_id, group_id, user_id)` on user_group_member.

## ID / number generation (deterministic — required for gold-action DB-hash)
- IDs: `<PREFIX>_<seq:03d>`, seq = (max existing seq for that table) + 1.
  Prefixes: INC_ (incident), CI_ (configuration_item), NOTIF_ (notification), USER_ (users),
  LOC_ (location), GROUP_ (user_group), and member_id/mapping ids similarly.
- `create_incident.number` = `INC-{seq:06d}` (e.g. `INC-000024`). NOTE: the SEED uses a legacy
  `INC0000001` (no dash, 7-pad); seed rows keep their stored value, newly-created incidents get
  the dash form. Don't "fix" seed values.

## create_incident defaults (when arg omitted)
- status=`new`, category=`inquiry-help`, priority=`planning`.
- priority is NOT derived from impact×urgency — it simply defaults to `planning`.
- `*_display` fields are left **NULL** on creation (tools never derive them; only the seed
  bakes display snapshots). Same expected for update_incident — verify per tool via diff.
- org_id is inherited (acting/caller user's org; all our tasks are ORG_001).

## Validation & error envelopes (replicate where tasks depend on it)
- `send_notification`: the `email` must belong to a user in the org, else typed error
  `{"detail":{"error":true,"error_code":"VALIDATION_ERROR","details":[{"code":"USER_EMAIL_NOT_FOUND",...}]}}`.
- `add_new_user`: `phone` must match `+X-XXX-XXX-XXXX`, else FastAPI-style
  `{"detail":[{"type":"value_error","loc":["body","phone"],"ctx":{"error_code":"INVALID_PHONE_FORMAT"}}]}`.
- Two error shapes exist (custom envelope vs FastAPI list). Our tools raise Python exceptions;
  the environment stringifies them into the tool message — exact error text only matters when a
  task's nl_assertion/gold path depends on it.

## Per-table ID prefixes (new records = `<PREFIX>_<maxseq+1:03d>`)
Use these exact prefixes (derived from the seed); verify the per-tool `number`/id format against
the oracle when in doubt:

| table | prefix | table | prefix |
|---|---|---|---|
| incident | INC_ | change | CHG_ |
| child_incident | CINC_ | change_request_mapping | CRM_ |
| configuration_item | CI_ | problem | PRB_ |
| incident_affected_cis | TASKCI_ | knowledge | KB_ |
| incident_knowledge | IKB_ | sla_definition | SLA_ |
| incident_sla | TSLA_ | service | SVC_ |
| incident_template | TMPL_ | service_offering | SVCOFF_ |
| location | LOC_ | user_group | GROUP_ |
| notification | NOTIF_ | user_group_member | MEMBER_ |
| users | USER_ | | |

`incident.number` = `INC-{seq:06d}`; check whether other entities (change, problem, knowledge)
also generate a human `number`/`kb_number` and in what format by probing the oracle.

## Reimplementation rules
1. Tools mutate an in-memory pydantic DB only (no SQL); optional CRUD action-log post-run.
2. Typed pydantic inputs AND returns (`-> Incident` / `List[Incident]`); schema from type
   hints + docstrings (tau2 `Tool` style). Batch variants exist (e.g. `add_child_incidents`).
3. Deterministic clock (`get_now()` fixed per task) for created/updated timestamps.
4. Mirror the MCP's module layout: one tool module per category (incidents, users, groups,
   locations, configuration_items, changes, problems, knowledge, notifications, services,
   service_offerings, sla_definitions, sla_metrics, incident_slas, incident_templates,
   incident_knowledges, incident_affected_cis, change_request_mappings, notification_analysis).

## Differential conformance protocol (primary correctness gate)
For each tool: seed both the live MCP and our toolkit from the same db.json, run an identical
battery of calls, then diff (a) the return value and (b) the full DB state — normalizing
volatile timestamps. Any divergence is a port bug. The MCP is always the oracle.
