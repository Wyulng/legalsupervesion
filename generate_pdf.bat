@echo off
chcp 65001 > nul
echo ============================================================
echo         项目文档 PDF 生成器 (Pandoc + HTML)
echo ============================================================
echo.

:: 检查 pandoc 是否安装
where pandoc > nul 2>&1
if errorlevel 1 (
    echo [错误] 未安装 Pandoc
    echo 请先安装: https://pandoc.org/installing.html
    echo 或运行: choco install pandoc
    pause
    exit /b 1
)

echo [1/3] 收集项目文件...

:: 创建临时目录
set TEMP_DIR=%TEMP%\pdf_gen_%RANDOM%
mkdir %TEMP_DIR% 2>nul

:: 生成合并的 Markdown 文件
(
echo # 民事判决书智能监督模型
echo.
echo 项目代码文档
echo.
echo ---自动生成---
echo.
)> "%TEMP_DIR%\README.md"

:: 复制 README
copy /Y "README.md" "%TEMP_DIR\README.md" > nul

:: 添加各文件内容
for %%F in (
    "docker-compose.yml"
    ".env.example"
    "backend\run.py"
    "backend\requirements.txt"
    "backend\dockerfile"
    "backend\.dockerignore"
    "backend\app\__init__.py"
    "backend\app\config.py"
    "backend\app\logging_config.py"
    "backend\app\main.py"
    "backend\app\models\__init__.py"
    "backend\app\models\schemas.py"
    "backend\app\services\__init__.py"
    "backend\app\services\file_parser.py"
    "backend\app\services\llm_caller.py"
    "backend\app\services\llm_client.py"
    "backend\app\services\m3_analyzer.py"
    "backend\app\services\m3_scenes.py"
    "backend\app\services\rag_store.py"
    "backend\app\services\regex_filter.py"
    "backend\app\services\section_assembler.py"
    "backend\app\services\section_extractor.py"
    "backend\app\services\task_store.py"
    "backend\app\utils\__init__.py"
    "backend\app\utils\helpers.py"
    "frontend\index.html"
    "frontend\nginx.conf"
) do (
    set "FILE=%%~F"
    if exist %%F (
        echo.] >> "%TEMP_DIR%\README.md"
        echo. >> "%TEMP_DIR%\README.md"
        echo # 文件: %%F >> "%TEMP_DIR%\README.md"
        echo. >> "%TEMP_DIR%\README.md"
        echo.``` >> "%TEMP_DIR%\README.md"
        type %%F >> "%TEMP_DIR%\README.md"
        echo.``` >> "%TEMP_DIR%\README.md"
        echo. >> "%TEMP_DIR%\README.md"
    )
)

echo [2/3] 生成 HTML 文档...

:: 生成 HTML（使用 GitHub 风格主题）
pandoc "%TEMP_DIR%\README.md" ^
    -o "项目文档.html" ^
    --toc ^
    --toc-depth=3 ^
    --metadata title="民事判决书智能监督模型" ^
    -c "https://cdn.jsdelivr.net/npm/github-markdown-css@5.8.1/github-markdown.min.css" ^
    -c "https://cdn.jsdelivr.net/npm/highlight.js@11.10.0/styles/github-dark.min.css" ^
    --highlight-style=pygments ^
    --mathjax ^
    --standalone ^
    --metadata author="Legal Supervision" ^
    --css "data:text/css,
        body { font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif !important; }
        .markdown-body { max-width: 1200px; margin: 0 auto; padding: 20px; }
        pre { border-radius: 8px; }
        code { font-family: 'Consolas', 'Source Code Pro', monospace !important; }
        .toc { background: #f6f8fa; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        #TOC { background: #f6f8fa; padding: 15px; border-radius: 8px; }
        #TOC ul { margin: 0; padding-left: 20px; }
        #TOC li { margin: 5px 0; }
    "

echo [3/3] 清理临时文件...
rmdir /S /Q %TEMP_DIR% 2>nul

echo.
echo ============================================================
echo           生成完成！
echo ============================================================
echo.
echo 文件已生成: 项目文档.html
echo.
echo [生成 PDF 方法]
echo 1. 在浏览器中打开 项目文档.html
echo 2. 按 Ctrl + P 打开打印
echo 3. 选择 [另存为 PDF] 或 [Microsoft Print to PDF]
echo 4. 布局选择 [横向] 效果最佳
echo.
echo 提示: 打印设置中勾选 [背景图形] 可保留代码高亮颜色
echo.
pause
