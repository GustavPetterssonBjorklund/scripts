param (
    [Parameter(Mandatory = $true)]
    [string]$Folder
)

# Resolve full path
$Folder = (Resolve-Path $Folder).Path

# Get current user PATH
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")

# Check if already exists
if ($currentPath.Split(";") -contains $Folder) {
    Write-Host "Already in PATH:" $Folder -ForegroundColor Yellow
    exit 0
}

# Append
$newPath = "$currentPath;$Folder"
[Environment]::SetEnvironmentVariable("PATH", $newPath, "User")

Write-Host "Added to PATH (User):" $Folder -ForegroundColor Green
Write-Host "Restart terminal to take effect."