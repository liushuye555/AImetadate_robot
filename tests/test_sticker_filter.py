from qq_onebot_whitelist.images import is_probable_sticker_result
from qq_onebot_whitelist.images import is_junk_image


def test_probable_sticker_result_detects_small_unknown_jpeg_and_gif():
    assert is_probable_sticker_result({'format': 'JPEG', 'size': 52101, 'width': None, 'height': None, 'has_ai_metadata': False})
    assert is_probable_sticker_result({'format': 'GIF', 'size': 30000, 'width': None, 'height': None, 'has_ai_metadata': False})
    assert is_probable_sticker_result({'format': 'JPEG', 'size': 52101, 'width': 640, 'height': 640, 'has_ai_metadata': False})


def test_probable_sticker_result_keeps_real_sized_images_and_ai_metadata():
    assert not is_probable_sticker_result({'format': 'PNG', 'size': 1500000, 'width': 1024, 'height': 1536, 'has_ai_metadata': False})
    assert not is_probable_sticker_result({'format': 'JPEG', 'size': 52101, 'width': None, 'height': None, 'has_ai_metadata': True})


def test_is_junk_image_detects_stickers_and_extreme_strips():
    assert is_junk_image({'format': 'GIF', 'size': 30000, 'width': None, 'height': None, 'has_ai_metadata': False})
    # 超宽截图条（3.1:1，非表情包尺寸）
    assert is_junk_image({'format': 'PNG', 'size': 500000, 'width': 3683, 'height': 1190, 'has_ai_metadata': False})
    # 正常竖图不算 junk
    assert not is_junk_image({'format': 'PNG', 'size': 1500000, 'width': 1024, 'height': 1536, 'has_ai_metadata': False})
    # 带 AI 元数据不参与 junk 判定
    assert not is_junk_image({'format': 'PNG', 'size': 500000, 'width': 3683, 'height': 1190, 'has_ai_metadata': True})
