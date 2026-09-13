"""本地 HTML 视图的共享样式与页面骨架。

总入口（index.html）、资源链接（resources.html）、群文件（files.html）、
聊天记录收藏索引共用同一套设计；页面必须保持自包含（file:// 直接打开，
不联网），因此不允许引用任何外部资源。壁纸取自归档图片本身（view 目录内
的 wallpaper.*），构建时随机挑选。

深浅两套主题通过 CSS 变量切换：html[data-theme="light"] 覆盖变量值；
默认跟随系统 prefers-color-scheme，手动选择记忆在 localStorage（viewTheme）。
"""
from __future__ import annotations

import html
from pathlib import Path

WALLPAPER_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}

# 图库页等自带 CSS 的页面也要用的主题变量与切换按钮样式（与 BASE_CSS 保持一致）
THEME_VARS_CSS = """
:root{color-scheme:dark;--bg:#0d0f13;--text:#e8ecf4;--muted:#98a2b6;--accent:#7aa5ff;--accent-soft:#9fc2ff;
--panel:#171a22;--line:#262c3a;--line-strong:#333b4e;--img-bg:#11151c;--pre-bg:#151922;
--broken-bg:#241b1b;--broken-fg:#ffbd9f;--chip-text:#c6cfe2;--head-bg:rgba(13,15,19,.82);
--toggle-bg:rgba(23,26,34,.8)}
html[data-theme="light"]{color-scheme:light;--bg:#f2f4f8;--text:#222a3a;--muted:#68738a;--accent:#2f6bdb;--accent-soft:#2b62c9;
--panel:#ffffff;--line:#dfe4ee;--line-strong:#c9d2e3;--img-bg:#eceff5;--pre-bg:#eef1f7;
--broken-bg:#f7e8e4;--broken-fg:#b05a3c;--chip-text:#3d4a66;--head-bg:rgba(242,244,248,.85);
--toggle-bg:rgba(255,255,255,.85)}
.theme-toggle{position:fixed;top:14px;right:18px;z-index:9;padding:6px 13px;border-radius:999px;border:1px solid var(--line-strong);background:var(--toggle-bg);color:var(--chip-text);font-size:12.5px;cursor:pointer;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.theme-toggle:hover{border-color:var(--accent)}
"""

