@echo off
cd /d "%~dp0"
echo ============================================
echo   GDZ Monitor - Gerando executavel
echo ============================================
echo.

echo [1/4] Instalando dependencias...
pip install -r requirements.txt pyinstaller

echo.
echo [2/4] Rodando QA (pytest: unitarios + tests/qa)...
python -m pytest -q -p no:cacheprovider
if errorlevel 1 (
  echo.
  echo QA FALHOU - executavel NAO foi gerado. Corrija os testes acima.
  pause
  exit /b 1
)

echo.
echo [3/4] Gerando executavel PyWebView (HerosagaMonitor.spec)...
pyinstaller HerosagaMonitor.spec

echo.
echo [4/4] Pronto!
echo O executavel esta em: dist\GDZMonitor.exe
echo.
pause
