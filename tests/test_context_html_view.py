def test_context_image_cards_mask_deobfuscated():
    from qq_onebot_whitelist.context_view import _image_cards
    items = [
        {"id": "1", "image_rel": "a.png", "meta": "m", "deobfuscated": True, "text_excerpt": ""},
        {"id": "2", "image_rel": "b.png", "meta": "m", "deobfuscated": False, "text_excerpt": ""},
    ]
    html = _image_cards(items, "x/")
    assert "masked" in html or "blur" in html
    assert "x/a.png" in html and "x/b.png" in html
