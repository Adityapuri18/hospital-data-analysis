@echo off
REM One-command setup for Windows. Double-click this file.
echo Installing Python packages...
pip install -r requirements.txt
echo.
echo Installing Node packages...
call npm install
if not exist .env copy .env.example .env
echo.
echo Done.
echo.
echo Quickest demo: open dashboard.html in a browser. Nothing else needed.
echo.
echo Full stack, two terminals in this folder:
echo   Terminal 1:  python app.py
echo   Terminal 2:  npm run seed   (once, needs MongoDB)
echo                npm start
echo Then open http://localhost:4000
pause
