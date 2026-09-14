# Потпишување и испраќање фактури (Esign Invoices)

Desktop tool (Macedonian-language GUI) that batch-signs PDF invoices with a
physical USB PKCS#11 token and emails each one to its customer. Runs on
Windows and macOS (same codebase).

## How it works

1. **Клиенти (Customers)** tab: a local list of company ID → email (+ name),
   stored in `data/customers.db` next to the program. Import once from a CSV
   export of your DB, then edit by hand from here on. Re-importing a CSV
   flags any ID whose email changed as a conflict for you to resolve (keep
   existing / use new) instead of silently overwriting; brand-new IDs are
   listed separately before you commit the import.
2. **Поставки (Settings)** tab: folders, the invoice filename pattern (which
   part of the filename is the customer ID), the USB token's PKCS#11 driver
   path, and the Gmail sending address/App Password.
3. **Потпишување и испраќање (Run)** tab: scans the unsigned-invoices
   folder and matches each file to a customer. Signing and sending are two
   separate, independent steps - not one combined action:
   - **"Потпиши ги сите"** opens one PKCS#11 session (one PIN entry covers
     the whole batch) and signs every matched invoice into the signed
     folder. Nothing is emailed yet.
   - Use **"Отвори папка со потпишани"** to look over the signed PDFs
     before anything goes out - this is the point of the split: someone
     can review the actual signed invoices first.
   - **"Испрати ги сите потпишани"** emails every invoice that's been
     signed but not yet sent. This doesn't need the token at all, and can
     be run later or in a different app session than the signing step -
     a scan always picks up previously-signed-but-unsent invoices as ready
     to send.

A local `data/runlog.db` records what has already been signed/sent, so
re-running the tool (after a crash, a cancel, or by accident) never
re-signs or double-emails an invoice that already went out.

## Setup on Windows

1. Install Python 3.11+ from python.org (check "Add to PATH" during install).
2. Install the USB token vendor's PKCS#11 driver (the `.dll` that came with
   the token, or from the CA's website). Note where it installs - you'll
   point Settings at it.
3. Open a terminal in this folder and run `build.bat`. This creates a
   virtualenv, installs dependencies, runs the test suite, and builds
   `dist\EsignInvoices\EsignInvoices.exe`.
   - To just run from source without building an .exe yet (faster while
     testing), use `run.bat` instead.
4. Launch the app and follow **First run**, below.

## Setup on macOS

1. Install Python 3.11+ (`brew install python@3.11` or from python.org).
2. Install the USB token vendor's PKCS#11 driver for macOS (a `.dylib`,
   sometimes shipped as a `.so`). Note its path.
3. Open Terminal in this folder and run `./build.sh`. This creates a
   virtualenv, installs dependencies, runs the test suite, and builds
   `dist/EsignInvoices.app`.
   - To just run from source (faster while testing), use `./run.sh` instead.
4. Launch the app and follow **First run**, below.
   - First launch may need Right-click → Open (or System Settings →
     Privacy & Security → "Open Anyway") since the app isn't notarized.

## First run

In **Поставки**:
- Set the unsigned/signed invoice folders.
- Check the filename pattern against your real invoice filenames (the
  example line updates live).
- Browse to the token driver. Click "Прикажи сертификати" to confirm the
  app can see the token (plug it in first).
- Enter your Gmail address and an **App Password** (not your normal Gmail
  password): on myaccount.google.com, turn on 2-Step Verification, then
  generate an App Password under Security → App passwords.
- Save.

In **Клиенти**, import your customer CSV (ID + Email columns, name
optional) to seed the list.

In **Потпишување и испраќање**: "Провери фактури" to scan, check the
matches look right, "Потпиши ги сите" (enter the token PIN once), review
the signed PDFs, then "Испрати ги сите потпишани" whenever you're ready.

**Recommendation: test with 2-3 real invoices before running all 500** -
verify the signature and the received email both look correct.

## Development

```
python3 -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
pytest tests -q
python -m app.main
```

Core logic (`app/customers.py`, `app/matcher.py`, `app/pipeline.py`,
`app/runlog.py`, `app/config.py`) is plain Python with no GUI or hardware
dependency and is fully unit-tested (33 tests). `app/signer.py` (pyHanko)
and `app/mailer.py` (SMTP) can also be exercised without the real
token/Gmail using a throwaway PKCS12 test certificate - see the signing
flow tested during development. The full GUI has also been smoke-tested
(headless and live) on macOS.

`app/signer.py`'s PKCS#11 path (`pkcs11_signing_session`,
`list_pkcs11_certificates`) can only be verified against the real token -
that's the one part that needs testing on-site, on whichever machine (Windows
or macOS) actually has the token plugged in.
