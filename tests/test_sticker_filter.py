from qq_onebot_whitelist.images import is_probable_sticker_result


def test_probable_sticker_result_detects_small_unknown_jpeg_and_gif():
    assert is_probable_sticker_result({'format': 'JPEG', 'size': 52101, 'width': None, 'height': None, 'has_ai_metadata': False})
    assert is_probable_sticker_result({'format': 'GIF', 'size': 30000, 'width': None, 'height': None, 'has_ai_metadata': False})
    assert is_probable_sticker_result({'format': 'JPEG', 'size': 52101, 'width': 640, 'height': 640, 'has_ai_metadata': False})


def test_probable_sticker_result_keeps_real_sized_images_and_ai_metadata():
    assert not is_probable_sticker_result({'format': 'PNG', 'size': 1500000, 'width': 1024, 'height': 1536, 'has_ai_metadata': False})
    assert not is_probable_sticker_result({'format': 'JPEG', 'size': 52101, 'width': None, 'height': None, 'has_ai_metadata': True})
