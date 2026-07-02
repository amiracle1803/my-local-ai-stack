@echo off
setlocal EnableDelayedExpansion
title Voice Studio - Setup
color 0A

echo.
echo  ==========================================
echo   Voice Studio  ^|  Chatterbox + F5-TTS
echo   GPU Accelerated  ^|  RTX 4070
echo  ==========================================
echo.

cd /d "%~dp0"

:: -- Python check ---------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo         Install Python 3.10-3.11 from python.org
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  Python %PY_VER% found.

:: -- Virtual environment ----------------------------------------
if not exist "venv\Scripts\activate.bat" (
    echo  Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause & exit /b 1
    )
) else (
    echo  Virtual environment exists, skipping creation.
)

call venv\Scripts\activate.bat

echo.
echo  Upgrading pip...
python -m pip install --upgrade pip -q

echo  Installing core packages ^(Flask, soundfile^)...
pip install flask soundfile -q

echo  Checking PyTorch / CUDA...
python -c "import torch; assert torch.cuda.is_available(), 'no cuda'" >nul 2>&1
if errorlevel 1 (
    echo  Installing PyTorch with CUDA 12.8 ^(RTX 4070^)...
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128 -q
    if errorlevel 1 (
        echo  [ERROR] PyTorch CUDA install failed.
        echo         Visit https://pytorch.org/get-started/locally/ for manual steps.
        pause & exit /b 1
    )
) else (
    python -c "import torch; print('  PyTorch', torch.__version__, '| GPU:', torch.cuda.get_device_name(0))"
)

echo  Installing Chatterbox TTS...
pip install chatterbox-tts -q

echo  Installing F5-TTS ^(~1.5 GB model downloads on first use^)...
pip install f5-tts huggingface_hub matplotlib pydub vocos -q

echo  Installing Kokoro + XTTS-v2 ^(for the optional humanize pipeline^)...
pip install kokoro TTS -q

echo  Pinning numba/llvmlite for Windows binary compatibility...
pip install numba==0.60.0 llvmlite==0.43.0 -q

echo.
echo  Applying Windows compatibility patches to F5-TTS/vocos...
python patch_f5tts.py

echo.
echo  ==========================================
echo   Setup complete. Run start.bat to launch.
echo  ==========================================
echo.

pause
