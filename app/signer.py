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

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Iterator

import tzlocal
from PIL import Image, ImageDraw, ImageFont
from pyhanko.pdf_utils.images import PdfImage
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.layout import AxisAlignment, InnerScaling, Margins, SimpleBoxLayoutRule
from pyhanko.sign import PdfSignatureMetadata, signers
from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter
from pyhanko.sign.pkcs11 import PKCS11SignatureConfig, PKCS11SigningContext
from pyhanko.sign.signers.pdf_cms import Signer
from pyhanko.stamp import TextStampStyle

DEFAULT_STAMP_TEXT = "%(signer)s\nДигитално потпишано\n%(ts)s"
DEFAULT_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S %Z"  # matches pyHanko's own default

# pyHanko's default stamp font is a base-14 PDF font (Latin-1 only), which
# silently garbles Cyrillic text. Rather than bundle a font (and its
# licensing questions), we point at a Cyrillic-capable font already
# installed on the machine - Windows and macOS both ship one by default.
if sys.platform == "win32":
    _windir = os.environ.get("WINDIR", r"C:\Windows")
    _FONT_CANDIDATES = [
        rf"{_windir}\Fonts\tahoma.ttf",
        rf"{_windir}\Fonts\arial.ttf",
        rf"{_windir}\Fonts\calibri.ttf",
    ]
elif sys.platform == "darwin":
    _FONT_CANDIDATES = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Tahoma.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
else:
    _FONT_CANDIDATES = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]


def find_stamp_font() -> Path | None:
    for candidate in _FONT_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return p
    return None


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
    x_pct: float = 5.0
    y_pct: float = 3.0
    width_pct: float = 60.0
    height_pct: float = 14.0

    # Appearance: the stamp text template (supports %(signer)s and %(ts)s,
    # same convention pyHanko itself uses) and an optional background
    # watermark image shown faintly behind the text - e.g. a company logo
    # or a signature graphic, like Adobe's own default appearance does.
    stamp_text: str = DEFAULT_STAMP_TEXT
    background_image_path: str = ""
    background_opacity: float = 0.6


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


