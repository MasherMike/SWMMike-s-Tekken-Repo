@echo off
rem Double-click this before you go live. It starts poller.ps1, which keeps
rem overlay-data.js up to date for the OBS overlay. Close the window to stop.
title Tekken overlay poller
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0poller.ps1"
