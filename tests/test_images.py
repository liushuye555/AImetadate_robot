import struct
import zlib

from qq_onebot_whitelist.image_meta import parse_image_metadata
from qq_onebot_whitelist.image_policy import should_keep_image


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + kind + payload + b'\x00\x00\x00\x00'


def make_png(chunks):
    ihdr = struct.pack('>IIBBBBB', 920, 1536, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr) + b''.join(chunks) + png_chunk(b'IEND', b'')


def test_parse_png_detects_comfyui_ztxt_without_decoding_pixels(tmp_path):
    payload = b'prompt\x00' + zlib.compress(b'{"class_type":"KSampler","inputs":{"ckpt_name":"model.safetensors"}}')
    path = tmp_path / 'ai.png'
    path.write_bytes(make_png([png_chunk(b'zTXt', payload)]))

    meta = parse_image_metadata(path)

    assert meta.format == 'PNG'
    assert meta.width == 920
    assert meta.height == 1536
    assert meta.has_ai_metadata is True
    assert meta.ai_source == 'ComfyUI'
    assert 'prompt' in meta.metadata_keys


def test_plain_png_is_not_kept(tmp_path):
    path = tmp_path / 'plain.png'
    path.write_bytes(make_png([]))
    meta = parse_image_metadata(path)

    keep, reason = should_keep_image(meta)

    assert keep is False
    assert reason == 'no_ai_metadata'


def test_ai_png_is_kept(tmp_path):
    payload = b'workflow\x00' + zlib.compress(b'{"nodes":[{"class_type":"KSampler"}]}')
    path = tmp_path / 'ai.png'
    path.write_bytes(make_png([png_chunk(b'zTXt', payload)]))
    meta = parse_image_metadata(path)

    keep, reason = should_keep_image(meta)

    assert keep is True
    assert reason == 'ai_metadata'
