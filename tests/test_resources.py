from qq_onebot_whitelist.daily_report import canonical_url
from qq_onebot_whitelist.resources import (
    classify_file, classify_link, extract_file_segments, extract_resource_links,
    is_direct_image_link, is_unresolved_short_link, link_category,
)


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


def test_link_organization_prefers_destination_over_nearby_model_words():
    assert link_category('https://www.bilibili.com/video/BV1example', 'ComfyUI 工作流教程') == 'AI教程视频'
    assert link_category('https://www.bilibili.com/video/BV2example', 'MiniMax H3 正式发布') == 'AI资讯视频'
    assert link_category('https://www.bilibili.com/video/BV3example', '日常搞笑视频') == '娱乐视频'
    assert link_category('https://www.bilibili.com/video/BV4example', '原创音乐 MV') == '音乐视频'
    assert link_category('https://linux.do/t/topic/123', '') == '技术社区'
    assert link_category('https://api.example.com', 'AI 中转公益站，注册送额度') == 'AI中转服务'
    assert link_category('https://tensor.art/images/123', '') == 'AI作品展示'
    assert link_category('https://tensor.art', '') == 'AI作品展示'
    assert link_category('https://tensor.art/models/123/example', '') == 'AI模型'
    assert link_category('https://github.com/example/repo', '这是一个模型相关仓库') == 'AI工具插件'
    assert link_category('https://www.runninghub.ai/zh-cn/workflow/123', '') == 'AI工作流'
    assert link_category('https://tusi.cn/models/123', '') == 'AI模型'
    assert link_category('https://www.runninghub.ai/zh-cn/ai-detail/123', '') == 'AI在线服务'
    assert link_category('https://tusi.cn/images/123', '') == '图片'
    assert link_category('https://docs.comfy.org/tutorials/first-workflow', '') == '教程'
    assert link_category('https://comfy.org/zh-CN/download', '') == 'AI工具插件'
    assert link_category('https://www.phoronix.com/news/FFmpeg-9.0-Released', '') == '新闻'


def test_link_organization_hides_unresolved_xiaohongshu_short_links_and_merges_root_urls():
    assert is_unresolved_short_link('https://xhslink.cn/abc')
    assert canonical_url('https://api.example.com/') == 'https://api.example.com'
    assert is_direct_image_link('https://postimg.cc/abc123')
