@echo off
setlocal EnableDelayedExpansion
title Speech Filter - Setup
color 0A

echo.
echo  ==========================================
echo   Speech Filter  ^|  F5-TTS Audio Cleaner
echo   GPU Accelerated  ^|  RTX 4070
echo  ==========================================
echo.

cd /d "%~dp0"

:: ── Python check ───────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo         Install Python 3.10-3.11 from python.org
    pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  Python %PY_VER% found.

:: ── Virtual environment ────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo  Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause & exit /b 1
    )
    echo  Virtual environment created.
) else (
    echo  Virtual environment exists, skipping creation.
)

call venv\Scripts\activate.bat

:: ── Upgrade pip ────────────────────────────────────────────
echo.
echo  Upgrading pip...
python -m pip install --upgrade pip -q

:: ── Core deps ──────────────────────────────────────────────
echo  Installing core packages ^(Flask, soundfile^)...
pip install flask soundfile -q
if errorlevel 1 ( echo  [WARN] Some core packages failed. & )

:: ── CUDA PyTorch ───────────────────────────────────────────
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
    echo  PyTorch CUDA installed.
) else (
    python -c "import torch; print('  PyTorch', torch.__version__, '| GPU:', torch.cuda.get_device_name(0))"
)

:: ── F5-TTS ─────────────────────────────────────────────────
echo  Checking F5-TTS...
python -c "from f5_tts.api import F5TTS" >nul 2>&1
if errorlevel 1 (
    echo  Installing F5-TTS ~1.5 GB ^(model downloads on first use^)...
    pip install f5-tts cached-path -q
    if errorlevel 1 (
        echo  [WARN] f5-tts base install had issues, trying extra deps...
    )
    pip install matplotlib pydub vocos -q
    echo  F5-TTS installed.
) else (
    echo  F5-TTS already installed.
)

:: ── Scipy corruption guard ──────────────────────────────────
python -c "import scipy.optimize" >nul 2>&1
if errorlevel 1 (
    echo  Fixing corrupted scipy...
    pip install scipy --force-reinstall -q
)

:: ── Verify ─────────────────────────────────────────────────
echo.
echo  Verifying...
python -c "from f5_tts.api import F5TTS; print('  [OK] F5-TTS')" 2>&1
python -c "import torch; d=torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only'; print('  [OK] GPU:', d)" 2>&1

echo.
echo  ==========================================
echo   Setup complete.
echo.
echo   F5-TTS model downloads on first use
echo   ^(~1.5 GB from Hugging Face^).
echo.
echo   Run start.bat to launch the app.
echo  ==========================================
echo.

pause
