# Dakbox

Every social inbox in one place, with an assistant that answers customers and does the work: product questions,
order status, carts, delivery estimates, return requests. Built from the *Commerce Inbox Prototype* (Northwind Outdoor demo store).

```
dakbox/
  app/        Flutter app (web, macOS, Android, iOS)    Provider + Dio, one design file: lib/brand/theme.dart
  backend/    FastAPI + SQLite                          the assistant, channels, orders, approvals
  build_web.sh  builds the web app; the backend then serves it at /
```

## Run it

```bash
# 1. backend (Python 3.12)
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 4000        # seeds the demo store on first run

# 2. app (in another terminal)
cd app && flutter run -d chrome                    # or: -d macos
```

The first time you open the app it asks you to **create the owner account** (no default password exists). After that, everyone signs in.

Or one server: `./build_web.sh`, start the backend, open <http://localhost:4000>. API docs: `/api/docs`.
Reset the demo data any time with `cd backend && .venv/bin/python -m app.seed --reset`.

Try it without any credentials: in the app press **+** in the Inbox (or Assistant, Try it), pick a channel, and write as a customer
in English, Bangla (`তাঁবু আছে?`) or Banglish (`bhai tent ta ache?`). Open `/widget` for the customer-facing website chat.

## What is real and what is simulated

| Part | State |
| --- | --- |
| Inbox, conversations, modes (Assistant / Review / Me), approvals, orders, products, customers, insights, settings, policies | Real, stored in SQLite |
| Assistant with an AI model (tool use) | Real when a provider key is set: **Assistant, Engine and key** (owners/admins) takes Claude, ChatGPT (OpenAI), Gemini, DeepSeek, or any OpenAI-compatible address (Groq, OpenRouter, a local server). The key is checked with the provider, stored encrypted per provider, and used on the next message (no restart); you choose the model, and a smaller one for translations and summaries. A panel key wins over the server's environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`). Order limits, stock, payments and refunds are enforced by Dakbox's code, not the model, so they hold for every provider. Only stand-ins were tested: no real provider was called, and Gemini's and DeepSeek's compatible endpoints are used from their public docs. |
| Assistant without a key | A rule engine that calls the same tools under the same safety rules. Used for every test so far. |
| WhatsApp Cloud API, Messenger, Instagram | Built to Meta's published docs (checked Nov 2026) and tested against a stand-in for Meta's API (`backend/tools`). **Not yet run against Meta itself**: that needs your Meta app, reviewed permissions and tokens. See *Connect Meta* for what to expect and how to verify. |
| Web chat widget (`/widget`) | Real, works end to end. |
| SSLCommerz, bKash, aamarPay, Steadfast | Built (see *Connect couriers and payments*) and tested against stand-ins. **Never run against the real services.** Until a provider is connected, shipping gives a labelled demo parcel and payment links are unavailable. |
| SSL Wireless (ISMS Plus), Alpha SMS | Order SMS built to their public API pages (see *Order SMS*) and tested against stand-ins. **Never run against the real services.** With none connected, order messages show as "Not sent". |
| Grameenphone/Robi/Banglalink corporate SMS, Pathao, RedX, Paperfly, eCourier, Nagad | Cards and toggles only, or marked not built. No provider API is called. |
| Insights charts | KPIs and the 14-day series are sample data (labelled). The "Live" strip is real. |

### Connect Meta (real WhatsApp, Messenger, Instagram)

You do this in the app, not in files: **Connections, Channels**. Tokens are checked with Meta before anything is saved, stored encrypted
(`DAKBOX_SECRET_KEY`, or a key file created next to the database), and never shown again (only the last four characters).

1. **Meta app.** In Meta for Developers, create an app (or use one) and add WhatsApp, Messenger and/or Instagram.
2. **Meta app card.** Enter the App ID, App secret, your **public https URL**, and generate a **verify token**. Meta only delivers webhooks to a public https address; while developing, use a tunnel.
3. **Webhook in Meta.** For each product set the Callback URL (`https://YOUR-URL/webhooks/meta`) and the verify token, and subscribe to the `messages` field (Messenger also `message_deliveries`, `message_reads`).
4. **Connect a real account.** Pick the channel and paste:
   - WhatsApp: *Phone number ID*, *WhatsApp Business Account ID*, and a **System User** access token (not the 24-hour test token).
   - Messenger: *Page ID* and a Page access token (`pages_messaging`).
   - Instagram: either *Instagram Login* (account ID + token, `instagram_business_manage_messages`) or *Facebook Page* (Page ID + Page token).
