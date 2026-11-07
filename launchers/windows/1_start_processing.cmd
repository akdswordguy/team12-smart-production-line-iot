@echo off
title Team 12 - PROCESSING role (HiveMQ)
powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File "%~dp0team12_launch.ps1" -Role processing
