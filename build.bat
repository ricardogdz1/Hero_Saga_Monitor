@echo off
cd /d "%~dp0"
echo ============================================
echo   GDZ Monitor - Gerando executavel
echo ============================================
echo.

echo [1/3] Instalando dependencias...
pip install -r requirements.txt pyinstaller

echo.
echo [2/3] Gerando executavel PyWebView (HerosagaMonitor.spec)...
pyinstaller HerosagaMonitor.spec

echo.
echo [3/3] Pronto!
echo O executavel esta em: dist\GDZMonitor.exe
echo.
pause
