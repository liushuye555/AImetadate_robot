from pathlib import Path

from qq_onebot_whitelist.image_meta import parse_image_metadata


def test_parse_jpeg_dimensions(tmp_path):
    # minimal JPEG with SOF0 marker: width=320, height=240
    data = (
        b'\xff\xd8'
        b'\xff\xe0\x00\x04xx'
        b'\xff\xc0\x00\x11\x08\x00\xf0\x01\x40\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00'
        b'\xff\xd9'
    )
    path = tmp_path / 'x.jpg'
    path.write_bytes(data)
    meta = parse_image_metadata(path)
    assert meta.format == 'JPEG'
    assert meta.width == 320
    assert meta.height == 240
