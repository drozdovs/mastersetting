@echo off
REM ============================================================
REM  MasterSetting 2.0 — автоматическая проверка на Windows 10/11
REM  Запускать в папке проекта: deploy\verify_windows.bat
REM
REM  Всё делается во временных папках (%TEMP%\ms-test) на тестовой
REM  «карте», созданной скриптом. Реальные настройки и боевая карта
REM  НЕ трогаются.
REM
REM  Результат: deploy\windows-report\ — набор текстовых файлов и
REM  итоговый REPORT.txt со сводкой. Пришлите его целиком.
REM ============================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0.."
set "ROOT=%CD%"
set "OUT=%ROOT%\deploy\windows-report"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

echo ============================================================
echo  MasterSetting 2.0 — проверка на Windows
echo  Корень проекта: %ROOT%
echo  Отчёт:          %OUT%
echo ============================================================
echo.

REM --- 0. Окружение --------------------------------------------------
python --version > "%OUT%\python-version.txt" 2>&1
where python >> "%OUT%\python-version.txt" 2>&1
ver > "%OUT%\windows-version.txt" 2>&1
wmic os get osarchitecture >> "%OUT%\windows-version.txt" 2>&1

echo [1/5] Автотесты (все должны пройти; часть пропускается — права POSIX и реальные образцы FX3/FX3A)...
python -m pytest tests/ -q > "%OUT%\test-result.txt" 2>&1
set "PYTEST_RC=%ERRORLEVEL%"
echo    код возврата pytest: %PYTEST_RC%

REM --- 1. Тестовая «карта» ------------------------------------------
echo.
echo [2/5] Создаём тестовую карту с настройками и «видео»...
set "MS_BASE_PATH=%TEMP%\ms-test\base"
set "CARDTEST=%TEMP%\ms-test\CARD"
if exist "%TEMP%\ms-test" rmdir /s /q "%TEMP%\ms-test"
python deploy\make_test_card.py "%CARDTEST%" > "%OUT%\make-card.txt" 2>&1

echo.
echo [3/5] Обнаружение носителей и разбор карты...
python cli.py cards > "%OUT%\cards.txt" 2>&1
python cli.py inspect --media "%CARDTEST%" > "%OUT%\inspect.txt" 2>&1

REM --- 2. Полный цикл -----------------------------------------------
echo.
echo [4/5] Полный цикл: сохранить дважды, записать, проверить...
(
  echo === save #1 ===
  python cli.py save-version --operator "Иван" --camera SonyFX3 --preset "Основные" --media "%CARDTEST%"
  echo === save #2 (та же дата — должна быть НОВАЯ версия) ===
  python cli.py save-version --operator "Иван" --camera SonyFX3 --preset "Основные" --media "%CARDTEST%"
  echo === versions (ожидаем ДВЕ) ===
  python cli.py versions --operator "Иван" --camera SonyFX3 --preset "Основные"
  echo === write ===
  python cli.py write-version --operator "Иван" --camera SonyFX3 --preset "Основные" --card "%CARDTEST%"
  echo === verify (ожидаем ok) ===
  python cli.py verify --operator "Иван" --camera SonyFX3 --preset "Основные" --card "%CARDTEST%"
  echo === пропавшая карта (ожидаем понятную ошибку, БЕЗ Traceback) ===
  python cli.py write-version --operator "Иван" --camera SonyFX3 --preset "Основные" --card "%TEMP%\ms-test\GONE"
) > "%OUT%\cycle.txt" 2>&1

REM --- 3. Проверки «глазами» ----------------------------------------
echo.
echo [5/5] Проверяем, что медиа не скопировано и карта не тронута...
(
  echo === видео в библиотеке (должно быть пусто) ===
  dir /s /b "%MS_BASE_PATH%\*.mp4" 2>nul
  dir /s /b "%MS_BASE_PATH%\*.mxf" 2>nul
  echo === видео на карте (должно остаться на месте) ===
  if exist "%CARDTEST%\CLIP0001.MP4" (echo CLIP0001.MP4 на месте) else (echo ВНИМАНИЕ: CLIP0001.MP4 пропал)
  if exist "%CARDTEST%\PRIVATE\M4ROOT\CLIP\CLIP0002.MXF" (echo CLIP0002.MXF на месте) else (echo ВНИМАНИЕ: CLIP0002.MXF пропал)
) > "%OUT%\media-check.txt" 2>&1

REM --- 4. Сводка -----------------------------------------------------
set "HAS_TRACEBACK=no"
findstr /i /c:"Traceback" "%OUT%\cycle.txt" >nul 2>&1 && set "HAS_TRACEBACK=YES"
set "VER_COUNT="
for /f %%n in ('findstr /r /c:"version_id" "%OUT%\cycle.txt" ^| find /c /v ""') do set "VER_COUNT=%%n"

(
  echo MasterSetting 2.0 — отчёт проверки на Windows
  echo Дата: %DATE% %TIME%
  echo Проект: %ROOT%
  echo.
  echo pytest код возврата: %PYTEST_RC%   [0 = тесты прошли]
  echo Traceback в цикле:   %HAS_TRACEBACK%   [no = ошибки обрабатываются понятно]
  echo.
  echo Последняя строка тестов:
) > "%OUT%\REPORT.txt"
findstr /r /c:"passed" /c:"failed" /c:"error" "%OUT%\test-result.txt" >> "%OUT%\REPORT.txt" 2>&1
(
  echo.
  echo Файлы отчёта:
  echo   test-result.txt    — автотесты
  echo   cards.txt          — обнаружение носителей
  echo   inspect.txt        — разбор карты (медиа НЕ в settings_files)
  echo   cycle.txt          — полный цикл: 2 версии, запись, проверка, пропавшая карта
  echo   media-check.txt    — медиа не скопировано, карта не тронута
  echo   windows-version.txt — версия и разрядность Windows
  echo.
  echo Ожидаемо: pytest = 0; Traceback = no; в cycle.txt — ДВЕ версии и verify ok.
) >> "%OUT%\REPORT.txt"

echo.
echo ============================================================
if "%PYTEST_RC%"=="0" (echo  ИТОГ: тесты ПРОШЛИ) else (echo  ИТОГ: есть упавшие тесты — см. test-result.txt)
echo  Отчёт собран: %OUT%\REPORT.txt
echo  Пришлите папку windows-report целиком.
echo ============================================================
pause
endlocal