5. **Send a test message** to the account. It should appear in the Inbox. If it does not, **Recent webhook activity** (under the channels) says why: bad signature, an account that is not connected, or nothing arriving at all.

What the integration does: routes each message by the account it was sent to (several numbers/pages work side by side), ignores duplicate deliveries and echoes of your own messages,
shows delivery receipts (Sent, Delivered, Read, or the failure reason), splits long replies to each channel's limit, uses WhatsApp **templates** (fetched from Meta, approved only) when the 24-hour window is closed,
hands photos, voice notes and documents to a person (the assistant cannot see them) with a polite acknowledgement, and turns a channel red with a plain explanation when Meta rejects its token.
Webhooks are verified with HMAC-SHA256 over the raw body, and with no app secret set a live install **refuses** unsigned webhooks.
Tokens are re-checked every 6 hours; the card shows expiry when the App ID and secret are saved.

**Verified vs not.** Request and webhook shapes were checked against Meta's pages and are covered by 52 tests using the stand-in. Not verified against the real service: that your app's permissions are approved,
the exact text of live error messages, Messenger's text-length limit (2,000 characters used), and looking up an Instagram user's name (not documented, so skipped; they appear as "Instagram user ####").
Not built: Messenger/Instagram messages outside the 24-hour window (the HUMAN_AGENT tag's request format could not be confirmed), sending images or files, and downloading the media customers send.

**Try the whole flow with no Meta account** using the stand-in:
```bash
cd backend && .venv/bin/uvicorn tools.fake_meta_server:app --port 4010
printf 'META_GRAPH_BASE=http://127.0.0.1:4010\nMETA_IG_GRAPH_BASE=http://127.0.0.1:4010\n' > .env   # delete this file for real Meta
# connect WhatsApp with phone ID 106540352242922, WABA 102290129340398, any token starting "good"
curl -X POST 'localhost:4010/_fake/webhook?kind=wa&text=hello&secret=YOUR_APP_SECRET'     # a signed customer message
curl localhost:4010/_fake/outbox                                                           # what Dakbox sent to "Meta"
```

### Orders placed in chat

The assistant can take an order end to end (Assistant mode, or Review mode where a person approves it): it collects payment method, name, mobile number and address, shows a written **summary** (lines at live prices, delivery, total), and only after the customer's **next** message says yes does it call `place_order`.
Enforced in code (`backend/app/checkout.py`), whichever engine runs: the summary is fingerprinted, so any change to the cart, a price, the delivery charge or the details invalidates it; the summary must have been sent and the customer must have written again; stock is taken atomically (cancelling a chat order puts it back);
limits hand over to a person (largest order, default ৳20,000; 20 items; 3 orders per customer per day). Orders start **Pending**: staff still confirm cash on delivery by phone, and online payments stay unpaid until the provider confirms (a payment link follows the confirmation message). Switch it off or set the limit under Assistant, Behavior.
Not built: staff creating an order from a cart, discounts, editing an order after placement. Not run with Claude (no API key): only the offline engine was exercised; the same rules apply to both.

### Import products from a website (Connections, Store; or Products, Import from website)
Type a shop address and Dakbox shows what it found before saving anything: Shopify (`/products.json`), WooCommerce (Store API, no keys), or any other
site (sitemap plus the schema.org / Open Graph product data shops publish for Google). Imports are keyed by the site's own product id, so syncing again
(button, or automatically every 6 hours) updates price, photo and sold-out status without duplicating, never overwrites stock you counted yourself,
and sets stock to 0 (never deletes) for products that left the site. Websites say only "in stock", so the owner picks the stock number for those.
Prices on a non-BDT site need an explicit confirmation. It cannot read JavaScript-only shops, logins, or sites whose robots.txt says no.
Safety: only public https/http addresses (never localhost, private networks, cloud metadata; every redirect hop is re-checked), size/time/page caps,
text from the site is stripped of markup. Code: `backend/app/catalog_import.py`, `routes/catalog.py`; tests use stand-in sites (`tools/fake_site.py`).
Never run against a real shop. To try it locally: `DAKBOX_ALLOW_PRIVATE_FETCH=1` on the API (dev only) and `python -m tools.fake_site_server`, then import
`localhost:4012` (Shopify), `:4013` (WooCommerce), `:4014` (ordinary site).

### Orders made by staff (Orders, New order; or Inbox, customer panel, Create order from cart)
Staff build an order from products with live prices and stock, pick or add the customer, address, delivery area (charge from the courier setting, can be set by hand
and is recorded), and payment (cash on delivery, or a connected online provider whose payment link is then sent from the order). Stock is reserved atomically
(the last unit sells once), details are validated like chat orders, the order is marked "Created by staff", and cancelling it puts stock back. From a conversation
it uses that conversation's cart, empties it and drops any summary the assistant was waiting on. Needs the `orders.manage` permission (owner, admin, agent).
Code: `checkout.staff_quote/staff_place`, `POST /api/orders` and `/api/orders/quote`, `app/lib/screens/new_order.dart`. No customer confirmation step and no per-day limit: a person is accountable.

### Orders from your website (Connections, Store, Set up order sync)
When a customer orders on a connected website, the shop pushes the order to `POST /webhooks/shop/<id>` (a webhook) and it appears in Orders as "From website".
Shopify (Settings, Notifications, Webhooks: Order creation / payment / cancellation; paste Shopify's signing key into Dakbox), WooCommerce (Settings, Advanced, Webhooks:
Order created / updated; Dakbox's secret goes into Woo), or any other site posting Dakbox's JSON format with `X-Dakbox-Signature: sha256=<hmac hex>`.
Every request must carry a valid HMAC-SHA256 signature of the raw body or it is refused; an unknown address or a Shopify site with no key saved yet is closed (404).
Orders are created once (keyed by website + the website's order id) and later events only move them forward (unpaid to paid, to cancelled; a shipped order is never
cancelled automatically); staff edits are never overwritten. Customers are matched by phone. Lines link to the imported catalogue and take stock off Dakbox's own count
(never refused for stock; never below 0; a cancellation gives it back). The amount the customer was charged (discounts, tax) is the total and the cash-on-delivery amount.
Orders in a currency other than Taka are not imported unless that currency was accepted when the website was connected. The customer "order placed" SMS is a per-website switch.
Needs a public https address (same as Meta). Code: `app/shop_orders.py`, `routes/shop_orders.py`. Payload shapes come from the platforms' public docs and were never
checked against a real shop; test with the platform's own "send test" first.

### How the assistant finds products
`backend/app/agent/catalog_search.py`: one search used by both engines (and by Claude's `search_products` tool). It understands Bangla script, Banglish and English
(saree = sari = shari = শাড়ি, lal = red = লাল), plurals, common Bangla endings (শাড়িটা, শাড়ির), one-letter typos, and ignores filler (do you have, ache, আছে, কত). Results say how good
the match is (exact, closest, none, or popular when no product word was used), so the assistant can say honestly "we do not have that, we sell ..." instead of guessing. The offline engine
answers any catalogue (one product with variants and stock, a short list, or "not found" with what the store does sell); it used to know only four outdoor words. The Claude prompt no longer assumes
an outdoor shop: it is told what the store sells (Assistant, Behavior, About the store, or else a sample of the catalogue). Add a synonym by adding a word group in `_GROUPS` there.

### Businesses (multi-business, phases 1 to 3 of 6)
Dakbox is moving to host many businesses. Plan: `docs/MULTI-BUSINESS-PLAN.md`.
**Phase 1:** each business has its own database file, listed in a small registry (`registry.db`, created next to your `dakbox.db` the first time the server starts). Your existing install is registered in place as
the business **default**: nothing is moved. Every database call runs for the "current business" (`with db.business("slug"): ...`); `DAKBOX_STRICT_BUSINESS=1` turns "no business selected" into an error
(for a hosted install). CLI: `python -m app.businesses list | create "Name" [--slug x] [--demo] | rename | status | delete --yes`.
**Phase 2:** people are global accounts with a membership (and role) in each business. Sessions live in the registry and name the business they work in; that, and only that, decides which business's data a request
sees (a header or parameter naming another business is ignored). The account menu lists your businesses and switches between them (the screen reloads with the other business's data). Roles, deactivation and the
"one active owner" rule are per business; a person removed from one business stays in the others. Inviting someone who already has an account adds them without touching their password or name, and a business admin cannot
reset the password or rename an account that also belongs to other businesses. A platform administrator (the owner of the original install, made automatically on upgrade) can list, create, rename and suspend businesses
(`/api/platform/businesses`; the account menu has "New business…"); that role alone gives no access to any business's data. Suspending a business signs its people out at once. Realtime updates reach only the business
they happened in. On upgrade, existing team members become accounts (same ids, roles and passwords) and everyone signs in once more.
**Phase 3:** every public door names its business and uses that business's own secrets: Meta `/webhooks/meta/<slug>` (verify token and app secret per business), shop orders `/webhooks/shop/<slug>/<id>`,
payments `/pay/<slug>/<provider>/<kind>`, courier `/hooks/<slug>/steadfast`, website chat `/widget?b=<slug>` (the chat API takes the same `b`). A request signed for business A is refused at business B's address; an unknown or suspended
business is a plain 404. The addresses the app shows or sends to gateways, Meta and couriers carry the slug automatically. The original addresses (`/webhooks/meta`, `/pay/<provider>/<kind>`, ...) keep working for the default
business, so nothing already configured breaks; with `DAKBOX_STRICT_BUSINESS=1` they are off. Background jobs (channel re-check, courier polling, SMS queue, website sync) walk every active business, each inside
its own business with its own time limit, so one slow or broken business never delays the others. Caches and rate limits are keyed by business. Code: `app/publicbiz.py`, `app/jobs.py`.
**Phase 4:** secrets and AI. Each business encrypts its own secrets (channel tokens, shop signing secrets, AI keys, Meta app secret) with a key derived from the server master key and the business id (`b1.` prefix), so a stolen row pasted
into another business cannot be opened. Secrets written before this (no prefix) are readable only in the original business and are re-encrypted under its own key at startup, or by `python -m app.businesses rekey`. Platform-level secrets
(the platform's AI keys) use the master key (`m1.`). Plans (`free`: 3 team seats, 100 products, 100 AI replies a month, no platform AI; `standard`: 10, 1000, 2000, platform AI; `unlimited`) are editable under `/api/platform/plans`, a business is
moved with `PATCH /api/platform/businesses/<slug>` (`plan`, and `limits` to override single numbers); the original install is on Unlimited. Seats are checked when inviting or re-activating, products on create and on website import (updates are never
blocked). A business uses its own AI key, or, if its plan allows it, the platform's (`PUT /api/platform/ai`, or the server's environment key); only replies written with the platform's key count against the monthly allowance, own-key replies are
counted but never limited, and when the allowance is used up the offline rules keep answering. Usage per business and month: `GET /api/platform/usage`; every member sees their own plan at `GET /api/plan` (shown on the Engine tab and the Team page). Code: `app/secrets_store.py`, `app/limits.py`, `app/aikey.py`.
**Phase 5:** the platform administrator's screen (the **Platform** item in the navigation, visible only to platform administrators) lists every business with its plan and use of seats, products and AI replies; creates a business (with a plan) and opens it with its setup guide;
changes a business's plan; suspends or reactivates it; exports its data (a zip of one CSV per table plus a manifest; channel tokens, signing secrets, AI keys, password hashes and sign-ins are left out; the download link works once and expires in about a minute);
deletes it (the address must be typed; the default business can never be deleted; people keep their accounts); edits plans; manages the platform's own AI keys; and stops, allows or signs out any account everywhere. Everything the administrator does is
recorded in the platform's own log (Activity tab, `GET /api/platform/log`). The administrator sees only sizes and use, never a business's customers or messages: to look inside a business they must **Open** it, which joins them as an admin, is written
in that business's own activity log (`support.join`), and can be undone with `POST /api/platform/businesses/<slug>/leave`. A new business shows a **Get started** guide to its owners and admins (about the store, products, a channel, the AI, a test message); each step's state is read from real data
(`GET /api/onboarding`), the channel and AI steps can be skipped, and the guide can be hidden. The business that already existed is never shown the guide. Code: `app/routes/platform.py`, `app/routes/onboarding.py`, `app/export.py`.
**Phase 6:** hardening. `DAKBOX_HOSTED=1` turns on strict business selection by default, starts a blank server (no demo data), switches the API docs off, and makes the server refuse to start without `DAKBOX_SECRET_KEY` and `DAKBOX_DATA_DIR`. Rate limits per business (signed-in requests and public addresses; `429` with `Retry-After`) and an address-wide sign-in guess limit.
Backups: a consistent copy of the registry and every business (`python -m app.backups create|list|verify|drill|prune|restore`), daily on a hosted server, with checksums, an integrity check and a **restore drill** that opens every business from the backup in a scratch folder; the master key is never in a backup. `GET /healthz` for monitors and Platform > Health for the details.
Data deletion: an owner can erase one customer's personal data (Customers > row menu), the administrator can delete a business or an unattached account. The isolation suite (`python -m pytest -m isolation`, run by `backend/tools/release_gate.sh`) walks every route and proves one business cannot see or change another's data; it already caught and fixed a real bug (the `/api/me` exemption also matched `/api/meta`).
**Platform console** (Platform in the navigation; also reachable with no business selected via "Open the platform console" on the business picker). Overview: totals, a "needs attention" list (suspended businesses, plans nearly full, stopped accounts, health problems) and a feature matrix of every business (channels, couriers, payments, SMS, AI engine, products, orders and messages in 30 days, last activity). Businesses: search and filter, then a business page with plan and use, connections and their status, website import, the assistant and its key source, team, setup guide and recent staff activity (sizes, statuses and staff actions only, never customers or messages), with Open, Export, Suspend, Delete and plan change. Users: every account across all businesses, filters (platform admins, stopped, never signed in, no business), and a user page: rename, roles per business (change, switch off, remove, add), open sessions, reset password (temporary, forces a new one), sign out everywhere, stop or allow, make or remove platform admin, delete an unattached account. New user: create an account and optionally put it in a business with a role. API: `GET /api/platform/businesses/<slug>`, `/features`, `/accounts/<id>`, `POST /accounts`, `/accounts/<id>/reset-password`, `PUT|DELETE /accounts/<id>/memberships/<slug>`.
**Two panels.** *Super admin panel* (platform administrators land here after signing in; dark top bar, no inbox): create businesses (each with its own owner: a new person with a temporary password they must change, or an existing account by email; the super admin is **not** made a member), plans, people, platform AI keys, health and backups, activity, and the overview and feature matrix. To look inside a business the super admin presses Open, which joins them as an admin, shows a "Super admin · you are inside <business>" bar with a way back, and is written in that business's own log. *Business panel* (the owner and their staff): inbox, orders, products, customers, assistant and so on, plus **Team** (the owner and admins add staff, choose roles, switch people off) and **My business** (owner: rename the business, see plan and use, download a copy of the data). Owners have no super admin powers: every `/api/platform` route refuses them. API: `POST /api/platform/businesses` with `owner: {name, email, password}`; `GET|PATCH /api/business`, `POST /api/business/export`. On a hosted server (`DAKBOX_HOSTED=1`) the first account is the super admin only; on a single-shop install it is also the shop's owner.
Everything about running it is in `docs/OPERATIONS.md`, including what is not built (public sign-up, billing, shared Meta app, off-server backup copies).

### Order SMS (shipped, delivered, refund, payment failed)

**Connections, SMS.** Messages are built from fixed templates and order facts in the customer's language (Bangla, Banglish or English), never from anything a customer typed.
Automatic messages go out for *Shipped* (with tracking and the cash to keep ready), *Delivered*, *Refund issued* and *Payment failed*, if that row's SMS switch is on under Notifications; the **Send status update** button on an order sends a real SMS too.
*Order placed* and *Out for delivery* have no trigger yet (orders are not created in Dakbox, and no courier status means "out for delivery").

| Provider | What it does | Gaps in its public docs |
| --- | --- | --- |
| Alpha SMS (`api.sms.net.bd`) | Send, balance (used to verify the key without sending anything), delivery report polled every minute | Only "Sent" and "Complete" appear as statuses, so any other word is never shown as delivered; no part-counting or rate-limit rules; no client reference id, so a timed-out send is recorded as **Unknown** and never repeated automatically |
| SSL Wireless ISMS Plus (`smsplus.sslwireless.com`) | Send with a unique client reference (so a retry after a timeout cannot text twice) | No balance, status or delivery-report call: connecting sends one real test SMS, and messages stay **Accepted**, never "Delivered". Your server's IP must be whitelisted in their portal. The docs page and the API are on different hosts; the API host is the one the page states |

Rules: one automatic message per event (a repeated courier poll cannot text twice); **quiet hours 22:00 to 08:00 Bangladesh time** (automatic messages wait, a person pressing Send is not held; switch off or change under Connections, SMS);
a cap per number and per day (6 and 500 by default); a failed or unknown message is shown with the reason and a **Send again** button for people who can manage orders; a rejected API key turns the provider red and stops all sending until it is checked again;
the part count (160 characters per part in plain English, 70 with Bangla) is shown for each message. Only order updates are sent, never promotions (BTRC has separate rules for those).
Grameenphone and Robi/Banglalink corporate SMS are not built: their API documentation is not public.

Try it with no accounts: run the stand-in below, set `SSLWIRELESS_BASE=http://127.0.0.1:4011/api/v3` and `ALPHASMS_BASE=http://127.0.0.1:4011` in `backend/.env`, connect with token `ssl-token-0001` / sender `NORTHWIND` (any `01XXXXXXXXX` test number) or key `alpha-key-0001`, and read what was "sent" with `curl localhost:4011/_fake/sms`.

### Connect couriers and payments

In the app: **Connections, Couriers** and **Payments**. Credentials are checked with the provider, stored encrypted like the Meta tokens, and never shown again.
Each card has **Setup URLs** with the exact callback/IPN/webhook addresses to paste into that provider's panel. Real gateways only call a **public https** address, so set the public URL first (same field as Meta); live mode refuses plain http.

| Provider | What it does | Built from |
| --- | --- | --- |
| SSLCOMMERZ | Hosted checkout link, IPN, validation, refunds (needs the bank transaction id; SSLCOMMERZ only accepts refund calls from your registered public IP) | Official docs |
| bKash (tokenized checkout v2) | Create, execute, query, refunds. Token cached with the 2-grants-per-hour limit in mind. You supply the base URL bKash gave you (sandbox or production) | Official docs |
| aamarPay | Hosted checkout and transaction check. **No refund API**: refunds are recorded by hand | Official docs |
| Steadfast | Books one parcel per order, tracking, webhook | **Docs could not be verified.** Test with a single real parcel first |

The money rules, the same for every gateway: a redirect or webhook is never believed on its own; Dakbox asks the provider server to server, and only marks an order paid when the transaction id, amount and currency all match.
Settling is idempotent (an IPN and a redirect arriving together pay once), a second payment for a paid order is flagged for a person, refunds cannot be double-clicked or exceed what was paid, and a refund whose outcome is unknown is left *pending* to check, not retried.
Cash on delivery needs no setup: a courier booking shows the exact amount to collect and asks for confirmation, and the order is marked paid when the courier reports delivery (checked with the courier, not taken from the webhook).

**Try it with no accounts** using the stand-in (it enforces the documented request shapes and serves fake checkout pages):
```bash
cd backend && .venv/bin/uvicorn tools.fake_providers_server:app --port 4011
printf 'SSLCOMMERZ_BASE=http://127.0.0.1:4011\nBKASH_BASE=http://127.0.0.1:4011\nAAMARPAY_BASE=http://127.0.0.1:4011\nSTEADFAST_BASE=http://127.0.0.1:4011\n' >> .env   # delete these lines for real providers
# SSLCommerz teststore / testpass@ssl, aamarPay aamarpaytest / testkey, Steadfast sfkey / sfsecret, bKash merchant / pw / appkey / appsecret
curl -X POST localhost:4011/_fake/steadfast/1424001/delivered     # pretend the courier delivered a parcel, then press Refresh tracking
```
Without those variables the hosts are locked to the providers' real domains.

**Not built:** Pathao, RedX, Paperfly, eCourier and Nagad (their API documentation could not be read; guessing at endpoints that book parcels or take money is not safe), partial-refund tracking beyond the total, and courier charge quotes from the courier (flat charges you enter are used).

## Sign-in and roles

| Role | Can do |
| --- | --- |
| **Owner** | Everything, including adding and changing other owners. There is always at least one active owner. |
| **Admin** | Everything except changing owners: approve returns and refunds, settings, connections, the team. |
| **Agent** | Works the inbox and orders (reply, take over, approve the assistant's drafts, book couriers, adjust stock). Cannot decide Approvals, refund, change settings or manage the team. |
| **Viewer** | Read-only. |

- Passwords: scrypt, 10+ characters, common ones refused. Sessions are random tokens stored hashed, valid 7 days, revoked on sign-out, password change and deactivation.
- Five wrong passwords lock that email and IP for 15 minutes; the error is the same for unknown emails.
- People you invite get a temporary password and **must choose their own** at first sign-in. Owners and admins can reset a password (which signs that person out everywhere).
- Every sign-in, approval, refund, role change and settings change is in **Team, Recent activity**. Messages are signed with the real person's name.
- Roles are enforced on the server for every route. The app also hides or disables what a role cannot do.
- Webhooks and `/widget` stay public (Meta requests are verified by signature; the widget only ever sees its own chat). Only owners and admins can connect or change channels.

For production: serve over HTTPS, set `DAKBOX_ENV=production` (hides `/api/docs`, restricts CORS, refuses unsigned webhooks), and put the backend behind a reverse proxy.
The web app keeps the session token in the browser's local storage, so keep the site free of third-party scripts. There is no email, so "forgot password" means an owner or admin resets it.

## How the assistant stays safe

- **Facts come from tools**, never memory: catalog, live stock, orders, delivery rates, store policies (editable in *Assistant, Knowledge*).
- **Order details are private**: the customer must match the phone on the order (WhatsApp number, or the last 4 digits).
- **It cannot approve money**: refunds, returns, exchanges and price matches become **Approvals** for a person. It never promises an outcome.
- **Review mode**: the assistant drafts, side-effect tools are *staged*, and nothing changes until a person presses *Approve and send*.
- **Handoff** on anger, legal words, a request for a person, or two failed turns. The assistant stops replying once a person takes over.
- **No PINs, OTPs or card numbers**; customer text and tool output are treated as untrusted data in the prompt.
- WhatsApp's 24-hour window is enforced: after it closes only an approved template can be sent.

Tests: `cd backend && .venv/bin/python -m pytest` (174 checks: orders placed in chat, assistant rules, sign-in and roles, every Meta request and webhook shape, channel setup, payment settling and refund safety, courier booking and tracking, order SMS).

## Design

One file, `app/lib/brand/theme.dart`: ink navigation, **Dak Blue** `#3558FA`, saffron for everything the assistant does, floating rounded panels,
light and dark. Type: Bricolage Grotesque (headings), Figtree (UI), Hind Siliguri (Bangla, taller line height), JetBrains Mono (ids).
Responsive: sidebar, rail and bottom bar. Fonts load from Google Fonts on first launch; the splash waits for them.
Icons are Phosphor, via `lib/brand/icons.dart` (the package's Dart classes don't compile on the newest Flutter, its fonts do).

## Not built yet

Single-sign-on / two-factor / password-reset email, keyed (private) store APIs and pushing Dakbox order changes back to the shop, the corporate SMS gateways that publish no docs, the couriers and gateways listed above as not built,
file and image attachments, push notifications, real-time push (the app polls every ~2 s; `/api/events` streams server-sent events for when you want it),
Postgres/migrations (SQLite file `backend/dakbox.db`), Flutter widget tests.
