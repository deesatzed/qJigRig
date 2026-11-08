# Hosted boundary interim review

## Review Scope

Inspected `src/qjig/providers.py`, `src/qjig/hosted_preflight.py`, `src/qjig/account_client.py`, the service gate in `src/qjig/fresh_service.py`, references to `_send_unchecked`, and the credential changes through commit `f3ebdc2`. Reviewed the current offline verification checkpoint. This is not the required final whole-project security review.

## Summary Judgment

Blocked for hosted acceptance: guarded dispatch, complete billing and prior-spend reconciliation are not established. Normal service and typed hosted paths currently refuse inference. The internal HTTP method is still callable by Python code with the credential and is not an authorization boundary.

## Findings

| Severity | Category | Finding | Why It Matters | Required Fix |
|---|---|---|---|---|
| High | Accounting | `call_typed` and the workbench deliberately refuse hosted dispatch; no tested physical send is connected to complete reservations and settlement. | The required provider-path smoke and comparison cannot run safely. | Finish the single guarded path and test journaling, reservations, settlement and uncertainty before enabling it. |
| High | Spend assurance | Key limits exclude BYOK and the current credential lacks management access; prior goal spending and additional billable categories remain unknown. | Account credit and key remainder do not bound all possible charges or establish prior-goal totals. | Reconcile authoritative usage and bound or exclude every applicable billing category; leave unknowns blocking paid calls. |
| Medium | Resilience | `_urllib_post` reads both successful and HTTP-error response bodies without a byte limit. | A large or unbounded upstream response can exhaust process memory before an attempt is reconciled. | Add a bounded read and treat overflow after possible dispatch as an unknown outcome that retains the journaled attempt; test both response paths without live inference. |
| Medium | Boundary design | `_send_unchecked` can perform actual HTTP with the matching credential and has no ledger or preflight check. Only tests reference it in the inspected tree. | Python underscore naming and credential comparison do not prevent alternate internal callers from bypassing accounting. | Make the physical send reachable only through the guarded accounting path in normal execution; test all supported entrypoints. Do not represent private naming as a security boundary. |

## Correctness

The credential check detects the tested change between typed entry and preflight; it does not prove a key did not change and revert or stay unchanged after the last check. Preflight explicitly returns `hosted_authorized=false`.

## Security and Privacy

The account read uses no-redirect HTTP and sanitizes exceptions; the adapter rejects untrusted origins and redacts the configured secret from returned bodies. These observations do not establish complete protection against all sensitive data or adversarial in-process callers.

## Tests

At `f3ebdc2` the offline suite passed 715 with 8 skips, and isolated install and synthetic browser checks passed as recorded in `docs/verification/2026-11-08-current-offline-checkpoint.md`. No current test in this review establishes a real hosted send, complete billing or bounded HTTP response reads.

## Maintainability

Account observation, ledger, preflight and adapter checks span multiple modules; the eventual dispatch integration needs one documented source of truth for authorization and explicit failure semantics.

## Performance

Unbounded response buffering is the concrete resource concern identified above. No throughput or load claim was assessed.

## UI/UX Impact

The user-facing hosted path remains unavailable. This review did not inspect or grade the full UI.

## Regression Risk

Future changes that remove the refusal can turn currently nonauthorizing helpers into an unsafe send path if accounting, billing, output limits and interrupted-call handling are not enforced together.

## Scope Creep Check

Findings concern the required hosted model and accounting path. No new product capabilities are proposed.

## Required Fixes Before Done

Resolve the findings, complete the real-provider comparison and run the final scoped diff/security review against the actual final implementation and evidence.

## Optional Improvements

None identified in this narrow review.