def _load_measuring_font(font_path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    if font_path is not None:
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _wrap_text_block(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Word-wraps each '\\n'-separated paragraph in `text` so no line
    exceeds `max_width` (in the same units as font.getlength - points, for
    a font loaded at a point size)."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if not current or font.getlength(candidate) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def render_stamp_image(
    template: str,
    signer_name: str,
    box_width_pt: float,
    box_height_pt: float,
    font_path: Path | None,
    background_image_path: str = "",
    background_opacity: float = 0.35,
    max_font_size: int = 13,
    min_font_size: int = 5,
    padding_pt: float = 5.0,
    scale: float = 4.0,
) -> Image.Image:
    """Renders the visible signature stamp - substituted/wrapped/auto-sized
    text, optionally over a background watermark - as a single RGBA image
    sized to the signature box's exact aspect ratio.

    This is done with PIL rather than pyHanko's own text-box layout: with
    an embedded OpenType font (needed for Cyrillic), pyHanko's box-fit
    text layout was found to add erratic extra spacing between glyphs
    (reproduced identically across two independent PDF renderers, so it's
    a real content bug, not a viewer quirk) - rendering the finished stamp
    as one image sidesteps that entirely and gives full, predictable
    control over wrapping and sizing.
    """
    px_w = max(1, round(box_width_pt * scale))
    px_h = max(1, round(box_height_pt * scale))
    canvas = Image.new("RGBA", (px_w, px_h), (255, 255, 255, 0))

    if background_image_path:
        try:
            bg = Image.open(background_image_path).convert("RGBA")
            bg = bg.resize((px_w, px_h))
            alpha = bg.split()[3].point(lambda a: int(a * background_opacity))
            bg.putalpha(alpha)
            canvas.alpha_composite(bg)
        except OSError:
            pass

    ts = datetime.now(tz=tzlocal.get_localzone()).strftime(DEFAULT_TIMESTAMP_FORMAT)
    substituted = template % {"signer": signer_name, "ts": ts}

    usable_w = max(10.0, (box_width_pt - 2 * padding_pt) * scale)
    usable_h = max(10.0, (box_height_pt - 2 * padding_pt) * scale)

    chosen_size = min_font_size
    chosen_lines: list[str] = [substituted]
    for size in range(max_font_size, min_font_size - 1, -1):
        font = _load_measuring_font(font_path, round(size * scale))
        lines = _wrap_text_block(substituted, font, usable_w)
        line_height = size * scale * 1.3
        if len(lines) * line_height <= usable_h:
            chosen_size, chosen_lines = size, lines
            break
    else:
        font = _load_measuring_font(font_path, round(min_font_size * scale))
        chosen_lines = _wrap_text_block(substituted, font, usable_w)

    font = _load_measuring_font(font_path, round(chosen_size * scale))
    line_height = chosen_size * scale * 1.3
    draw = ImageDraw.Draw(canvas)
    y = padding_pt * scale
    for line in chosen_lines:
        draw.text((padding_pt * scale, y), line, font=font, fill=(0, 0, 0, 255))
        y += line_height

    return canvas


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
            stamp_image = render_stamp_image(
                options.stamp_text,
                signer.subject_name,
                box_width_pt=box[2] - box[0],
                box_height_pt=box[3] - box[1],
                font_path=find_stamp_font(),
                background_image_path=options.background_image_path,
                background_opacity=options.background_opacity,
            )
            # STRETCH_FILL: our rendered image already matches the box's
            # exact aspect ratio, so this just places it edge-to-edge
            # inside the stamp's border.
            background_layout = SimpleBoxLayoutRule(
                x_align=AxisAlignment.ALIGN_MID,
                y_align=AxisAlignment.ALIGN_MID,
                margins=Margins(left=0, right=0, top=0, bottom=0),
                inner_content_scaling=InnerScaling.STRETCH_FILL,
            )
            pdf_signer = signers.PdfSigner(
                meta,
                signer=signer,
                stamp_style=TextStampStyle(
                    stamp_text="",
                    background=PdfImage(stamp_image),
                    background_opacity=1.0,
                    background_layout=background_layout,
                ),
                new_field_spec=SigFieldSpec(
                    options.field_name, on_page=0, box=tuple(int(round(v)) for v in box)
                ),
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
    cert_id: str | None = None,
    slot_no: int | None = None,
) -> Iterator[Signer]:
    """Open one PKCS#11 session covering an entire signing batch.

    Usage:
        with pkcs11_signing_session(driver, pin) as signer:
            for pdf in invoices:
                sign_pdf(pdf, out, signer)

    ``cert_id`` (the certificate's CKA_ID, as hex) is preferred over
    ``cert_label`` for locating the matching private key: on many tokens
    (e.g. Gemalto/SafeNet IDPrime) the private key object has a
    different label than its certificate - only the CKA_ID matches
    between the two. It must be passed as both ``cert_id`` *and*
    ``key_id`` here: pyHanko's PKCS11Signer only drops its
    label-based key lookup when the raw ``key_id`` argument itself is
    set - passing ``cert_id`` alone still makes it fall back to
    searching for a private key whose CKA_LABEL equals the
    certificate's label (combined with the ID, as an AND match), which
    fails whenever that label doesn't match. Without either, signing
    fails with "Could not find private key with label ...".
    """
    key_id_bytes = bytes.fromhex(cert_id) if cert_id else None
    config = PKCS11SignatureConfig(
        module_path=str(driver_path),
        cert_label=cert_label,
        cert_id=key_id_bytes,
        key_id=key_id_bytes,
        slot_no=slot_no,
    )
    try:
        with PKCS11SigningContext(config, user_pin=pin) as signer:
            yield signer
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(f"Грешка при поврзување со USB токенот: {exc}") from exc


@dataclass
class TokenSlotInfo:
    """One PKCS#11 slot with a token present, for the Settings screen's
    token-picker dropdown - lets the user select a slot/certificate by
    name instead of having to know a raw numeric slot index."""

    slot_id: int
    token_label: str
    cert_labels: list[str]
    cert_ids: list[str] = field(default_factory=list)  # hex CKA_ID, paired by index with cert_labels

    @property
    def display_name(self) -> str:
        label = self.token_label or f"Слот {self.slot_id}"
        names = [
            cert_label or f"ID {cert_id}"
            for cert_label, cert_id in zip_longest(self.cert_labels, self.cert_ids, fillvalue="")
        ]
        if names:
            return f"{label} — {', '.join(names)}"
        return label


def list_pkcs11_tokens(driver_path: Path) -> list[TokenSlotInfo]:
    """Scans the driver for present tokens/slots and their certificates,
    used by the settings screen's token-picker dropdown. Certificate
    labels are usually readable without a PIN (public objects)."""
    import pkcs11 as pkcs11_lib

    lib = pkcs11_lib.lib(str(driver_path))
    results: list[TokenSlotInfo] = []
    for slot in lib.get_slots(token_present=True):
        token = slot.get_token()
        cert_labels: list[str] = []
        cert_ids: list[str] = []
        try:
            with token.open() as session:
                for obj in session.get_objects(
                    {pkcs11_lib.Attribute.CLASS: pkcs11_lib.ObjectClass.CERTIFICATE}
                ):
                    try:
                        label = obj[pkcs11_lib.Attribute.LABEL]
                    except Exception:
                        label = None
                    try:
                        cert_id = obj[pkcs11_lib.Attribute.ID]
                    except Exception:
                        cert_id = None
                    if not label and not cert_id:
                        continue
                    cert_labels.append(label or "")
                    cert_ids.append(cert_id.hex() if cert_id else "")
        except Exception:
            pass
        results.append(
            TokenSlotInfo(
                slot_id=slot.slot_id,
                token_label=(token.label or "").strip(),
                cert_labels=cert_labels,
                cert_ids=cert_ids,
            )
        )
    return results
