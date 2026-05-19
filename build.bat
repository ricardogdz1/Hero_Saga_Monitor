@echo off
echo ============================================
echo   Herosaga Monitor - Gerando executavel
echo ============================================
echo.

echo [1/3] Instalando dependencias...
pip install -r requirements.txt pyinstaller

echo.
echo [2/3] Gerando executavel...
pyinstaller --onefile --windowed --name "HerosagaMonitor" --icon=icon.ico app.py

echo.
echo [3/3] Pronto!
echo O executavel esta em: dist\HerosagaMonitor.exe
echo.
pause
