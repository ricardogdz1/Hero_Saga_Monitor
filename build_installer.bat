@echo off
cd /d "%~dp0"
echo ============================================
echo   GDZ Monitor - Gerando instalador (Setup)
echo ============================================
echo.

rem Requer: dist\GDZMonitor.exe ja gerado (rode build.bat antes)
if not exist "dist\GDZMonitor.exe" (
    echo ERRO: dist\GDZMonitor.exe nao encontrado. Rode build.bat primeiro.
    pause
    exit /b 1
)

rem Versao vem de gdz_monitor\__init__.py (fonte unica)
for /f %%v in ('python -c "import gdz_monitor; print(gdz_monitor.__version__)"') do set APPVER=%%v
echo Versao: %APPVER%

rem Localiza o compilador do Inno Setup 6
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" (
    echo ERRO: Inno Setup 6 nao encontrado.
    echo Baixe gratis em: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

"%ISCC%" /DMyAppVersion=%APPVER% installer\GDZMonitor.iss
if errorlevel 1 (
    echo ERRO ao compilar o instalador.
    pause
    exit /b 1
)

echo.
echo Pronto! Instalador em: dist\GDZMonitor-Setup-v%APPVER%.exe
pause
