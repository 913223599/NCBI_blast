$exclude = @('.git', 'node_modules', 'dist', 'build', '__pycache__', '.gemini', '.vscode', 'artifacts', 'scratch', '.venv', 'venv', '.idea', 'target', '.pytest_cache');
function Get-Tree($path, $indent = "") {
    if (!(Test-Path $path)) { return }
    $items = Get-ChildItem -Path $path | Where-Object { $exclude -notcontains $_.Name };
    $itemCount = $items.Count;
    for ($i = 0; $i -lt $itemCount; $i++) {
        $item = $items[$i];
        $isLast = $i -eq ($itemCount - 1);
        
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

$targetPath = "d:\NCBI blast\docs\project_structure.md";
$header = "# NCBI BLAST Project Structure`n`nGenerated on: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n`n" + '```text' + "`n";
$tree = Get-Tree "d:\NCBI blast" | Out-String;
$footer = '```';

$content = $header + $tree + $footer;
# 使用 UTF8 无 BOM 写入
[System.IO.File]::WriteAllText($targetPath, $content, (New-Object System.Text.UTF8Encoding($false)));
