# Dakbox for many businesses: plan

Status: Phases 1 to 6 built (2026-11-12). What remains is policy and product work (section 6 decisions, public sign-up, billing, shared Meta app) and operations: see docs/OPERATIONS.md section 8. Written 2026-11-12 from a read of the current code.

## 1. Where we are

Dakbox is one business per installation. One SQLite file holds everything: 24 tables, about 340 database calls in about 30 files, one set of team logins, one set of settings,
one Meta app, one set of courier/payment/SMS keys. The assistant itself is already store-agnostic (it reads that business's products, policies and "About the store").

Process-wide state that would leak between businesses if nothing changed: login-throttle table, per-conversation locks and running-task set, the realtime event subscribers, the website
import cache, the SMS task set, the Meta template cache, the Claude client, the web-chat rate table, and four background loops (channel re-check, courier polling, SMS queue, website sync).
Public doors a business's customers or providers knock on: the Meta webhook, the shop-order webhook, payment return/IPN, and the web-chat widget with its 3 API calls.

## 2. The decision that shapes everything: how to separate businesses

| | A. One database file per business (recommended) | B. One shared database with a business id on every row |
|---|---|---|
| Code change | Small: the database layer picks the file for the current business; most queries stay as they are | Large: every one of ~340 queries and 24 tables changes; global UNIQUE rules (SKU, order number, phone, external ids) all become per-business |
| Leak risk | Very low: a forgotten filter cannot read another business's file | High: one forgotten `WHERE business_id=?` leaks data |
| Back up / export / delete one business | Copy or delete a file | Careful row-by-row work |
| Cross-business reports (your admin view) | Loop over files; fine for hundreds | Easy SQL |
| Scale ceiling | Hundreds of active businesses on one server; then move to Postgres (a schema per business) | Higher, but you pay for it in risk from day one |

Recommendation: A. A small **registry database** holds only what must be global: businesses, people and their memberships, sessions, routing for incoming webhooks, plan/limits, platform admins.
Each business's data stays in its own file, exactly as it is today, so the existing tests and screens keep working.

## 3. Target design

**Registry (new, global):** `businesses` (id, slug, name, status trial/active/suspended, plan, created), `users` (global accounts: email, password hash), `memberships` (user, business, role owner/admin/agent/viewer),
`sessions` (token hash, user, chosen business), `routes` (kind + external id → business, for Meta pages and similar), `platform_admins`, `usage` (monthly counters).

**Per business (today's schema, unchanged):** products, customers, conversations, orders, settings, policies, channels, integrations, payments, SMS, audit.
Today's `users` and `sessions` tables move to the registry. Audit stays per business.

**Request flow:** sign in once; the session picks a business (switcher in the app if you belong to several); every API request is checked against the membership and then runs with that business's database selected
(a context variable the database layer reads). Roles and permissions stay exactly as they are, but are per business.

**Incoming doors get the business in the address:** `/webhooks/meta/<slug>`, `/webhooks/shop/<id>` (already unique per website), `/pay/<slug>/<provider>/...`, `/widget?b=<public key>`.
Each business verifies with its own secrets, so a signature made for business A can never be accepted by B.

**Secrets:** one master key (DAKBOX_SECRET_KEY) derives a separate encryption key per business, so one business's stored keys cannot be read with another's.

**Background loops:** each loop walks the businesses, one at a time, sets the business context, and catches errors per business so one broken business never stops the others.

**Process-wide state:** every cache, lock, subscriber set and client becomes keyed by business (or moved into the business context).

**The existing install:** becomes business #1 ("default"): its file is moved, its team becomes global users with owner/admin/agent/viewer memberships, and sessions are reissued (everyone signs in again once).

## 4. Phases (each ends with tests passing and something you can click)

| # | Phase | What it delivers | Size |
|---|---|---|---|
| 0 | Decisions | The open questions in section 6 answered | small |
| 1 | Business-aware database (DONE) | Registry; database layer chooses the file per business via a context variable; test fixtures create businesses; the existing suite passes unchanged against business #1; migration script for the current install | medium |
| 2 | Accounts and switching (DONE) | Global users + memberships; sign in / sign out / invite per business; business switcher in the app; roles per business; platform admin role | medium |
| 3 | Incoming and background (DONE) | Per-business webhook/payment/widget addresses and routing; loops walk all businesses; realtime events, locks and caches scoped; "send this webhook to business A's address with B's secret" refused | large |
| 4 | Secrets and AI | Per-business encryption keys; AI key per business (already built) or platform key with usage counting; plan limits (staff seats, products, AI replies per month) enforced | medium |
| 5 | Platform admin and onboarding | Your admin screen: create / suspend / delete / export a business, see usage; a new-business wizard: name and what you sell, website import, connect a channel, pick the AI, first test message | large |
| 6 | Hardening | The isolation test suite (below), per-business rate limits, backups and restore drill, monitoring, a data-deletion path, documentation | medium |

Phases 1 to 3 are the risky core. Phase 1 can start before the decisions in section 6 are settled.
Rough total: 8 to 12 working sessions like the ones we have been doing, for something I would trust to host other people's customers.

## 5. How we prove businesses cannot see each other

A dedicated test suite creates two businesses and then, for every API route and every public door:
- reads, changes and deletes A's records by id while signed in to B (must be refused or not found);
- signs in as a person who belongs only to A and sends B's business header (refused);
- posts a webhook signed with A's secret to B's address (refused);
- checks searches, lists, counts, exports, realtime events, order numbers, SKUs and customer matching never cross over;
- runs the background loops with one business deliberately broken (the others still run);
- checks that deleting a business removes its file and its registry routes and nothing else.
This suite is a release gate: nothing ships to a second business until it is green.

## 6. Decisions I need from you (these shape phases 4 and 5, not phase 1)

1. **Who are the businesses?** Your own several shops, or customers you sell Dakbox to (then plans, billing and terms matter)?
2. **Sign-up:** you create each business by hand at first (simple, safe), or anyone can sign up and start a trial (needs abuse limits and email verification)?
3. **AI key:** each business brings its own key (already built, no cost to you), or you provide one and charge for usage (needs metering and quotas)?
4. **Facebook / WhatsApp / Instagram:** today each business must create its own Meta app, which non-technical shop owners will struggle with. Alternatives: you do that step for them (assisted onboarding), or you become a Meta Tech Provider with one platform app (needs Meta business verification and App Review, which takes weeks and rules).
5. **Address style:** one address for everyone (simple), or a subdomain per business like `shopname.yourdomain.com` (nicer, needs wildcard DNS and certificate)?
6. **Hosting:** where it will run, and the backup plan. One server with per-business files is fine to start.
7. **Legal and trust:** terms of service and a privacy notice for the businesses and their customers (their messages pass through your server and an AI provider).

## 7. Risks to watch

- A missed place where the business context is not set (a background task, a scheduled job): covered by the isolation suite and by making "no business selected" an error instead of a default.
- Realtime events and caches shared across businesses: each gets a business key, with tests.
- Many open database files: connections are opened on demand and closed when idle.
- Meta onboarding friction is the biggest product risk for a hosted service, not a technical one.
- Each business's database needs the same upgrades: the upgrade step runs when a file is opened and is tested on a copy first.

## 8. Not changing

The assistant's logic and safety rules, the product import, orders, payments, couriers, SMS and every existing screen keep working as they do; the new parts are the registry, the switcher, the platform admin and the routing.
