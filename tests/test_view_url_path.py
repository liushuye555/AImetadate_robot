from qq_onebot_whitelist.build_image_view import url_path


def test_url_path_encodes_hash_in_filename():
    assert url_path('unknown_size/#4302_xxx.jpg') == 'unknown_size/%234302_xxx.jpg'
    assert url_path('竖图/#1 图.png') == '%E7%AB%96%E5%9B%BE/%231%20%E5%9B%BE.png'
