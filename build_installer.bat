@echo off
setlocal

cd /d "%~dp0"

set "ISS_FILE=installer\lumicontroll_setup.iss"
set "ISCC_EXE="

where ISCC.exe >nul 2>&1
if not errorlevel 1 set "ISCC_EXE=ISCC.exe"

if "%ISCC_EXE%"=="" if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if "%ISCC_EXE%"=="" if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC_EXE%"=="" (
    echo Inno Setup Compiler is niet gevonden.
    echo Installeer Inno Setup 6 en draai dit script opnieuw:
    echo https://jrsoftware.org/isinfo.php
    pause
    exit /b 1
)

if not exist "dist\lumicontroll.exe" (
    echo dist\lumicontroll.exe niet gevonden. Draai eerst build_app.bat.
    pause
    exit /b 1
)

if exist "installer_output" rmdir /s /q "installer_output"

"%ISCC_EXE%" "%ISS_FILE%"
if errorlevel 1 (
    echo.
    echo Installer build mislukt.
    pause
    exit /b 1
)

echo.
echo Klaar: installer_output\lumicontroll setup.exe
echo.
pause
