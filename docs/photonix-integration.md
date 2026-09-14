# Integrating PKCS#11 e-signing into Photonix — handover notes

**Audience:** the Claude agent (or engineer) working on Photonix.
**Source:** this repo (`esign-invoices`), a working PySide6 desktop app that
batch-signs PDF invoices with a physical PKCS#11 USB token (Gemalto tested)
and emails them. The goal below is to make the same signing capability
available to traders from a Photonix **web** page, backed by Photonix's own
server DB, instead of shipping them a separate desktop app.

## The one hard constraint

A browser tab cannot talk PKCS#11 to a USB token. There is no DOM/JS API for
it, and WebUSB only exposes raw USB transfers - not something that can drive
a vendor's smart-card middleware (`.dll` / `.dylib` / `.so`). This is true
regardless of framework, so "100% web, nothing installed on the trader's
machine" is not achievable while the private key lives on a physical token
that must stay with the trader.

The workaround every e-signature portal uses (government portals, bank
portals, etc.): keep a **small local helper process** on the trader's
machine that owns the PKCS#11 conversation, and expose it to the web page
over `localhost`. Everything else - invoice/job list, status, history,
customer data - moves into Photonix's web UI and server DB as normal.

## Component split

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│   Photonix web app           │        │  Trader's machine             │
│   (server + browser UI)      │        │                                │
│                               │  HTTPS │  ┌──────────────────────────┐ │
│  - invoice/job queue          │◄──────►│  │ Photonix browser tab      │ │
│  - status, history, DB        │        │  └────────────┬─────────────┘ │
│  - customer/email data        │        │               │ localhost API │
│  - triggers "sign job N"      │        │               ▼               │
│  - stores/serves signed PDFs  │        │  ┌──────────────────────────┐ │
└───────────────────────────────┘        │  │ Local Signing Agent      │ │
                                          │  │ (this repo's core, minus │ │
                                          │  │  the PySide6 GUI)        │ │
                                          │  │  - PKCS#11 session       │ │
                                          │  │  - PIN prompt (native)   │ │
                                          │  │  - PDF signing/stamping  │ │
                                          │  └──────────────────────────┘ │
                                          │               │                │
                                          │        USB token (Gemalto)     │
                                          └────────────────────────────────┘
```

Photonix's server never touches the private key or the PIN. It only ever
sees: a request to sign document X, and later either the signed PDF bytes
or a signed status + the file, uploaded from the trader's browser (which got
them from the local agent).

## What moves into Photonix (web/server side)

Straight port, no PKCS#11 involved - this is normal web app work:

- Invoice/job listing, matching, status tracking → replaces
  `app/matcher.py`, `app/pipeline.py`, `app/runlog.py`'s role, but backed by
  Photonix's real DB instead of the local SQLite files
  (`data/customers.db`, `data/runlog.db`) this desktop app uses today.
- Customer directory (`app/customers.py`) → presumably already exists in
  Photonix's DB; this app's CSV-import/conflict-resolution logic
  (`app/gui/import_dialog.py`) is only relevant if Photonix doesn't already
  have that data.
- Email sending (`app/mailer.py`, Gmail SMTP + App Password) → likely
  replaced by whatever Photonix already uses to notify/email traders or
  customers, unless that's genuinely a new capability for Photonix.
- The visible signature stamp's *position/appearance settings*
  (`sig_x_pct`, `sig_y_pct`, stamp text template, watermark image -
  `app/config.py`, rendered by `render_stamp_image()` in `app/signer.py`)
  are per-trader/per-invoice-template config that belongs in Photonix's DB,
  not a local file - but the actual *rendering* still has to happen
  wherever the PDF gets signed (see below).

## The Local Signing Agent (new, small, replaces the GUI)

This is essentially `app/signer.py`'s non-GUI logic, repackaged as a tiny
background service instead of a PySide6 app:

**Reuse directly (already hardware-tested, including the Gemalto fix):**
- `pkcs11_signing_session()`, `list_pkcs11_tokens()`, `TokenSlotInfo` in
  `app/signer.py` - the whole PKCS#11 session/key-lookup logic.
- `render_stamp_image()` / the visible-stamp compositing logic in
  `app/signer.py` - signing "bare" (invisible signature only) is rarely
  what's wanted for invoices; keep the visible stamp step.
- The actual PDF signing call via pyHanko (`PdfSignatureMetadata`, the
  `signers` module usage in `app/signer.py`).

**Drop:** everything under `app/gui/` (PySide6 tabs, dialogs, the settings
screen's Qt widgets) - none of it is needed once configuration and the job
queue live in Photonix's web UI.

**Add:**
1. A minimal local HTTP (or WebSocket) server bound to `127.0.0.1` on a
   fixed port, e.g.:
   - `GET  /health` → agent is running, driver path configured, token
     present or not.
   - `GET  /tokens` → wraps `list_pkcs11_tokens()`, returns slot/cert
     label+ID choices for a one-time setup step (analogous to today's
     "Скенирај токени" button).
   - `POST /sign` → body: the PDF (or a URL/blob the agent fetches from
     Photonix), the driver path + slot/cert_id to use, stamp
     text/position, PIN. Response: signed PDF bytes (or an error string
     - reuse pyHanko's `SigningError` messages, they're already
     human-readable, e.g. the two label/ID bugs fixed in this repo's
     `git log`).
   - The PIN is passed once per browser session/prompt and **never
     persisted to disk**, matching this app's existing behavior
     (`app/config.py`'s docstring is explicit about this) - keep that
     invariant in the agent.
2. A tiny native PIN-entry prompt (a native OS dialog, not a web page,
   so the PIN never transits through the browser/DOM/JS at all - only the
   local agent process sees it) - unless product requirements are fine
   with the PIN going browser → localhost agent over plain loopback HTTP,
   in which case the web page's own "enter PIN" field can POST it directly
   to `/sign` and skip a native dialog. That's a product decision, not a
   technical blocker either way; note it for whoever owns this.
3. Packaging as a lightweight background app that starts at login (a tray
   icon showing "token connected / not connected" is a nice-to-have, not
   required). This repo's `build.spec` / `build.sh` / `build.bat`
   (PyInstaller) already show a working "single native executable, no
   Python install required for the end user" packaging path per OS - the
   agent can reuse that packaging setup almost unchanged, just with a
   different entry point (`app/main.py`'s PySide6 window swapped for the
   HTTP server + tray icon).

## Browser ↔ localhost gotchas to plan for

- **Mixed content**: Photonix's web app is presumably served over HTTPS.
  An HTTPS page calling `http://localhost:PORT` is blocked as mixed
  content by some browsers/some versions (Chrome has been loosening this
  for loopback addresses, Firefox/Safari are stricter). Plan for either:
  a self-signed/mkcert TLS cert on the local agent (`https://127.0.0.1:PORT`,
  which needs a one-time trust step per machine), or confirm the target
  browsers/versions actually allow the HTTPS→loopback-HTTP exception
  before relying on it.
