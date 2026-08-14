@echo off
setlocal

cd /d "%~dp0"

set "APP_NAME=lumicontroll"
set "ENTRY=app.py"
set "VIEWER_NAME=viewer"
set "VIEWER_ENTRY=viewer.py"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "SPEC_FILE=%APP_NAME%.spec"
set "VIEWER_SPEC_FILE=%VIEWER_NAME%.spec"

echo.
echo Building LumiControLL...
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python is niet gevonden. Installeer Python of zet python.exe in PATH.
    pause
    exit /b 1
)

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller ontbreekt. Installeren...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 (
        echo PyInstaller installeren is mislukt.
        pause
        exit /b 1
    )
)

python -c "import pyaudiowpatch" >nul 2>&1
if errorlevel 1 (
    echo pyaudiowpatch ontbreekt. Installeren...
    python -m pip install pyaudiowpatch
    if errorlevel 1 (
        echo pyaudiowpatch installeren is mislukt.
        pause
        exit /b 1
    )
)

if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%SPEC_FILE%" del /q "%SPEC_FILE%"
if exist "%VIEWER_SPEC_FILE%" del /q "%VIEWER_SPEC_FILE%"

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --icon "an.ico" ^
    --add-binary "libusb-1.0.dll;." ^
    --hidden-import "usb.backend.libusb1" ^
    --hidden-import "pyudmx" ^
    --hidden-import "stupidArtnet" ^
    --hidden-import "keyboard" ^
    --hidden-import "pyaudiowpatch" ^
    --hidden-import "_portaudiowpatch" ^
    "%ENTRY%"

if errorlevel 1 (
    echo.
    echo Build mislukt.
    pause
    exit /b 1
)

if exist "%VIEWER_ENTRY%" (
    echo.
    echo Building Art-Net Viewer...
    echo.
    python -m PyInstaller ^
        --noconfirm ^
        --clean ^
        --onefile ^
        --windowed ^
        --name "%VIEWER_NAME%" ^
        --icon "an.ico" ^
        "%VIEWER_ENTRY%"

    if errorlevel 1 (
        echo.
        echo Viewer build mislukt.
        pause
        exit /b 1
    )
)

copy /y "an.ico" "%DIST_DIR%\" >nul
copy /y "libusb-1.0.dll" "%DIST_DIR%\" >nul
if exist "readme.pdf" copy /y "readme.pdf" "%DIST_DIR%\" >nul
if exist "LICENSE.txt" copy /y "LICENSE.txt" "%DIST_DIR%\" >nul
if exist "docs" xcopy /e /i /y "docs" "%DIST_DIR%\docs" >nul
if exist "zadig-2.9.exe" copy /y "zadig-2.9.exe" "%DIST_DIR%\" >nul
if exist "third_party_licenses" xcopy /e /i /y "third_party_licenses" "%DIST_DIR%\third_party_licenses" >nul
if exist "viewer.py" copy /y "viewer.py" "%DIST_DIR%\" >nul
if exist "installer_defaults\shows" (
    xcopy /e /i /y "installer_defaults\shows" "%DIST_DIR%\shows" >nul
) else if exist "shows" (
    xcopy /e /i /y "shows" "%DIST_DIR%\shows" >nul
)

if exist "installer_defaults\settings.config" (
    copy /y "installer_defaults\settings.config" "%DIST_DIR%\" >nul
) else if exist "settings.config" (
    copy /y "settings.config" "%DIST_DIR%\" >nul
)
if exist "installer_defaults\sound_settings.json" (
    copy /y "installer_defaults\sound_settings.json" "%DIST_DIR%\" >nul
) else if exist "sound_settings.json" (
    copy /y "sound_settings.json" "%DIST_DIR%\" >nul
)

if exist "installer_defaults\adm.config" (
    copy /y "installer_defaults\adm.config" "%DIST_DIR%\" >nul
) else if exist "adm.config" (
    copy /y "adm.config" "%DIST_DIR%\" >nul
)

echo.
echo Klaar: %DIST_DIR%\%APP_NAME%.exe
echo.
pause