BASE_CSS = """
:root{color-scheme:dark;--bg:#0d0f13;--text:#e8ecf4;--muted:#98a2b6;--accent:#7aa5ff;--accent-soft:#9fc2ff;
--panel:#171a22;--panel-2:#1b1f2a;--line:#262c3a;--line-strong:#333b4e;
--card-bg:rgba(23,26,34,.78);--card-border:rgba(255,255,255,.09);--card-hover-bg:rgba(28,32,44,.85);--card-hover-border:rgba(158,190,255,.45);
--toolbar-bg:rgba(13,15,19,.66);--chip-bg:rgba(23,26,34,.55);--chip-border:rgba(255,255,255,.12);--chip-text:#c6cfe2;
--input-bg:rgba(23,26,34,.85);--pf-bg:rgba(23,26,34,.8);
--badge-bg:#243350;--badge-fg:#b9d3ff;--kind-bg:#3a3220;--kind-fg:#ffd98a;
--count-bg:rgba(122,165,255,.13);--count-fg:#bcd2ff;--icon-bg:rgba(122,165,255,.12);
--desc:#ccd3e0;--meta:#8b95a9;--code:#9fb0cc;
--copy-bg:#1d2736;--copy-border:#3d506d;--copy-fg:#b9d3ff;
--foot:#6f7a8f;--foot-line:rgba(38,44,58,.6);--item-hover:rgba(122,165,255,.05);--item-line:rgba(38,44,58,.8);
--section-line:rgba(38,44,58,.7);--gradient-a:rgba(58,92,164,.30);--gradient-b:rgba(96,70,160,.16);
--wall-a:rgba(13,15,19,.52);--wall-b:rgba(13,15,19,.6);--wall-c:rgba(13,15,19,.86);
--head-bg:rgba(13,15,19,.82);--img-bg:#11151c;--pre-bg:#151922;--broken-bg:#241b1b;--broken-fg:#ffbd9f;
--toggle-bg:rgba(23,26,34,.8);--shadow:0 12px 28px rgba(0,0,0,.35)}
html[data-theme="light"]{color-scheme:light;--bg:#f2f4f8;--text:#222a3a;--muted:#68738a;--accent:#2f6bdb;--accent-soft:#2b62c9;
--panel:#ffffff;--panel-2:#f6f8fc;--line:#dfe4ee;--line-strong:#c9d2e3;
--card-bg:rgba(255,255,255,.85);--card-border:rgba(28,44,90,.10);--card-hover-bg:rgba(255,255,255,.96);--card-hover-border:rgba(47,107,219,.35);
--toolbar-bg:rgba(242,244,248,.85);--chip-bg:rgba(28,44,90,.05);--chip-border:rgba(28,44,90,.14);--chip-text:#3d4a66;
--input-bg:#ffffff;--pf-bg:#ffffff;
--badge-bg:#e3ecff;--badge-fg:#2358b8;--kind-bg:#f6ecd2;--kind-fg:#96690f;
--count-bg:rgba(47,107,219,.10);--count-fg:#2b5cb8;--icon-bg:rgba(47,107,219,.10);
--desc:#3a445c;--meta:#7a8499;--code:#5a6a8c;
--copy-bg:#eef3fc;--copy-border:#b9ccec;--copy-fg:#2b5cb8;
--foot:#8a93a6;--foot-line:rgba(28,44,90,.10);--item-hover:rgba(47,107,219,.05);--item-line:rgba(28,44,90,.10);
--section-line:rgba(28,44,90,.12);--gradient-a:rgba(88,120,200,.12);--gradient-b:rgba(140,110,200,.08);
--wall-a:rgba(242,244,248,.42);--wall-b:rgba(242,244,248,.55);--wall-c:rgba(242,244,248,.88);
--head-bg:rgba(242,244,248,.85);--img-bg:#eceff5;--pre-bg:#eef1f7;--broken-bg:#f7e8e4;--broken-fg:#b05a3c;
--toggle-bg:rgba(255,255,255,.85);--shadow:0 12px 26px rgba(30,50,100,.14)}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;font-size:14.5px;margin:0;color:var(--text);line-height:1.6;background:radial-gradient(1100px 480px at 12% -8%,var(--gradient-a),transparent 60%),radial-gradient(900px 420px at 90% -10%,var(--gradient-b),transparent 55%),var(--bg)}
a{color:var(--accent-soft);text-decoration:none}
a:hover{text-decoration:underline}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wrap{max-width:1180px;margin:0 auto;padding:0 26px}
.crumbs{padding-top:22px;font-size:13px}
h1{font-size:24px;line-height:1.3;margin:8px 0 6px;letter-spacing:.2px}
.page-desc{margin:0;color:var(--muted);font-size:14px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 2px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border:1px solid var(--chip-border);border-radius:999px;background:var(--chip-bg);color:var(--chip-text);font-size:12.5px;backdrop-filter:blur(8px)}
.chip b{color:var(--text);font-weight:600}
.count-chip{flex:none}
.toggles{display:flex;flex-wrap:wrap;gap:8px 22px;margin:12px 0 0}
.toggles label{display:inline-flex;align-items:center;gap:7px;cursor:pointer;font-size:13px;color:var(--chip-text)}
.toggles input{accent-color:#4a6fa5;width:15px;height:15px;margin:0;cursor:pointer}
.toolbar{position:sticky;top:0;z-index:5;margin-top:14px;padding:12px 0;background:var(--toolbar-bg);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--section-line)}
.toolbar-inner{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.search{position:relative;flex:1 1 300px;max-width:560px}
.search::before{content:"🔍";position:absolute;left:12px;top:50%;transform:translateY(-50%);font-size:13px;opacity:.65;pointer-events:none}
#filter{width:100%;padding:10px 14px 10px 36px;border-radius:10px;border:1px solid var(--line-strong);background:var(--input-bg);color:var(--text);font-size:14.5px;outline:0;transition:border-color .15s,box-shadow .15s}
#filter:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(74,111,165,.22)}
button.pf{padding:6px 13px;border-radius:999px;border:1px solid var(--line-strong);background:var(--pf-bg);color:var(--accent-soft);font-size:13px;cursor:pointer;transition:border-color .12s,color .12s,background .12s}
button.pf:hover{border-color:var(--accent);color:var(--accent-soft)}
button.pf.active{background:#2c3f63;border-color:#46679f;color:#fff}
html[data-theme="light"] button.pf.active{background:#2b6ef3;border-color:#2b6ef3;color:#fff}
select#sortSel{padding:7px 10px;border-radius:999px;border:1px solid var(--line-strong);background:var(--pf-bg);color:var(--chip-text);font-size:13px;cursor:pointer;outline:0}
select#sortSel:focus{border-color:var(--accent)}
select#sortSel option{background:var(--panel);color:var(--text)}
.theme-toggle{position:fixed;top:14px;right:18px;z-index:9;padding:6px 13px;border-radius:999px;border:1px solid var(--line-strong);background:var(--toggle-bg);color:var(--chip-text);font-size:12.5px;cursor:pointer;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.theme-toggle:hover{border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;padding:18px 0 6px}
.card{position:relative;display:block;padding:16px 16px 13px;background:var(--card-bg);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid var(--card-border);border-radius:14px;color:inherit;transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease,background .15s ease}
a.card:hover{transform:translateY(-2px);border-color:var(--card-hover-border);background:var(--card-hover-bg);box-shadow:var(--shadow);text-decoration:none}
.card h2{margin:0 0 7px;font-size:15.5px;font-weight:650;display:flex;align-items:center;gap:9px;line-height:1.4}
.card .icon{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:9px;background:var(--icon-bg);font-size:17px;flex:none}
.card .muted{margin:0;color:var(--muted);font-size:12.5px;line-height:1.5}
.card .count{margin-top:10px;display:inline-block;padding:2px 10px;border-radius:999px;background:var(--count-bg);color:var(--count-fg);font-size:12px}
section.card{padding:4px 20px 12px;margin:18px 0;background:var(--card-bg);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
section.card h2{font-size:16px;font-weight:650;margin:16px 0 6px;display:flex;align-items:baseline;gap:8px}
section.card h2 .muted{font-size:12.5px;font-weight:400;color:var(--meta)}
ul.resource-list{list-style:none;margin:0;padding:0}
.resource-item{padding:13px 10px;border-top:1px solid var(--item-line);border-radius:8px;transition:background .12s}
ul.resource-list li:first-child .resource-item{border-top:0}
.resource-item:hover{background:var(--item-hover)}
.title{font-size:15px;font-weight:600;overflow-wrap:anywhere;line-height:1.55}
.desc{margin:.3em 0;color:var(--desc);font-size:13.5px}
.meta{font-size:12.5px;color:var(--meta)}
.badge{display:inline-block;padding:2px 9px;margin-right:8px;border-radius:999px;background:var(--badge-bg);color:var(--badge-fg);font-size:11.5px;vertical-align:1px}
.badge.kind{background:var(--kind-bg);color:var(--kind-fg)}
.actions{display:flex;gap:12px;align-items:center;margin:.45em 0 .2em}
.actions a{font-size:13.5px}
.copy-link{padding:4px 11px;border:1px solid var(--copy-border);border-radius:8px;background:var(--copy-bg);color:var(--copy-fg);font-size:12.5px;cursor:pointer;transition:background .12s}
.copy-link:hover{background:var(--badge-bg)}
.url{font-size:12.5px;margin:2px 0}
.url summary{cursor:pointer;color:var(--muted)}
.url code{overflow-wrap:anywhere;color:var(--code)}
#noResult{display:none;padding:46px 0 30px;text-align:center;color:var(--noresult)}
.foot{margin-top:26px;padding:20px 0 34px;border-top:1px solid var(--foot-line);color:var(--foot);font-size:12px}
@media(max-width:640px){.wrap{padding:0 16px}h1{font-size:20px}.grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}.search{max-width:none}}
"""

