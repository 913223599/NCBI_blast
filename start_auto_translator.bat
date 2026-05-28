@echo off
chcp 65001 >nul
title NCBI Taxonomy 本地词库全自动翻译工具
echo ===================================================
echo     NCBI Taxonomy 本地词库全自动翻译工具
echo     (基于 Google 免费引擎，后台挂机专用)
echo ===================================================
echo.
python "src\utils\taxonomy_auto_translator.py"
echo.
echo 任务已执行完毕。
pause
