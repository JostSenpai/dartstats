@echo off
cd /d "%~dp0"

echo [SYSTEM] Firing up the Autodarts Pipeline in the background...
start /B py -3.12 dartstats.py

echo [SYSTEM] Launching the Analytics Dashboard...
:: Bypassing the Windows PATH issue by running Streamlit directly through Python!
py -3.12 -m streamlit run dashboard.py
