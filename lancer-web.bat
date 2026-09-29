@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1 && (
  py -3 serveur_web.py
  goto :eof
)
where python >nul 2>&1 && (
  python serveur_web.py
  goto :eof
)
echo Installez Python 3 depuis https://www.python.org/ puis relancez lancer-web.bat
pause
