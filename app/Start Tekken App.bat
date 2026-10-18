@echo off
title Tekken app
cd /d "%~dp0"
py server.py
if errorlevel 1 pause
