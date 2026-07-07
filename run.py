"""
GDZ Monitor — ponto de entrada.

Como correr:
    python run.py        (ou duplo clique em run.bat)

Build do executável Windows:
    build.bat            (PyInstaller, gera dist/GDZMonitor.exe)
"""
from gdz_monitor.app.main import main

if __name__ == "__main__":
    main()
