@echo off
start "turnpike-monitor" /min python "%~dp0monitor.py"
start http://127.0.0.1:8642
