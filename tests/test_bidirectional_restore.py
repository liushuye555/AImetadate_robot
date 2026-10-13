import hashlib

from PIL import Image, PngImagePlugin

from qq_onebot_whitelist.gilbert_obfuscation import (
    analyze_image,
    restore_image,
    safe_restore,
)


WIDTH, HEIGHT = 72, 54


def _make_source(path, *, rgba=False):
    """Deterministic smooth gradient with subtle texture; contains no user imagery."""
    mode = 'RGBA' if rgba else 'RGB'
    pixels = []
    for y in range(HEIGHT):
        for x in range(WIDTH):
            texture = ((x * 17 + y * 29 + x * y * 3) % 7) - 3
            red = max(0, min(255, 30 + 2 * x + texture))
            green = max(0, min(255, 35 + 3 * y - texture))
            blue = max(0, min(255, 25 + x + y + texture))
            if rgba:
                alpha = (x * 11 + y * 7) % 256
                pixels.append((red, green, blue, alpha))
            else:
                pixels.append((red, green, blue))
    image = Image.new(mode, (WIDTH, HEIGHT))
    image.putdata(pixels)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Prompt', 'soft gradient study')
    metadata.add_text('Software', 'Synthetic regression fixture')
    image.save(path, pnginfo=metadata)
    return image


def _make_obfuscated(source_path, output_path, source_direction, layers):
    # restore_image applies the inverse operation for the requested direction.
    # Applying the opposite operation constructs the corresponding scrambled input.
    construction_direction = 'encode' if source_direction == 'decode' else 'decode'
    restore_image(source_path, output_path, layers=layers, direction=construction_direction)


def _assert_same_pixels(expected_path, actual_path):
    with Image.open(expected_path) as expected, Image.open(actual_path) as actual:
        assert actual.mode == expected.mode
        assert actual.size == expected.size
        assert actual.tobytes() == expected.tobytes()


def test_auto_detects_and_restores_both_directions_and_one_to_three_layers(tmp_path):
    source = tmp_path / 'source.png'
    _make_source(source)

    for source_direction in ('decode', 'encode'):
        for layers in (1, 2, 3):
            scrambled = tmp_path / f'{source_direction}-{layers}.png'
            restored = tmp_path / f'restored-{source_direction}-{layers}.png'
            _make_obfuscated(source, scrambled, source_direction, layers)

            detected = analyze_image(scrambled)
            assert detected is not None
            assert detected['obfuscated'] is True
            assert detected['confidence'] == 'confirmed'
            assert detected['direction'] == source_direction
            assert detected['layers'] == layers
            assert set(detected['direction_ratios']) == {'decode', 'encode'}

            restored_path, used_layers = restore_image(scrambled, restored)
            assert restored_path == restored
            assert used_layers == layers
            _assert_same_pixels(source, restored)


def test_rgba_restore_preserves_alpha_and_png_text_metadata(tmp_path):
    source = tmp_path / 'rgba-source.png'
    _make_source(source, rgba=True)
    scrambled = tmp_path / 'rgba-scrambled.png'
    restored = tmp_path / 'rgba-restored.png'
    _make_obfuscated(source, scrambled, 'encode', 2)

    restore_image(scrambled, restored)

    _assert_same_pixels(source, restored)
    with Image.open(scrambled) as before, Image.open(restored) as after:
        assert after.info['Prompt'] == before.info['Prompt'] == 'soft gradient study'
        assert after.info['Software'] == before.info['Software'] == 'Synthetic regression fixture'


def test_wrong_direction_safe_restore_keeps_original_and_does_not_archive(tmp_path):
    source = tmp_path / 'source.png'
    _make_source(source)
    scrambled = tmp_path / 'original.png'
    _make_obfuscated(source, scrambled, 'decode', 1)
    original_bytes = scrambled.read_bytes()
    digest = hashlib.sha256(original_bytes).hexdigest()
    archive = tmp_path / 'images' / 'ai'

    result = safe_restore(
        scrambled,
        tmp_path / 'tmp' / 'wrong-direction.png',
        archive,
        digest,
        layers=1,
        direction='encode',
    )

    assert result is None
    assert scrambled.read_bytes() == original_bytes
    assert not (archive / digest[:2] / f'{digest}.png').exists()
    assert not (archive.parent / 'obfuscation-originals' / digest[:2] / f'{digest}.png').exists()


def test_successful_safe_restore_backs_up_original_and_promotes_exact_pixels(tmp_path):
    source = tmp_path / 'source.png'
    _make_source(source)
    scrambled = tmp_path / 'obfuscated.png'
    _make_obfuscated(source, scrambled, 'encode', 3)
    original_bytes = scrambled.read_bytes()
    digest = hashlib.sha256(original_bytes).hexdigest()
    archive = tmp_path / 'images' / 'ai'

    promoted = safe_restore(
        scrambled,
        tmp_path / 'tmp' / 'verified.png',
        archive,
        digest,
        layers=3,
        direction='encode',
    )

    expected_path = archive / digest[:2] / f'{digest}.png'
    backup_path = archive.parent / 'obfuscation-originals' / digest[:2] / f'{digest}.png'
    assert promoted == expected_path
    assert backup_path.read_bytes() == original_bytes
    _assert_same_pixels(source, promoted)
    assert not scrambled.exists()
