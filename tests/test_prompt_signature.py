"""同批签名：完整工作流哈希（模型/参数不同 → 不同批）。"""

import hashlib
import json

from PIL import Image, PngImagePlugin

from qq_onebot_whitelist.image_meta import extract_prompt_signature


def _png_with_graph(path, unet):
    graph = {
        "3": {"inputs": {"text": "1girl, white hair"}, "class_type": "CLIPTextEncode"},
        "348": {"inputs": {"unet_name": unet}, "class_type": "UNETLoader"},
    }
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", json.dumps(graph))
    Image.new("RGB", (8, 8)).save(path, pnginfo=info)


def test_signature_identical_workflow_same_key(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _png_with_graph(a, "model.safetensors")
    _png_with_graph(b, "model.safetensors")
    assert extract_prompt_signature(a) == extract_prompt_signature(b)


def test_signature_differs_when_model_changes_even_same_prompt(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _png_with_graph(a, "waiANIMA_v10.safetensors")
    _png_with_graph(b, "JANIMA_v10.safetensors")
    ka, kb = extract_prompt_signature(a), extract_prompt_signature(b)
    assert ka and kb and ka != kb
    expected = hashlib.sha1(
        json.dumps(
            {
                "3": {"inputs": {"text": "1girl, white hair"}, "class_type": "CLIPTextEncode"},
                "348": {"inputs": {"unet_name": "waiANIMA_v10.safetensors"}, "class_type": "UNETLoader"},
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:16]
    assert ka == expected


def test_signature_none_without_graph_metadata(tmp_path):
    png = tmp_path / "plain.png"
    Image.new("RGB", (8, 8)).save(png)
    assert extract_prompt_signature(png) is None