# 放在 <head> 里提前执行，避免首帧闪错主题
THEME_INIT_JS = (
    '(function(){var t;try{t=localStorage.getItem("viewTheme")}catch(e){}'
    'if(t!=="light"&&t!=="dark"){t=window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}'
    'document.documentElement.dataset.theme=t})();'
)

THEME_TOGGLE_HTML = '<button id="themeToggle" type="button" class="theme-toggle" title="切换深浅色"></button>'

THEME_TOGGLE_JS = (
    '<script>(function(){var b=document.getElementById("themeToggle");if(!b)return;'
    'function cur(){return document.documentElement.dataset.theme==="light"?"light":"dark"}'
    'function paint(){b.textContent=cur()==="dark"?"\\u2600\\ufe0f 浅色":"\\ud83c\\udf19 深色"}'
    'b.addEventListener("click",function(){var n=cur()==="dark"?"light":"dark";'
    'document.documentElement.dataset.theme=n;try{localStorage.setItem("viewTheme",n)}catch(e){}paint();});'
    'paint()})();</script>'
)

WALLPAPER_DEFER_JS = (
    '<script>(function(){var ready=function(){'
    '("requestIdleCallback"in window?requestIdleCallback:function(f){setTimeout(f,200)})'
    '(function(){document.body.classList.add("wallpaper-ready")},{timeout:2000})};'
    'document.readyState!=="loading"?ready():document.addEventListener("DOMContentLoaded",ready);})();</script>'
)