- **CORS**: the local agent must set `Access-Control-Allow-Origin` to
  Photonix's exact origin (not `*`), so a malicious page elsewhere can't
  also talk to a trader's signing agent while it happens to be running.
- **Port choice**: pick a fixed, documented port and handle "already in
  use" (agent already running) gracefully - the health check endpoint is
  what the web page polls to detect the agent is/isn't installed and
  running before showing the "Sign" button.

## Known gotchas already solved here - don't rediscover them

- **Gemalto/SafeNet key lookup**: pyHanko finds the private key by
  `CKA_LABEL`, defaulting the key label to the certificate's label if
  nothing else is given. On this Gemalto token, the private key's label
  differs from its certificate's label - only `CKA_ID` matches between
  the two. The fix needed **both** `cert_id` *and* `key_id` passed to
  `PKCS11SignatureConfig` (passing only `cert_id` still silently
  backfills a label-based query that fails) - see `app/signer.py`'s
  `pkcs11_signing_session()` and the two fix commits in this repo's
  history for the full trace of why. Carry this over verbatim.
- **Driver file extension is OS-specific**: `.dll` (Windows), `.dylib` or
  `.so` (macOS) - `app/gui/settings_tab.py`'s `DRIVER_FILE_FILTER` shows
  the platform check; the label text bug (always saying `.dll`
  regardless of OS) is a separate, still-open cosmetic issue worth fixing
  wherever this becomes user-facing text again.
- **One PIN entry per batch, not per document**: `pkcs11_signing_session`
  opens one token session and reuses it for every document signed in that
  call - don't re-prompt for a PIN per invoice if a trader is signing
  several from Photonix in one sitting.
- **Cyrillic stamp rendering**: the visible signature stamp is rendered as
  a Pillow image and embedded, not laid out via pyHanko's native text -
  embedding a Cyrillic font directly into the PDF's text layer produced
  spacing bugs (reproduced in two independent renderers). If Photonix's
  traders also need Cyrillic (or other non-Latin) text in the stamp, keep
  rendering it as an image rather than switching back to native PDF text.

## Suggested rollout phases

1. Extract `app/signer.py`'s non-GUI logic (plus its pyHanko/PIL/tzlocal
   dependencies) into a standalone package, unit-tested exactly as today
   (`tests/test_signer.py` and friends already cover the pure-logic
   parts).
2. Wrap it in the local HTTP agent + packaging described above; smoke-test
   it standalone (curl/Postman against `/tokens` and `/sign`) with the
   real Gemalto token before any Photonix UI work starts.
3. Build the Photonix web page: job queue + a "Sign" action that checks
   `/health`, prompts for PIN, calls `/sign`, uploads the result, updates
   Photonix's DB.
4. Pilot with one trader/machine before wider rollout - the PKCS#11 path
   is the one part of this whole system that can only be verified against
   a real, present token, not in CI.
5. Once traders are migrated, this repo's desktop app can be retired (or
   kept only for whichever back-office signing role doesn't move to
   Photonix).

## Open decisions for the Photonix team/agent to make

- Does the PIN get typed into a Photonix web form (simplest, but the PIN
  then passes through the browser/DOM) or into a native dialog the local
  agent pops up itself (more isolation, more to build)?
- Where does the per-trader driver path / slot / cert_id configuration
  live - a one-time local agent config file (like today's
  `pkcs11_driver_path`/`pkcs11_cert_id` in `app/config.py`), or pushed
  down from Photonix's DB on agent startup?
- Distribution/updates for the local agent binary across all trader
  machines - Photonix's existing update mechanism (if any) vs. a
  standalone installer.
- Does the visible-stamp appearance (position/text/watermark) need to be
  configurable per trader/invoice template in Photonix's UI, or is one
  fixed template enough (today's app makes it configurable per
  install)?
