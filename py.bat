@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ================================================
echo           ComfyUI 完整自动化流程
echo ================================================
echo   步骤：1.导出参考图 → 2.参数调优 → 3.批量生成
echo ================================================
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] 虚拟环境不存在！请先运行：python -m venv venv
    pause
    exit /b 1
)

REM 检查 ComfyUI 是否运行
echo [检查] 正在检测 ComfyUI 服务...
curl -s http://127.0.0.1:8188/api/prompt >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ComfyUI 服务未启动！请先启动 ComfyUI（端口 8188）
    pause
    exit /b 1
)
echo [OK] ComfyUI 服务正常运行
echo.

REM 步骤1：导出参考图片
echo [1/3] 导出参考图片（用于参数调优）...
if not exist "reference_images" (
    mkdir reference_images
)
venv\Scripts\python.exe extract_reference_images.py
if errorlevel 1 (
    echo [WARN] 参考图片导出失败，继续执行...
) else (
    echo       ✅ 参考图片导出成功
)
echo.

REM 步骤2：运行LoRA参数调优
echo [2/3] 运行LoRA参数自动调优...
echo       每个风格最多30次试验，预计耗时较长，请耐心等待...
echo       调优结果将保存到 best_lora_params.json
venv\Scripts\python.exe optimize_all_lora.py
if errorlevel 1 (
    echo [WARN] 调优失败，将使用默认参数继续
) else (
    echo       ✅ 参数调优完成
)
echo.

REM 步骤3：批量生成
echo [3/3] 开始批量生成图片...
echo       文件名使用中文"卖点变量标签"
venv\Scripts\python.exe batch_generate.py
if errorlevel 1 (
    echo [ERROR] 批量生成失败
) else (
    echo       ✅ 批量生成完成
)
echo.

echo ================================================
echo                 全部完成！
echo ================================================
echo   📁 生成的图片保存在 ComfyUI 的 output 文件夹中
echo   📊 调优参数保存在 best_lora_params.json
echo   📸 参考图片保存在 reference_images 文件夹中
echo ================================================
pause
