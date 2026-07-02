@echo off
setlocal enabledelayedexpansion
title Real Natural Voices - Chatterbox + F5-TTS
color 0A
cls

echo.
echo  =========================================================
echo    Real Natural Voices  ^|  Chatterbox + F5-TTS
echo    Local  ^|  Unlimited  ^|  Voice Cloning  ^|  MIT License
echo  =========================================================
echo.

:: ---- STEP 1: System check ------------------------------------
echo  [1/5] Checking system...
nvidia-smi >nul 2>&1
if errorlevel 1 goto :no_gpu
for /f "skip=1 tokens=*" %%G in ('nvidia-smi --query-gpu=name --format=csv') do set _GPU=%%G
for /f "skip=1 tokens=*" %%G in ('nvidia-smi --query-gpu=memory.total --format=csv') do set _VRAM=%%G
echo         GPU: !_GPU! (!_VRAM!)
goto :gpu_done
:no_gpu
echo         No NVIDIA GPU detected -- will run on CPU.
:gpu_done
echo.

:: ---- STEP 2: Python check ------------------------------------
echo  [2/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo         [ERROR] Python not found.
    echo         Install Python 3.10+ from python.org then re-run.
    pause & exit /b 1
)
python --version
echo.

:: ---- STEP 3: Virtual environment -----------------------------
echo  [3/5] Setting up virtual environment...
set "VENV=%~dp0venv"
if not exist "!VENV!\Scripts\activate.bat" (
    echo         Creating venv...
    python -m venv "!VENV!"
    if errorlevel 1 ( echo         [ERROR] venv creation failed. & pause & exit /b 1 )
    echo         Created.
) else (
    echo         Already exists.
)
call "!VENV!\Scripts\activate.bat"
echo.

:: ---- STEP 4: PyTorch -----------------------------------------
echo  [4/5] Setting up PyTorch...
python -c "import torch, torchaudio" >nul 2>&1
if not errorlevel 1 goto :torch_all_ok

python -c "import torch" >nul 2>&1
if errorlevel 1 goto :install_torch_full

:: torch present but torchaudio missing -- install just torchaudio
echo         Installing audio library...
python -m pip install torchaudio --index-url https://download.pytorch.org/whl/cu124 -q
if errorlevel 1 python -m pip install torchaudio -q
goto :torch_done

:install_torch_full
echo         Installing PyTorch... (first run downloads ~2 GB)
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124 -q
if errorlevel 1 python -m pip install torch torchaudio -q
goto :torch_done

:torch_all_ok
echo         Already installed.
:torch_done
echo.

:: ---- STEP 5: Install packages --------------------------------
echo  [5/5] Installing packages...
python -m pip install --upgrade pip -q

echo         Installing Chatterbox and Flask...
python -m pip install -r "%~dp0requirements.txt" -q
if errorlevel 1 (
    echo         [ERROR] Install failed. Check your internet connection.
    pause & exit /b 1
)
python -c "from chatterbox.tts import ChatterboxTTS" >nul 2>&1
if errorlevel 1 (
    echo.
    echo         [ERROR] Chatterbox failed to import after install.
    echo         Try running this script again.
    pause & exit /b 1
)

echo         Installing F5-TTS...
python -m pip install f5-tts --no-deps -q
python -m pip install vocos --no-deps -q
python -m pip install torchdiffeq -q

echo         Applying F5-TTS compatibility patches...
python "%~dp0patch_f5tts.py"
if errorlevel 1 (
    echo         [WARN] Some patches may not have applied -- F5-TTS engine may not work.
)

echo         Installing Kokoro TTS...
python -m pip install kokoro soundfile -q
if errorlevel 1 (
    echo         [WARN] Kokoro install failed. /api/humanize Stage 1 will be unavailable.
)

echo         Installing XTTS-v2 (Coqui TTS)...
python -m pip install TTS -q
if errorlevel 1 (
    echo         [WARN] TTS install failed.
    echo                To install manually: pip install TTS
)

echo         Applying compatibility patches...
python "%~dp0patch_f5tts.py"

echo         All packages ready.
echo.

:: ---- Download Fish Speech model weights -----------------------
:: ---- Launch --------------------------------------------------
echo  ---------------------------------------------------------
echo    NOTE: First launch downloads models from Hugging Face (one-time):
echo      Chatterbox  ~1.7 GB   (voice cloning + expressive)
echo      F5-TTS      ~1.5 GB   (fast generation)
echo      XTTS-v2     ~1.9 GB   (humanization stage 2 -- CC-BY 4.0)
echo    All models are cached automatically after first download.
echo.
echo    Browser: http://localhost:5000
echo    Stop:    Press CTRL+C in this window
echo  ---------------------------------------------------------
echo.

:: Kill any process already on port 5000
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1
)

timeout /t 3 /nobreak >nul
python "%~dp0app.py"

echo.
echo  Server stopped. Press any key to close.
pause >nul