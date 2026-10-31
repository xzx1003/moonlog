@echo off
REM Windows batch wrapper for build.ps1
powershell -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