def find_wallpaper(view_dir: str | Path) -> str | None:
    """视图目录里构建时落下的 wallpaper.* 文件名；没有则返回 None。"""
    try:
        for path in sorted(Path(view_dir).glob('wallpaper.*')):
            if path.suffix.lower() in WALLPAPER_EXTS:
                return path.name
    except OSError:
        pass
    return None


def background_css(wallpaper: str | None) -> str:
    """把归档图变成全屏壁纸背景，遮罩颜色跟随深浅主题。

    壁纸挂到 body.wallpaper-ready 类上：页面内容先渲染，空闲时由脚本
    （见 page_shell 追加的延迟脚本）再换上大背景，避免首屏被壁纸阻塞。
    没有壁纸时保持纯渐变。
    """
    if not wallpaper:
        return ''
    url = html.escape(str(wallpaper), quote=True)
    return (
        f'body.wallpaper-ready{{background:url("{url}") center/cover no-repeat fixed var(--bg)}}'
        'body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;'
        'background:linear-gradient(180deg,var(--wall-a) 0%,var(--wall-b) 50%,var(--wall-c) 100%)}'
    )


def page_shell(*, title: str, body: str, background: str = '') -> str:
    """用共享样式包一个自包含的本地页面；body 需自带 .wrap 容器。"""
    defer = WALLPAPER_DEFER_JS if 'wallpaper-ready' in background else ''
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(title)}</title>'
        f'<script>{THEME_INIT_JS}</script>'
        f'<style>{BASE_CSS}{background}</style><body>{THEME_TOGGLE_HTML}'
        f'<div class="wrap">{body}</div>{THEME_TOGGLE_JS}{defer}</body></html>'
    )
