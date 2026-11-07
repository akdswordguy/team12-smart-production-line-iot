@echo off
title Team 12 - stop everything
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0team12_launch.ps1" -Role stop
echo.
echo Now start 1_start_processing.cmd, then 2_start_device.cmd.
pause
