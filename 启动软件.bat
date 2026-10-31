@echo off
chcp 65001 > nul
cd /d %~dp0
echo Starting Safety Quiz Web App...
python -m streamlit run app.py --server.headless false
pause
