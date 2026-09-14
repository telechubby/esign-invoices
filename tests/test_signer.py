from app.signer import SignatureOptions, compute_signature_box


def test_compute_signature_box_basic():
    options = SignatureOptions(x_pct=70, y_pct=3, width_pct=25, height_pct=8)
    x1, y1, x2, y2 = compute_signature_box(page_width=612, page_height=792, options=options)
    assert x1 == 612 * 0.70
    assert y1 == 792 * 0.03
    assert x2 == x1 + 612 * 0.25
    assert y2 == y1 + 792 * 0.08


def test_compute_signature_box_full_page():
    options = SignatureOptions(x_pct=0, y_pct=0, width_pct=100, height_pct=100)
    box = compute_signature_box(612, 792, options)
    assert box == (0, 0, 612, 792)


def test_compute_signature_box_scales_with_page_size():
    options = SignatureOptions(x_pct=50, y_pct=50, width_pct=10, height_pct=10)
    box_letter = compute_signature_box(612, 792, options)
    box_a4 = compute_signature_box(595, 842, options)
    assert box_letter != box_a4
    assert box_letter[0] == 306  # 50% of 612
    assert box_a4[0] == 297.5  # 50% of 595
