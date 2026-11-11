# --- Setup Core Paths ---
$PROJECT_ROOT = if ($PSScriptRoot) { (Resolve-Path "$PSScriptRoot\..").Path } else { (Get-Location).Path }
$VENDOR_ROOT = Join-Path $PROJECT_ROOT "vendor"
$BIN_ROOT = Join-Path $PROJECT_ROOT "src\workbench\bin"

if (!(Test-Path $BIN_ROOT)) { New-Item -ItemType Directory -Path $BIN_ROOT }

function Download-And-Install ($url, $destDir, $targetSearchPattern, $finalName) {
    Write-Host ">>> Searching $finalName from $url ..."
    $tempFile = Join-Path ${env:TEMP} "$finalName-pkg"
    if ($url.EndsWith(".zip")) { $tempFile += ".zip" }
    
    try {
        Invoke-WebRequest -Uri $url -OutFile $tempFile -TimeoutSec 300
    } catch {
        Write-Warning "    Failed to download $($finalName): $($_.Exception.Message)"
        return
    }
    
    if ($tempFile.EndsWith(".zip")) {
        $extractDir = Join-Path ${env:TEMP} "extract-$finalName"
        if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
        New-Item -ItemType Directory -Path $extractDir
        
        Write-Host "    Extracting zip..."
        Expand-Archive -Path $tempFile -DestinationPath $extractDir -Force
        
        # Robust search for exe matching pattern, excluding MPI variants which need complex setup
        $exe = Get-ChildItem -Path $extractDir -Filter "*.exe" -Recurse | Where-Object { 
            ($_.BaseName -like "*$targetSearchPattern*") -and !($_.Name -like "*mpi*") 
        } | Select-Object -First 1
        
        if ($exe) {
            Write-Host "    Found matching binary at $($exe.FullName), installing as $finalName to $destDir"
            if (!(Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir }
            Copy-Item -Path $exe.FullName -Destination (Join-Path $destDir $finalName) -Force
        } else {
            Write-Warning "    Could not find exe matching '$targetSearchPattern' in the zip archive."
        }
    } else {
        Write-Host "    Installing single file binary..."
        if (!(Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir }
        Copy-Item -Path $tempFile -Destination (Join-Path $destDir $finalName) -Force
    }
}

# 1. IQ-TREE (v2.2.0 - Prefer non-click version)
# We match iqtree.exe but exclude iqtree2-click.exe if possible
Download-And-Install "https://github.com/iqtree/iqtree2/releases/download/v2.2.0/iqtree-2.2.0-Windows.zip" (Join-Path $VENDOR_ROOT "iqtree3") "iqtree" "iqtree.exe"

# 2. MrBayes (Prefer win64)
Download-And-Install "https://github.com/NBISweden/MrBayes/releases/download/v3.2.7/MrBayes-3.2.7-WIN.zip" (Join-Path $VENDOR_ROOT "MrBayes") "mb*win64" "mb.exe"

# 3. MUSCLE (Already good, but keep for consistency)
Download-And-Install "https://github.com/rcedgar/muscle/releases/download/v5.1/muscle5.1.win64.exe" $BIN_ROOT "muscle" "muscle.exe"

# 4. MAFFT (Corrected URL)
Download-And-Install "https://mafft.cbrc.jp/alignment/software/mafft-7.526-win64-signed.zip" $BIN_ROOT "mafft" "mafft.exe"

# 5. Edlib (Python bindings) - Ensure it's working
Write-Host ">>> Ensuring edlib python package is installed..."
python -m pip install -q edlib

Write-Host "`nSUMMARY: Tools retrieval process completed."
