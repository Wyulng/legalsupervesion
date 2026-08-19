#!/usr/bin/env python3
"""
项目文档 HTML 生成器
使用 Pandoc 生成美观的 HTML，可直接打印为 PDF
"""

import subprocess
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
OUTPUT_HTML = PROJECT_ROOT / "项目文档.html"

# 需要打包的文件
SOURCE_FILES = [
    "README.md",
    "docker-compose.yml",
    ".env.example",
    "backend/run.py",
    "backend/requirements.txt",
    "backend/dockerfile",
    "backend/.dockerignore",
    "backend/app/__init__.py",
    "backend/app/config.py",
    "backend/app/logging_config.py",
    "backend/app/main.py",
    "backend/app/models/__init__.py",
    "backend/app/models/schemas.py",
    "backend/app/services/__init__.py",
    "backend/app/services/file_parser.py",
    "backend/app/services/llm_caller.py",
    "backend/app/services/llm_client.py",
    "backend/app/services/m3_analyzer.py",
    "backend/app/services/m3_scenes.py",
    "backend/app/services/rag_store.py",
    "backend/app/services/regex_filter.py",
    "backend/app/services/section_assembler.py",
    "backend/app/services/section_extractor.py",
    "backend/app/services/task_store.py",
    "backend/app/utils/__init__.py",
    "backend/app/utils/helpers.py",
    "frontend/index.html",
    "frontend/nginx.conf",
]

# 排除目录
EXCLUDE_DIRS = {"data", ".claude", "__pycache__", ".git"}


def read_file_with_encoding(filepath):
    """尝试多种编码读取文件"""
    encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except:
            continue
    return None


def generate_combined_markdown():
    """生成合并的 Markdown 文件"""
    md_content = []

    # 标题
    md_content.append("# 民事判决书智能监督模型\n\n")
    md_content.append("> 项目代码文档\n\n")
    md_content.append("---\n\n")

    for rel_path in SOURCE_FILES:
        filepath = PROJECT_ROOT / rel_path

        # 检查是否在排除目录
        parts = rel_path.replace("\\", "/").split("/")
        if any(exclude in parts for exclude in EXCLUDE_DIRS):
            continue

        if not filepath.exists():
            print(f"  [跳过] 不存在: {rel_path}")
            continue

        content = read_file_with_encoding(filepath)
        if content is None:
            print(f"  [跳过] 无法读取: {rel_path}")
            continue

        # 判断文件类型用于代码高亮
        suffix = filepath.suffix.lower()
        lang_map = {
            ".py": "python",
            ".html": "html",
            ".css": "css",
            ".js": "javascript",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".md": "markdown",
            ".sh": "bash",
            ".txt": "text",
        }
        lang = lang_map.get(suffix, "")

        md_content.append(f"## {rel_path}\n\n")
        md_content.append(f"```{lang}\n")
        md_content.append(content)
        md_content.append("\n```\n\n")
        print(f"  + {rel_path}")

    return "".join(md_content)


