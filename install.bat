@echo off
echo Creating C:\cheongak ...
mkdir C:\cheongak 2>nul
mkdir C:\cheongak\templates 2>nul
mkdir C:\cheongak\static 2>nul
mkdir C:\cheongak\static\css 2>nul

echo Copying files...
xcopy /Y "%~dp0*.py" "C:\cheongak\" >nul
xcopy /Y "%~dp0*.txt" "C:\cheongak\" >nul
xcopy /Y "%~dp0templates\*" "C:\cheongak\templates\" >nul
xcopy /Y "%~dp0static\css\*" "C:\cheongak\static\css\" >nul

echo.
echo Done! Now syncing packages and starting...
echo.
cd /d C:\cheongak
uv sync
uv run app.py
pause
