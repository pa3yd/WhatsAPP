# 模拟聊天工作台 V2.0

本地 Python + Streamlit 工具，用来制作明确标注的虚构商务聊天，用于培训与演示。界面借鉴常见移动聊天布局，始终显示 `SIMULATED CHAT — FOR TRAINING AND DEMONSTRATION`。它不是 WhatsApp 客户端，也不连接或导入真实聊天。

## 安装与启动（Windows PowerShell）

```powershell
cd D:\WhatsAPP
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

打开 Streamlit 显示的本地地址。没有 API 密钥时，手动创建、离线示例、消息编辑、图片、预览、JSON 保存和 PNG/ZIP 导出均可使用。离线示例只覆盖内置语言（法语、英语、西班牙语、德语、中文）；未覆盖语言会使用英语示例并可手动改写。

PNG 导出需要浏览器。程序优先使用 Playwright 自带 Chromium，也可使用本机 Chrome；若两者均没有，运行 `.\.venv\Scripts\python.exe -m playwright install chromium`。

## 可选 AI 配置

仅在你决定启用 AI 时，把 `OPENAI_API_KEY` 放入当前进程环境变量；不要写入聊天 JSON。可通过 `OPENAI_MODEL` 选择支持结构化输出的模型，默认 `gpt-4o-mini`。程序不自动读取 `.env` 文件；`.env.example` 只是字段说明。模型生成后内容进入可编辑列表；事实、报价和产品规格仍需人工确认。单条重写只改目标文本，并保留该条 ID、图片、时间及其他消息。没有密钥时 AI 按钮给出明确错误。

## 使用

1. 在“单组聊天与编辑”设置人物、产品、关键词和时间规则。默认法国/法语、手机充电器、10 条、09:00–16:30、5–30 分钟、Europe/Rome。法国与 Rome 的组合只显示提醒；可自行切换 Paris。
2. 选择“完全手动”或“离线示例”创建消息；上传虚构头像和产品图片，随后在指定消息里选择附件。所有图片按资源 ID 保存在 `data/assets`。
3. 编辑文本、发送方和精确日期分钟。人工时间被固定；自动重算会保留它。调整顺序保留原时间并显示冲突提醒。要覆盖人工时间需点明确的全量重算按钮。可按纯文本、图片、图片加文字分别覆盖回复间隔；跨日对话用“结束日期偏移”指定 1–7 天。
4. 保存聊天或另存新版本；下载 JSON；准备并下载高清 PNG。完整 HTML 由同一模板用于预览和 Playwright 导出。
5. 批量页可编辑每组国家、语言、时区、人物和数量。失败组保留错误与重试入口，成功组可独立编辑、保存、导出，也可打包 ZIP。
6. 历史和模板页可载入记录。删除需先点“删除”，再点“确认删除”。

`data/chats`、`data/templates` 与 `data/assets` 是本地持久数据，重启应用后保留。迁移时请连同整个 `data` 目录复制；单独 JSON 不含图片二进制。不要用真实客户头像或未经授权素材。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖默认值、时间固定与冲突、关键词、图片与 JSON 保存、批量失败隔离、完整 PNG 和 ZIP。AI 实际调用需要用户启用并提供密钥，未提供时不能声称已通过线上调用验收。

## 结构

| 路径 | 用途 |
|---|---|
| `app.py` | Streamlit 页面与交互状态 |
| `chatbench/models.py` | 数据结构与验证 |
| `chatbench/time_engine.py` | 自动、人工、混合时间规则 |
| `chatbench/generator.py` | 离线示例与可选 AI 接口 |
| `chatbench/renderer.py` | HTML/CSS 聊天模板 |
| `chatbench/exporter.py` | Playwright PNG 与 ZIP |
| `chatbench/storage.py` | JSON、图片和模板存储 |
| `tests/` | 核心回归测试 |

## 已知边界

- 预览与 PNG 固定使用 420 CSS 像素宽度；较窄的浏览器窗口需横向滚动查看。默认导出 3 倍像素密度。
- 夏令时不存在的本地时间会报错；夏令时重复的小时当前使用该时区的默认第一次出现。若需精确区分两次出现，应增加 `fold` 选择。
- 批量离线示例属于固定演示文案，并非 AI 多语言生成；对未知语言回退英语。
- 预览与 PNG 共享 HTML/CSS，但不同浏览器环境的字体文件可产生细微字形差异。
