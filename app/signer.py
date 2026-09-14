"""PDF digital signing via pyHanko.

Two signer sources are supported behind the same signing call:

- PKCS#12 (.p12/.pfx file) - used for local testing without the physical
  token (e.g. the throwaway test certificate).
- PKCS#11 (the real USB token) - used in production. A single PIN entry
  opens a session that is reused for the whole batch, so the user is not
  prompted per invoice (unless the token itself forces re-authentication
  per signature, which pyHanko also supports via PKCS11SigningPinEntryMode).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import PdfSignatureMetadata, signers
from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter
from pyhanko.sign.pkcs11 import PKCS11SignatureConfig, PKCS11SigningContext
from pyhanko.sign.signers.pdf_cms import Signer
from pyhanko.stamp import TextStampStyle


class SigningError(Exception):
    pass


@dataclass
class SignatureOptions:
    reason: str = ""
    location: str = ""
    field_name: str = "Signature1"

    # Where the visible signature stamp goes on the first page, as
    # percentages of the page's width/height (PDF convention: y measured
    # from the BOTTOM of the page). Percentages are used rather than
    # absolute points because they work regardless of the actual page
    # size, which can vary between invoices.
    x_pct: float = 65.0
    y_pct: float = 5.0
    width_pct: float = 30.0
    height_pct: float = 12.0


def compute_signature_box(
    page_width: float,
    page_height: float,
    options: SignatureOptions,
) -> tuple[float, float, float, float]:
    """Converts the configured percentage-based position/size into an
    absolute (x1, y1, x2, y2) box in PDF points for this page's size."""
    x1 = options.x_pct / 100 * page_width
    y1 = options.y_pct / 100 * page_height
    x2 = x1 + options.width_pct / 100 * page_width
    y2 = y1 + options.height_pct / 100 * page_height
    return x1, y1, x2, y2


def sign_pdf(
    input_path: Path,
    output_path: Path,
    signer: Signer,
    options: SignatureOptions | None = None,
) -> None:
    """Sign a single PDF with an already-constructed pyHanko Signer.

    The signature is always made visible on the first page, at the
    position/size configured in `options` - so someone opening the PDF sees
    a signature stamp, not just an invisible cryptographic signature.
    """
    options = options or SignatureOptions()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(input_path, "rb") as inf:
            # strict=False: real-world invoice PDFs (e.g. from LibreOffice/
            # reporting tools) often use hybrid cross-reference sections,
            # which pyHanko's strict mode refuses to sign.
            writer = IncrementalPdfFileWriter(inf, strict=False)

            first_page = writer.root["/Pages"]["/Kids"][0].get_object()
            px0, py0, px1, py1 = (float(v) for v in first_page["/MediaBox"])
            box = compute_signature_box(px1 - px0, py1 - py0, options)

            meta = PdfSignatureMetadata(
                field_name=options.field_name,
                reason=options.reason or None,
                location=options.location or None,
                subfilter=SigSeedSubFilter.PADES,
                md_algorithm="sha256",
            )
            pdf_signer = signers.PdfSigner(
                meta,
                signer=signer,
                stamp_style=TextStampStyle(background=None),
                new_field_spec=SigFieldSpec(options.field_name, on_page=0, box=box),
            )

            with open(output_path, "wb") as outf:
                pdf_signer.sign_pdf(writer, output=outf)
    except Exception as exc:  # pyHanko raises various exception types
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise SigningError(str(exc)) from exc


# -- PKCS#12 (testing) ---------------------------------------------------


def load_pkcs12_signer(p12_path: Path, password: str) -> Signer:
    try:
        return signers.SimpleSigner.load_pkcs12(
            pfx_file=str(p12_path),
            passphrase=password.encode("utf-8"),
        )
    except Exception as exc:
        raise SigningError(f"Не можам да го вчитам сертификатот: {exc}") from exc


# -- PKCS#11 (real USB token) ---------------------------------------------


@contextmanager
def pkcs11_signing_session(
    driver_path: Path,
    pin: str,
    cert_label: str | None = None,
    slot_no: int | None = None,
) -> Iterator[Signer]:
    """Open one PKCS#11 session covering an entire signing batch.

    Usage:
        with pkcs11_signing_session(driver, pin) as signer:
            for pdf in invoices:
                sign_pdf(pdf, out, signer)
    """
    config = PKCS11SignatureConfig(
        module_path=str(driver_path),
        cert_label=cert_label,
        slot_no=slot_no,
    )
    try:
        with PKCS11SigningContext(config, user_pin=pin) as signer:
            yield signer
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(f"Грешка при поврзување со USB токенот: {exc}") from exc


def list_pkcs11_certificates(driver_path: Path) -> list[str]:
    """Best-effort listing of certificate labels available on the token,
    used by the settings screen's "Прикажи сертификати" action. Requires
    no PIN for most tokens (public objects are readable without login)."""
    import pkcs11 as pkcs11_lib

    lib = pkcs11_lib.lib(str(driver_path))
    labels: list[str] = []
    for slot in lib.get_slots(token_present=True):
        token = slot.get_token()
        with token.open() as session:
            for obj in session.get_objects({pkcs11_lib.Attribute.CLASS: pkcs11_lib.ObjectClass.CERTIFICATE}):
                try:
                    label = obj[pkcs11_lib.Attribute.LABEL]
                except Exception:
                    label = None
                if label:
                    labels.append(label)
    return labels