def main():
    print("=" * 60)
    print("        项目文档 HTML 生成器")
    print("=" * 60)

    print("\n[1/2] 收集文件并生成 Markdown...")
    md_content = generate_combined_markdown()

    # 保存临时合并文件
    temp_md = PROJECT_ROOT / "_temp_combined.md"
    with open(temp_md, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\n[2/2] 生成 HTML...")

    # 生成 HTML 内容
    result = subprocess.run(
        [
            "pandoc",
            str(temp_md),
            "-f", "markdown",
            "-t", "html",
            "--standalone",
            "--metadata", "title=民事判决书智能监督模型",
            "--highlight-style=pygments",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if result.returncode != 0:
        print(f"[错误] Pandoc 执行失败: {result.stderr}")
        temp_md.unlink()
        return

    # 完整 HTML 模板
    css = """
    <style>
    :root {
        --primary: #4f46e5;
        --bg: #0d1117;
        --text: #c9d1d9;
        --border: #30363d;
        --code-bg: #161b22;
    }
    * { box-sizing: border-box; }
    body {
        font-family: 'Microsoft YaHei', 'Segoe UI', -apple-system, sans-serif;
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
        margin: 0;
        padding: 20px;
    }
    .markdown-body {
        max-width: 1200px;
        margin: 0 auto;
        background: #161b22;
        padding: 40px 50px;
        border-radius: 12px;
        border: 1px solid var(--border);
    }
    h1, h2, h3, h4 {
        color: #ffffff;
        border-bottom: 1px solid var(--border);
        padding-bottom: 10px;
        margin-top: 35px;
    }
    h1 {
        font-size: 2.2em;
        text-align: center;
        border-bottom: none;
        margin-bottom: 30px;
        color: #58a6ff;
    }
    h2 { font-size: 1.6em; color: #58a6ff; }
    h3 { font-size: 1.3em; color: #8b949e; }
    a { color: #58a6ff; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code {
        font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
        background: var(--code-bg);
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.9em;
        color: #ff7b72;
    }
    pre {
        background: var(--code-bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 15px;
        overflow-x: auto;
    }
    pre code {
        background: none;
        padding: 0;
        font-size: 0.85em;
        line-height: 1.6;
        color: #c9d1d9;
    }
    blockquote {
        border-left: 4px solid var(--primary);
        margin: 20px 0;
        padding: 10px 20px;
        background: rgba(79, 70, 229, 0.1);
        color: #8b949e;
    }
    #TOC {
        background: var(--code-bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 20px;
        margin-bottom: 30px;
    }
    #TOC h2 { border: none; margin-top: 0; }
    #TOC ul { list-style: none; padding-left: 0; }
    #TOC li { margin: 8px 0; }
    hr { border: none; border-top: 1px solid var(--border); margin: 30px 0; }
    table { border-collapse: collapse; width: 100%; margin: 20px 0; }
    th, td { border: 1px solid var(--border); padding: 10px; text-align: left; }
    th { background: var(--code-bg); color: #ffffff; }
    /* 代码高亮覆盖 */
    .hljs { background: transparent !important; }
    /* 滚动条 */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: var(--bg); }
    ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 5px; }
    ::-webkit-scrollbar-thumb:hover { background: #484f58; }
    /* 分页打印优化 - 占满整个版面 */
    @media print {
        @page {
            size: landscape;
            margin: 10mm;
        }
        html, body {
            width: 100%;
            height: auto;
            margin: 0 !important;
            padding: 0 !important;
            background: white !important;
        }
        body {
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            color-adjust: exact !important;
        }
        .markdown-body {
            background: white !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 15mm 20mm !important;
            margin: 0 !important;
            max-width: 100% !important;
            width: 100% !important;
            color: #1f1f1f !important;
            font-size: 10pt !important;
            line-height: 1.4 !important;
        }
        h1 {
            font-size: 24pt !important;
            color: #0066cc !important;
            border-bottom: 2px solid #0066cc !important;
            margin-top: 0 !important;
            page-break-after: avoid;
        }
        h2 {
            font-size: 16pt !important;
            color: #333 !important;
            border-bottom: 1px solid #ddd !important;
            margin-top: 20px !important;
            page-break-after: avoid;
        }
        h3 {
            font-size: 12pt !important;
            color: #555 !important;
        }
        h4 { font-size: 11pt !important; color: #555 !important; }
        code {
            color: #c7254e !important;
            background: #f5f5f5 !important;
            border: 1px solid #ddd !important;
            font-size: 9pt !important;
        }
        pre {
            background: #f8f8f8 !important;
            border: 1px solid #ddd !important;
            border-left: 4px solid #0066cc !important;
            padding: 10px !important;
            margin: 10px 0 !important;
            font-size: 9pt !important;
            overflow-x: visible !important;
            white-space: pre-wrap !important;
            word-wrap: break-word !important;
        }
        pre code {
            color: #333 !important;
            background: transparent !important;
            font-size: 9pt !important;
            line-height: 1.5 !important;
        }
        blockquote {
            background: #f0f0f0 !important;
            border-left: 4px solid #888 !important;
            color: #555 !important;
            margin: 10px 0 !important;
        }
        #TOC {
            background: #f8f8f8 !important;
            border: 1px solid #ddd !important;
            padding: 15px !important;
            margin-bottom: 20px !important;
            page-break-after: avoid;
        }
        #TOC h2 { color: #333 !important; }
        a { color: #0066cc !important; }
        table {
            border: 1px solid #ddd !important;
            font-size: 9pt !important;
        }
        th {
            background: #f0f0f0 !important;
            color: #333 !important;
        }
        td { border: 1px solid #ddd !important; }
        hr { border-top: 1px solid #ddd !important; }
        .hljs { background: transparent !important; }
    }
    </style>
    """

    content = result.stdout

    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>民事判决书智能监督模型</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.10.0/styles/github-dark.min.css">
    <script src="https://cdn.jsdelivr.net/npm/highlight.js@11.10.0/lib/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
    {css}
</head>
<body>
<div class="markdown-body">
{content}
</div>
</body>
</html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(full_html)

    # 删除临时文件
    temp_md.unlink()

    print("\n" + "=" * 60)
    print("           生成完成！")
    print("=" * 60)
    print(f"\n文件: {OUTPUT_HTML}")
    print(f"大小: {OUTPUT_HTML.stat().st_size / 1024:.1f} KB")
    print("\n[生成 PDF 方法]")
    print("1. 双击打开 项目文档.html")
    print("2. 按 Ctrl + P 打印")
    print("3. 目标选择 [另存为 PDF]")
    print("4. 布局选择 [横向]")
    print("5. 勾选 [背景图形]")


if __name__ == "__main__":
    main()
