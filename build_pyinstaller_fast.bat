@echo off
setlocal enableextensions

rem Fast packaging path (AV-friendly variant)
rem Usage: build_pyinstaller_fast.bat [AppName] [DistDir] [CleanFlag]
rem Example: build_pyinstaller_fast.bat SeaAnemone dist clean

set "APPNAME=%~1"
set "DISTDIR=%~2"
set "CLEANFLAG=%~3"

if "%APPNAME%"=="" set "APPNAME=SeaAnemone"
if "%DISTDIR%"=="" set "DISTDIR=dist"

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "ENTRY=%ROOT%\app\app.py"
set "PYI_BUILD=%ROOT%\build\pyi"
set "PYI_SPEC=%ROOT%\build\%APPNAME%.spec"

if not exist "%ENTRY%" (
	echo [ERROR] Entry file not found: %ENTRY%
	exit /b 1
)

if /I "%CLEANFLAG%"=="clean" (
	echo [INFO] Cleaning previous PyInstaller artifacts...
	if exist "%PYI_BUILD%" rd /s /q "%PYI_BUILD%"
	if exist "%PYI_SPEC%" del /q "%PYI_SPEC%"
	if exist "%ROOT%\%DISTDIR%\%APPNAME%" rd /s /q "%ROOT%\%DISTDIR%\%APPNAME%"
)

rem The help docs are optional: only bundle them if they have been built
rem (PyInstaller stops with an error when an --add-data source is missing).
set "DOCS_ARG="
if exist "%ROOT%\docs\build\html" (
	set "DOCS_ARG=--add-data "%ROOT%\docs\build\html;docs/build/html""
) else (
	echo [WARN] docs\build\html not found - building without the help pages.
)

echo.
echo [INFO] Building fast onedir package with PyInstaller...
echo.

rem kaleido + choreographer: PNG export for the report, the 3D report
rem preview and the Interpret export. kaleido 1.x renders through an
rem installed Chromium-based browser (Chrome, Edge, Chromium or Brave) on
rem the machine running the exe -- Edge ships with Windows 10/11.
rem docx: python-docx's built-in .docx template, needed to write the report.
rem Qt: the app never uses Qt (browser UI + Tk dialogs), but the env has
rem both PyQt5 and PyQt6 installed and other packages' optional imports
rem (e.g. matplotlib backends) make PyInstaller try to bundle both, which
rem it refuses to do -- so all Qt bindings are excluded.
rem torchaudio/torchvision: unused by the app; torchaudio's DLL doesn't
rem match the installed torch and crashes PyInstaller's analysis step.
rem rasterio: its compiled modules import submodules (e.g. rasterio.sample)
rem that PyInstaller can't see, plus it ships GDAL/PROJ data files.
rem pyproj: its PROJ database (proj.db) lives inside the package (pip
rem install), where PyInstaller's hook doesn't look in a conda env.
python -m PyInstaller ^
	--exclude-module PyQt5 ^
	--exclude-module PyQt6 ^
	--exclude-module PySide2 ^
	--exclude-module PySide6 ^
	--exclude-module torchaudio ^
	--exclude-module torchvision ^
	--collect-all rasterio ^
	--collect-all pyproj ^
	--noconfirm ^
	--onedir ^
	--noconsole ^
	--name "%APPNAME%" ^
	--distpath "%ROOT%\%DISTDIR%" ^
	--workpath "%PYI_BUILD%" ^
	--specpath "%ROOT%\build" ^
	--hidden-import plotly.graph_objs._figure ^
	--hidden-import _plotly_utils.importers ^
	--collect-all plotly ^
	--collect-all dash ^
	--collect-all dash_bootstrap_components ^
	--collect-all dash_flexlayout ^
	--collect-all kaleido ^
	--collect-all choreographer ^
	--collect-data docx ^
	--add-data "%ROOT%\app\assets;assets" ^
	--add-data "%ROOT%\app\recent_projects.txt;app" ^
	%DOCS_ARG% ^
	"%ENTRY%"

if errorlevel 1 (
	echo.
	echo [ERROR] PyInstaller build failed.
	exit /b 1
)

set "OUTDIR=%ROOT%\%DISTDIR%\%APPNAME%"
echo.
echo [OK] Build finished: %OUTDIR%

if exist "%OUTDIR%\%APPNAME%.exe" (
	echo [OK] EXE: %OUTDIR%\%APPNAME%.exe
) else (
	echo [WARN] EXE not found in expected path.
)

rem The app opens its own browser tab once its server is up (and picks
rem another port if 8050 is busy), so the launcher only starts the exe.
rem Kept because the Inno Setup shortcuts point at it.
set "RUNNER=%OUTDIR%\run_%APPNAME%.bat"
> "%RUNNER%" echo @echo off
>>"%RUNNER%" echo set "APPDIR=%%~dp0"
>>"%RUNNER%" echo start "" "%%APPDIR%%\%APPNAME%.exe"
echo [OK] Launcher: %RUNNER%

endlocal
