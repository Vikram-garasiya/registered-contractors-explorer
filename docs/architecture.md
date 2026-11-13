# Architecture decisions

Lightweight ADRs: context → decision → consequences / alternatives considered.

## ADR-1 Read data.gov.sg live; don't keep a local copy

**Context.** The BCA register has about 24,000 rows. The screen needs full-text search,
sort and offset paging. `datastore_search` supports all three natively and answers a
20-row page in well under a second.

**Decision.** `DataGovSG_IS.Contractors_Search` calls data.gov.sg on every request. There are no
entities and no sync timer.

**Consequences.** Data is always current and nothing needs reconciling. Availability and
rate limits are inherited from upstream. That is mitigated by an optional API key, one
call per page view, safe typed errors, and nightly contract tests.

**When to change.** Switch to a cached snapshot in a Core module (timer + staging + atomic
swap) when any of these apply: analytics over the whole set (aggregations, history),
traffic that would breach upstream limits, or availability requirements stricter than
data.gov.sg's.

## ADR-2 The integration service never raises; it returns codes

**Context.** REST failures surface as many exception types and HTTP statuses.

**Decision.** Two parts:
* The REST `OnAfterResponse` callback calls `ValidateGovApiStatus`, which turns each status
  into a typed `GovApi*` user exception.
* `Contractors_Search` catches each exception type, plus `CommunicationException` and
  `AllExceptions`, and returns `ErrorCode` (stable, machine-readable), `ErrorMessage`
  (safe to show users) and `IsRetryable`, with an empty `Response`.

**Consequences.** Consumers never need exception handling for upstream problems and can't
leak technical detail. The details are still logged on the server (`LogError = True`).
A service action keeps the module loosely coupled: consumers don't recompile when DataGovSG_IS
changes internally.

## ADR-3 Validate, allow-list and sanitise at the boundary

**Context.** Upstream rejects punctuation in `q` (HTTP 409 "q is invalid"), accepts any
`sort` expression, and caps nothing on our side.

**Decision.** DataGovSG_IS owns all input rules:
* `Limit` must be 1–5000 and `Offset` must be ≥ 0, both typed Integer.
* `SortBy` must be one of five fields, optionally followed by ` desc`; anything else is
  ignored.
* `Query` is sanitised: punctuation becomes spaces, then repeated spaces are collapsed.

**Consequences.** The UI can't build an invalid or unbounded request. Users typing a unit
number (`#03-10`) or a company suffix (`PTE. LTD.`) get results instead of an error. The
contract test `test_punctuation_is_rejected_upstream_so_gov_is_strips_it` records why the
sanitiser exists, and will flag it if upstream relaxes the rule.

## ADR-4 Export on demand, capped at 5,000 rows

**Context.** The original export data action was fetched *At start*, doubling upstream calls
on every page view, and it only exported the visible 20 rows.

**Decision.** `GetContractorsForExport` is *On demand*, triggered by the Export button. It
asks for up to 5,000 rows matching the current search and sort in one call; the contract
tests confirm upstream serves this.

**Alternatives.** A full-register export (24,000 rows) would need several paged calls in a
server action, plus a timeout budget. That's deferred until someone needs it.

## ADR-5 Test what you can't see: contract, end-to-end and IaC

The app holds no data and very little logic of its own; most risk sits at the upstream
boundary and in the UI wiring. So:
* **Contract tests** pin every upstream assumption, including field names, formats, sort,
  the export limit and the 409 behaviour.
* **Playwright** proves the user journeys against a deployed environment.
* **IaC** is tested offline with `terraform test` and a mocked provider.

A `RegisteredContractors_Tests` self-test module, in its own LifeTime application that is never deployed to
Production, is the next step for unit-level checks of the sanitiser and allow-list.

## ADR-6 One environment per Terraform state; servers are cattle-ish

Each OutSystems environment (LifeTime, Dev, Test, Prod) has its own VPC, database and state
file, so a mistake in Dev can't touch Prod and environments can be rebuilt independently.
Front-ends are plain EC2 instances, not an Auto Scaling group. OutSystems front-ends must be
registered with the Deployment Controller, and scaling in needs deregistration, so a fixed,
explicitly managed count is safer. EC2 auto-recover and AWS Backup provide the self-healing.
Patching runs one server at a time.
