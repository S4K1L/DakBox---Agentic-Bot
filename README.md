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
| Assistant with Claude (tool use) | Real **when `ANTHROPIC_API_KEY` is set** (`backend/.env`). Not run in this build: there was no key. |
| Assistant without a key | A rule engine that calls the same tools under the same safety rules. Used for every test so far. |
| WhatsApp Cloud API, Messenger, Instagram | Built to Meta's published docs (checked Nov 2026) and tested against a stand-in for Meta's API (`backend/tools`). **Not yet run against Meta itself**: that needs your Meta app, reviewed permissions and tokens. See *Connect Meta* for what to expect and how to verify. |
| Web chat widget (`/widget`) | Real, works end to end. |
| SSLCommerz, bKash, aamarPay, Steadfast | Built (see *Connect couriers and payments*) and tested against stand-ins. **Never run against the real services.** Until a provider is connected, shipping gives a labelled demo parcel and payment links are unavailable. |
| SSL Wireless (ISMS Plus), Alpha SMS | Order SMS built to their public API pages (see *Order SMS*) and tested against stand-ins. **Never run against the real services.** With none connected, order messages show as "Not sent". |
| WooCommerce, Shopify, Grameenphone/Robi/Banglalink corporate SMS, Pathao, RedX, Paperfly, eCourier, Nagad | Cards and toggles only, or marked not built. No provider API is called. |
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

Single-sign-on / two-factor / password-reset email, store-platform (WooCommerce, Shopify) APIs, the corporate SMS gateways that publish no docs, the couriers and gateways listed above as not built, creating orders in chat,
file and image attachments, push notifications, real-time push (the app polls every ~2 s; `/api/events` streams server-sent events for when you want it),
Postgres/migrations (SQLite file `backend/dakbox.db`), Flutter widget tests.
