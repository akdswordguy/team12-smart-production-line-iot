@echo off
title Team 12 - DEVICE role, ML-driven line (HiveMQ)
powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File "%~dp0team12_launch.ps1" -Role device -MlDriven
