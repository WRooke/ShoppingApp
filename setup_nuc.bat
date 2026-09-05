@echo off
rem === ShoppingApp: one-time automated NUC setup ===
rem Run this ON THE NUC. See SETUP.md and DEPLOY.md for what it does and what stays manual.
rem Safe to re-run - every step checks current state first.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_nuc.ps1" %*
