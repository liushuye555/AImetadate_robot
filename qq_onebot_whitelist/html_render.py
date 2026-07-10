from __future__ import annotations

import html
import re


def _inline(text: str) -> str:
    value = html.escape(text, quote=True)
    value = re.sub(r'`([^`]+)`', r'<code>\1</code>', value)
    value = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2">\1</a>', value)
    value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
    value = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', value)
    return value


def render_markdown(text: str) -> str:
    lines = str(text or '').replace('\r\n', '\n').split('\n')
    output: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None
    in_code = False
    code_lines: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            output.append('<p>' + '<br>'.join(_inline(line) for line in paragraph) + '</p>')
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f'</{list_type}>')
            list_type = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith('```'):
            flush_paragraph()
            close_list()
            if in_code:
                output.append('<pre><code>' + html.escape('\n'.join(code_lines)) + '</code></pre>')
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not stripped:
            flush_paragraph()
            close_list()
            index += 1
            continue
        if index + 1 < len(lines) and '|' in line and re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*', lines[index + 1]):
            flush_paragraph()
            close_list()
            headers = [cell.strip() for cell in line.strip().strip('|').split('|')]
            output.append('<div class="table-wrap"><table><thead><tr>' + ''.join(f'<th>{_inline(cell)}</th>' for cell in headers) + '</tr></thead><tbody>')
            index += 2
            while index < len(lines) and '|' in lines[index] and lines[index].strip():
                cells = [cell.strip() for cell in lines[index].strip().strip('|').split('|')]
                output.append('<tr>' + ''.join(f'<td>{_inline(cell)}</td>' for cell in cells) + '</tr>')
                index += 1
            output.append('</tbody></table></div>')
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f'<h{level}>{_inline(heading.group(2))}</h{level}>')
            index += 1
            continue
        if re.fullmatch(r'[-*_]{3,}', stripped):
            flush_paragraph()
            close_list()
            output.append('<hr>')
            index += 1
            continue
        if stripped.startswith('> '):
            flush_paragraph()
            close_list()
            output.append(f'<blockquote>{_inline(stripped[2:])}</blockquote>')
            index += 1
            continue
        unordered = re.match(r'^[-*+]\s+(.+)$', stripped)
        ordered = re.match(r'^\d+[.)]\s+(.+)$', stripped)
        if unordered or ordered:
            flush_paragraph()
            target = 'ul' if unordered else 'ol'
            if list_type != target:
                close_list()
                output.append(f'<{target}>')
                list_type = target
            output.append(f'<li>{_inline((unordered or ordered).group(1))}</li>')
            index += 1
            continue
        close_list()
        paragraph.append(stripped)
        index += 1

    if in_code:
        output.append('<pre><code>' + html.escape('\n'.join(code_lines)) + '</code></pre>')
    flush_paragraph()
    close_list()
    return '\n'.join(output)
