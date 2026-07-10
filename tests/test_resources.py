from qq_onebot_whitelist.resources import classify_file, classify_link, extract_file_segments, extract_resource_links


def test_classify_model_and_archive_files():
    assert classify_file('cute_lora.safetensors') == 'model'
    assert classify_file('workflow_pack.zip') == 'archive'
    assert classify_file('comfy_workflow.json') == 'workflow'
    assert classify_file('notes.txt') == 'other'


def test_extract_file_segments_from_message_file_segment():
    event = {
        'message': [
            {'type': 'file', 'data': {'file': 'model.safetensors', 'name': 'model.safetensors', 'size': '12345', 'url': 'https://example.test/model.safetensors'}},
            {'type': 'text', 'data': {'text': '这个lora'}}
        ]
    }
    files = extract_file_segments(event)
    assert files == [{'file_name': 'model.safetensors', 'file_size': 12345, 'url': 'https://example.test/model.safetensors', 'kind': 'model'}]


def test_classify_links_by_domain_and_context():
    assert classify_link('https://civitai.com/models/123', '这个lora不错') == 'civitai_model'
    assert classify_link('https://github.com/user/repo', 'comfyui节点') == 'github_project'
    assert classify_link('https://pan.baidu.com/s/abc', '模型包') == 'cloud_drive'
    assert classify_link('https://example.com/a', '教程') == 'tutorial_or_reference'
