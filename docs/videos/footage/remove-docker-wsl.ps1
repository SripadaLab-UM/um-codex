# Removes Docker Desktop and WSL (an administrator run) so UM-Codex's installer can be tested from scratch.
# Started elevated by whoever is testing; logs to C:\umv-film\remove-docker-wsl.log.
$ErrorActionPreference = "Continue"
Start-Transcript C:\umv-film\remove-docker-wsl.log -Force | Out-Null
"== Docker Desktop =="
Get-Process "Docker Desktop", "com.docker.backend", "com.docker.build", "docker-sandbox" -ErrorAction SilentlyContinue | Stop-Process -Force
$installer = Join-Path $Env:ProgramFiles "Docker\Docker\Docker Desktop Installer.exe"
& $installer uninstall --quiet | Out-Host
"docker exit: $LASTEXITCODE"
Start-Sleep 5
"== WSL =="
wsl --shutdown 2>&1 | Out-Host
$p = Start-Process msiexec -ArgumentList '/x', '{DC52CEBE-E53A-463D-98EE-81AF640914BD}', '/qn', '/norestart' -Wait -PassThru
"wsl msi exit: $($p.ExitCode)"
"done"
Stop-Transcript | Out-Null
