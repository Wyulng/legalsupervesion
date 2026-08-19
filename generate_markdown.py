#!/usr/bin/env python3
"""
项目代码整合脚本
将所有代码文件整合成一个 Markdown 文件
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
OUTPUT_MD = PROJECT_ROOT / "项目代码整合.md"

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
    "backend/app/services\section_assembler.py",
    "backend/app/services\section_extractor.py",
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


def get_lang(suffix):
    """根据扩展名获取语言标识"""
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
        ".dockerfile": "dockerfile",
    }
    return lang_map.get(suffix, "")


def main():
    print("=" * 60)
    print("        项目代码整合器")
    print("=" * 60)

    md_content = []
    md_content.append("# 民事判决书智能监督模型\n")
    md_content.append("\n")
    md_content.append("> 项目代码文档\n")
    md_content.append("\n")
    md_content.append("---\n")
    md_content.append("\n")

    file_count = 0
    skip_count = 0

    for rel_path in SOURCE_FILES:
        filepath = PROJECT_ROOT / rel_path

        # 检查是否在排除目录
        parts = rel_path.replace("\\", "/").split("/")
        if any(exclude in parts for exclude in EXCLUDE_DIRS):
            print(f"  [跳过] 排除目录: {rel_path}")
            skip_count += 1
            continue

        if not filepath.exists():
            print(f"  [跳过] 不存在: {rel_path}")
            skip_count += 1
            continue

        content = read_file_with_encoding(filepath)
        if content is None:
            print(f"  [跳过] 无法读取: {rel_path}")
            skip_count += 1
            continue

        # 获取语言
        lang = get_lang(filepath.suffix)

        # 添加文件标题
        md_content.append(f"\n## {rel_path}\n")
        md_content.append("\n")

        # 添加代码块
        md_content.append(f"```{lang}\n")
        md_content.append(content)
        md_content.append("\n```\n")

        print(f"  + {rel_path}")
        file_count += 1

    # 写入文件
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("".join(md_content))

    print("\n" + "=" * 60)
    print("           生成完成！")
    print("=" * 60)
    print(f"\n文件: {OUTPUT_MD}")
    print(f"大小: {OUTPUT_MD.stat().st_size / 1024:.1f} KB")
    print(f"包含: {file_count} 个文件 (跳过 {skip_count} 个)")


if __name__ == "__main__":
    main()
