@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ================================================
echo           ComfyUI Full Automation Workflow
echo ================================================
echo   Steps: 1.Parameter Tuning -^> 2.Batch Generate
echo ================================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found! Please run: python -m venv venv
    pause
    exit /b 1
)

echo [Check] Detecting ComfyUI service...
curl -s -m 5 http://127.0.0.1:8188/api/prompt >nul 2>&1
if errorlevel 1 (
    echo [WARN] Could not detect ComfyUI, but continuing anyway...
    echo        Please ensure ComfyUI is running on port 8188
) else (
    echo [OK] ComfyUI service is running
)
echo.

echo [1/2] Running LoRA parameter optimization...
echo       Max 30 trials per label, this may take a while...
echo       Results will be saved to data/best_lora_params.json
venv\Scripts\python.exe python\optimize_all_lora.py
if errorlevel 1 (
    echo [WARN] Optimization failed, using default parameters
) else (
    echo       [OK] Parameter optimization completed
)
echo.

echo [2/2] Starting batch generation...
echo       Filenames use Chinese "卖点变量标签" column
venv\Scripts\python.exe python\batch_generate.py
if errorlevel 1 (
    echo [ERROR] Batch generation failed
) else (
    echo       [OK] Batch generation completed
)
echo.

echo ================================================
echo                    All Done!
echo ================================================
echo   Images saved in ComfyUI output folder
echo   Tuning params saved in data/best_lora_params.json
echo ================================================
pause