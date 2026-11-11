<#
.SYNOPSIS
    Project structure generator with advanced filtering.
#>

$excludeList = @(
    '.git', 'node_modules', '.venv', 'venv', 'dist', 'build', 'artifacts', 
    'scratch', '.gemini', '.vscode', '.idea', 'target', '.pytest_cache', 
    '__pycache__', 'coverage', 'htmlcov', 'bin_extract'
);

$excludePatterns = @(
    '*test*',
    '*spec*',
    '*.pyc', '*.pyo',
    'log_*.txt', 'crash_*.log',
    '*.db*',
    '*.md5'
);

function Get-Tree($path, $indent = "") {
    if (!(Test-Path $path)) { return }
    
    $items = Get-ChildItem -Path $path | Where-Object { 
        $name = $_.Name;
        if ($excludeList -contains $name) { return $false }
        foreach ($pattern in $excludePatterns) {
            if ($name -like $pattern) { return $false }
        }
        return $true
    };

    $itemCount = $items.Count;
    for ($i = 0; $i -lt $itemCount; $i++) {
        $item = $items[$i];
        $isLast = ($i -eq ($itemCount - 1));
        
        $prefix = "|-- ";
        if ($isLast) { $prefix = "\-- " }
        Write-Output ($indent + $prefix + $item.Name);
        
        if ($item.PSIsContainer) {
            $isLastStr = "|   ";
            if ($isLast) { $isLastStr = "    " }
            $newIndent = $indent + $isLastStr;
            Get-Tree $item.FullName $newIndent;
        }
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = (Get-Item $scriptDir).Parent.FullName
$targetPath = Join-Path $projectRoot "docs\project_structure.md"

Write-Host "Scanning structure: $projectRoot ..." -ForegroundColor Cyan

$header = "# NCBI BLAST Project Structure`n" +
          "> Status: Auto-generated (Filtered test and temp files)`n" +
          "> Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n`n" + 
          '```text' + "`n";

$tree = Get-Tree $projectRoot | Out-String;
$footer = '```';

$content = $header + $tree + $footer;

[System.IO.File]::WriteAllText($targetPath, $content, (New-Object System.Text.UTF8Encoding($false)));

Write-Host "Success! Document updated: $targetPath" -ForegroundColor Green
