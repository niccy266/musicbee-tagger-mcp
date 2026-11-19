#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Stops the MusicBee Tagger MCP Docker Compose stack, pulls the latest master branch, and rebuilds/starts the containers.
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    Write-Host "[*] Stopping existing Docker Compose containers..."
    docker compose down

    Write-Host "[*] Pulling latest changes from origin/master..."
    git pull --ff-only origin master

    Write-Host "[*] Building and starting Docker Compose containers..."
    docker compose up -d --build

    if (Test-Path "C:/dev") {
        Start-Sleep -Seconds 2
        docker cp musicbee-mcp:/certs/cert.pem C:/dev/cert.pem 2>$null
    }

    Write-Host "[+] Docker Compose containers are up:"
    docker compose ps
} finally {
    Pop-Location
}
