# TrendAtlas Multi-User Accounts v1

## Objective
Create a public multi-user registration and authentication foundation for TrendAtlas while preserving the current live Marek Hyperliquid account and the existing single-account production trading path unchanged.

## Non-negotiable production invariant
Until a later explicitly approved migration, the current Marek production account remains on the existing canonical execution path exactly as-is.

The following current production components must not be modified, reconfigured, restarted, or repurposed by Accounts/Auth v1:

- `scripts/execution/run_trendatlas_production.py`
- `deploy/systemd/mrv1-production.service`
- `deploy/systemd/mrv1-production.timer`
- the current Hyperliquid master account configuration
- the current `TrendAtlasProd` production agent/signer configuration
- the systemd encrypted credential `hyperliquid-agent-private-key`
- canonical execution intent, gate, journal, CLOID, authority, and account-snapshot semantics
- current real-account PnL ledger semantics
- Pi scheduler ownership or authority publication

Accounts/Auth v1 must introduce zero live-order capability and zero live-account migration capability.

## Isolation strategy
Build the new user-facing account system as an isolated web application under `web/`.

The existing Python/Streamlit production application remains untouched during Stage 1. The new `web/` application must not be imported by, called by, or required by the Pi production orchestrator.

No Stage 1 failure may block or alter the existing production service.

## Stage 1 scope: registration/authentication only
Stage 1 includes:

- public registration
- email verification
- login
- logout
- forgot-password / password-reset flow
- authenticated session
- `/dashboard` authenticated shell
- `/onboarding` authenticated shell
- `/settings` authenticated shell
- user profile record
- database row-level isolation

Stage 1 explicitly excludes:

- Hyperliquid account connection
- API/agent wallet creation
- API private-key storage
- trading settings that can affect execution
- per-user execution
- per-user orders
- per-user PnL ingestion
- modification of the current owner/Marek account
- deployment to the Pi production service

## Web/auth architecture
Use a separate Next.js web application under `web/` with Supabase Auth + Postgres.

Supabase responsibilities:

- email/password authentication
- email verification
- password reset
- user identity
- Postgres user-profile persistence
- row-level security

The browser may use the public Supabase URL and anon/publishable key. The Supabase service-role secret must never be exposed to browser code or committed to Git.

Passwords must never be stored in TrendAtlas application tables.

## Initial routes

- `/register`
- `/login`
- `/forgot-password`
- `/auth/callback`
- `/dashboard`
- `/onboarding`
- `/settings`

Unauthenticated access to authenticated routes must redirect to `/login`.

Authenticated access to `/login` or `/register` may redirect to `/dashboard`.

## Stage 1 profile model
Create a profile table keyed 1:1 to the Supabase auth user id.

Minimum fields:

- `id uuid primary key references auth.users(id)`
- `email text`
- `display_name text`
- `created_at timestamptz`
- `updated_at timestamptz`
- `account_status text` with a safe default such as `active`
- `onboarding_status text` with a safe default such as `not_started`

Do not add Hyperliquid secrets or trading credentials in Stage 1.

## Row-level security
RLS must be enabled for all user-owned tables.

For `profiles`, authenticated users may read/update only the row whose `id = auth.uid()`.

No client-side query may be trusted as the isolation boundary; the database RLS policy is the enforcement boundary.

## Future model boundary
The Stage 1 architecture should leave room for later isolated tables such as:

- `hyperliquid_accounts`
- `trading_settings`
- `account_state`
- `account_performance`
- `execution_journal`

These are future stages only and must not be wired to live execution in Stage 1.

## Existing owner account migration rule
Do not auto-create, auto-link, or auto-migrate Marek's existing live Hyperliquid account into the new multi-user system.

The owner account migration will be a separate explicitly reviewed step after multi-user auth, account isolation, and Hyperliquid onboarding are proven safe.

## Explicit owner-account cutover approval — 2026-09-06
Marek approved a controlled migration of the existing owner account to the multi-account executor. This approval does not itself enable exchange writes.

The first live execution remains manual and one-shot. It must fail closed unless the legacy `mrv1-production.timer` is both disabled and inactive, `mrv1-production.service` is inactive, the eligible account set contains exactly the explicitly allowlisted master address, the current canonical signal id is confirmed, and every planned action is within the configured USD cap. No competing timer may be installed or enabled during the canary phase.

## Security requirements

- no secrets committed to Git
- provide `.env.example` only with placeholders/public-variable names
- service-role secrets are server-only
- no Hyperliquid private keys in Stage 1
- no plaintext secret logging
- no auth tokens logged
- use secure session/cookie behavior provided by the chosen Supabase SSR integration
- validate redirect destinations; no open redirects
- email normalization handled consistently
- user-facing auth errors must not expose internal stack traces or secrets

## UX target
Registration should be simple:

1. name
2. email
3. password
4. password confirmation
5. accept terms checkbox placeholder
6. create account
7. verify email
8. login/continue
9. land on onboarding/dashboard

The authenticated dashboard in Stage 1 should clearly say that the user's trading account is not connected yet and offer a disabled/non-live `Connect Hyperliquid` onboarding step for the next stage.

## Test requirements
At minimum cover:

- register validation
- password confirmation mismatch
- protected-route redirect when unauthenticated
- authenticated route access
- logout
- password-reset flow plumbing
- profile ownership/RLS migration definitions
- no production execution imports from `web/`
- no current production account address or signer secret copied into new account code
- no Hyperliquid order submitter reachable from Stage 1 web code

## Acceptance criteria
Stage 1 is complete only when:

- the new auth web app builds/tests independently
- current Python production tests relevant to execution/account safety remain unchanged and passing
- diff against the Stage 1 base contains no changes to the current production orchestrator/service/timer/signer path
- no generated `data/*` or `outputs/*` files are committed
- no live order is sent
- no Pi deployment is performed
- no authority publication is performed
- Marek's current live account continues operating through the pre-existing canonical path without any dependency on the new web app

## Rollout rule
Accounts/Auth v1 remains branch-only and non-production until explicit approval after review. It must not be merged or deployed automatically.
