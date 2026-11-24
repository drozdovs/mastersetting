@echo off
REM ============================================================
REM  Сборка MasterSetting.exe (Windows)
REM  Запускать в папке проекта: deploy\build_agent.bat
REM ============================================================
setlocal

cd /d "%~dp0.."

echo [1/4] Установка зависимостей для сборки...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo [2/4] Очистка предыдущей сборки...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/4] Сборка (onedir, без UPX)...
python -m PyInstaller --clean --noconfirm deploy\MasterSetting.spec

echo [4/4] Готово. Файл: dist\MasterSetting\MasterSetting.exe
echo.
echo Дальнейшие шаги для антивирусов:
echo   - Подписать код: signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx dist\MasterSetting\MasterSetting.exe
echo   - Отправить в Microsoft: https://www.microsoft.com/wdsi/filesubmission
echo   - Упаковать папку dist\MasterSetting в zip (портативная сборка)
pause
