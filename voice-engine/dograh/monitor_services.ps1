# Monitoring Script for Dograh Services
# This script opens two new PowerShell windows to tail the logs of pocket-tts and ollama.

Start-Process powershell -ArgumentList "-NoExit", "-Command", "docker logs -f pocket-tts" -WindowStyle Normal
Start-Process powershell -ArgumentList "-NoExit", "-Command", "docker logs -f ollama" -WindowStyle Normal

Write-Host "Monitoring terminals launched!" -ForegroundColor Green
