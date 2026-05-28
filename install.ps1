$ErrorActionPreference = "Stop"

$Repo = "AlfonsoDehesa/recollectium"
$InstallDir = Join-Path $env:LOCALAPPDATA "uv"
$UvBin = Join-Path $InstallDir "uv.exe"
$ToolBin = Join-Path $HOME ".local\bin"
$ManagedPathEdits = @()

function Get-UvArchiveName {
    $arch = $env:PROCESSOR_ARCHITECTURE
    switch ($arch) {
        "AMD64" { return "uv-x86_64-pc-windows-msvc.zip" }
        "ARM64" { return "uv-aarch64-pc-windows-msvc.zip" }
        default { throw "unsupported Windows architecture: $arch" }
    }
}

function Install-Uv {
    $existing = Get-Command uv -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "uv already installed: $($existing.Source)"
        return $existing.Source
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $archive = Get-UvArchiveName
    $url = "https://github.com/astral-sh/uv/releases/latest/download/$archive"
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid())
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip = Join-Path $tmp $archive

    Write-Host "Downloading uv..."
    Invoke-WebRequest -Uri $url -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $found = Get-ChildItem -Path $tmp -Filter uv.exe -Recurse | Select-Object -First 1
    if (-not $found) { throw "uv.exe not found in archive" }
    Copy-Item $found.FullName $UvBin -Force
    Remove-Item $tmp -Recurse -Force
    Write-Host "Installed uv: $UvBin"
    return $UvBin
}

function Get-RecollectiumInstallRef {
    if ($env:RECOLLECTIUM_INSTALL_REF) {
        return $env:RECOLLECTIUM_INSTALL_REF
    }

    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest"
        if ($release.tag_name) { return $release.tag_name }
    }
    catch {
        Write-Host "No GitHub release found; installing from main."
    }
    return "main"
}

$uv = Install-Uv
$ref = Get-RecollectiumInstallRef
$package = "git+https://github.com/$Repo.git@$ref"
Write-Host "Installing Recollectium from $ref..."
& $uv tool install --python 3.12 --force $package
if ($env:Path -notlike "*$ToolBin*") {
    $env:Path = "$ToolBin;$env:Path"
}
if ($env:GITHUB_PATH) {
    Add-Content -Path $env:GITHUB_PATH -Value $ToolBin
}
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath -notlike "*$ToolBin*") {
    [Environment]::SetEnvironmentVariable("Path", "$ToolBin;$userPath", "User")
    $ManagedPathEdits += "User Path: $ToolBin"
}
$stateDir = Join-Path $env:LOCALAPPDATA "recollectium"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$metadataPath = Join-Path $stateDir "install.json"
$metadata = [ordered]@{
    install_method = "bootstrap"
    source_ref = $ref
    installed_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    managed_path_edits = $ManagedPathEdits
}
$metadata | ConvertTo-Json | Set-Content -Path $metadataPath -Encoding utf8
Write-Host "Recollectium installed. Restart your terminal if recollectium is not found, then try: recollectium --version"
