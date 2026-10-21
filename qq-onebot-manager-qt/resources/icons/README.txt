人物插画图标资源
================

桌面与应用内主图标采用白发、蓝裙、蓝色贝雷帽人物的大头 Q 版头像。
参考图仅提供平涂色块、大眼睛、腮红和轻微歪头的画风，不使用参考人物。

- app-portrait.png  内置 imagegen 生成的人物头像原稿，真实透明底。
- app.svg           内嵌 512 像素头像的 SVG，为可编辑的组合源稿。
- app.png           平滑导出的人物头像，供品牌区、窗口和托盘使用。
- app.ico           Windows 程序文件与系统托盘图标，含 16/20/24/32/48/64/128/256 像素。
- app-character.ico 桌面与开始菜单快捷方式专用同款头像图标，独立文件名避免旧图缓存。
- nav-*.svg/png     人物头像 + 对应功能标记，实际显示 32x32。
- card-*.svg/png    人物头像 + NapCat/OneBot/Bot/QQ 标记，36x36，42x42 底座。
- action-*.svg/png  人物头像 + 日月/退出标记，实际显示 28x28。
- check-white.svg   保持小尺寸清晰的奶白色圆头勾选符号。
- badges/*.svg      可编辑的功能标记原稿，用于组合人物图标。
- mascot.png/svg    白发蓝裙侧栏全身角色及 SVG 后备图。
- portrait-prompt.txt / mascot-prompt.txt  图片生成提示词和参考图片用途。

scripts/windows/build-character-icons.ps1 从头像原稿和功能标记生成所有图标，
只进行透明图像的尺寸封装、ICO 编码和 SVG 功能标记组合。
导航/卡片/按钮 SVG 内嵌头像图片，不依赖外部图片路径。

修改图标后需要重新构建。桌面快捷方式通过 install-tray-shortcut.ps1 更新，
可以用 -PanelExePath 显式指定新版管理器路径。

应用使用 PNG 图标以确保小尺寸平滑缩放，SVG 保留为组合源稿。
初次生成资源前，先构建 CMake 的 icon-assets-generator 目标；再运行
scripts/windows/build-character-icons.ps1，必要时用 -RasterExporterPath 指定导出工具。
在最小窗口尺寸下，侧栏角色自动缩小以确保七项导航完整可见。

主题人物配色
============
浅色主题使用本目录的白发蓝衣人物；深色主题使用 dark/ 下的黑发黑衣人物。
切换主题时，侧栏角色、品牌、导航、状态卡、操作按钮、窗口和托盘图标立即同步。
设置页和侧栏切换按钮共用主题选择，保存后在下次启动时恢复。
选择“跟随系统”时按 Windows 深浅色设置使用对应人物，也响应系统颜色变化。
真实 QQ 头像继续显示，不会被主题人物覆盖。
桌面快捷方式和程序文件的固定图标仍采用白发版。

- mascot-black.png / app-portrait-black.png  黑色系全身与头像原稿。
- dark/mascot.png  深色主题侧栏人物。
- dark/*.svg/png/ico  深色主题功能图标与多尺寸托盘图标。
- black-variant-prompts.txt  黑色人物生成提示词。

运行 scripts/windows/build-character-icons.ps1 -Variant dark 重新封装深色图标，
默认读取 app-portrait-black.png 和 mascot-black.png，不改动浅色主题资源。
