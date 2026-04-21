$total_prophages = 3281395
$metadata_file = "F:\NCBI blast\database\Prophage.3281395sequence.metadata.tsv"
$msh_file = "F:\NCBI blast\database\Prophage.3281395sequence.fasta.gz.msh"

$Host.UI.RawUI.WindowTitle = "PhageScope Database Build Monitor"

while ($true) {
    try {
        Clear-Host
        Write-Host "==========================================================" -ForegroundColor Cyan
        Write-Host "         PhageScope Database Back-End Monitor" -ForegroundColor Cyan
        Write-Host "==========================================================" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  Target: Prophage.3281395sequence (17 GB Database)"
        Write-Host ""
        
        $lines_int = 0

        if (Test-Path $metadata_file) {
            $lines = ""
            $out = wsl -d Ubuntu -- bash -c "wc -l < '/mnt/f/NCBI blast/database/Prophage.3281395sequence.metadata.tsv' 2>/dev/null"
            if ($out) { $lines = $out -join "" }
            
            if ($lines -match "\d+") {
                $lines_int = [int]($lines -replace '[^\d]','')
                if ($lines_int -lt $total_prophages) {
                    $percent = [math]::Round(($lines_int / $total_prophages) * 100, 2)
                    Write-Host ">> Phase 1: High-Speed Metadata Extraction (zcat + awk)" -ForegroundColor Yellow
                    Write-Host "  Progress: $lines_int / $total_prophages ($percent%)" -ForegroundColor White
                    
                    $bar_len = 50
                    $filled = [math]::Round(($percent / 100) * $bar_len)
                    if ($filled -lt 0) { $filled = 0 }
                    if ($filled -gt 50) { $filled = 50 }
                    $empty = $bar_len - $filled
                    $bar = ("#" * $filled) + ("-" * $empty)
                    Write-Host "  [$bar]" -ForegroundColor Green
                } else {
                    Write-Host ">> Phase 1: High-Speed Metadata Extraction  [COMPLETE]" -ForegroundColor Green
                }
            } else {
                Write-Host ">> Phase 1: High-Speed Metadata Extraction ... [Reading]" -ForegroundColor Gray 
            }
        } else {
            Write-Host ">> Phase 1: High-Speed Metadata Extraction ... [Pending]" -ForegroundColor Gray
        }
        
        Write-Host ""
        
        if (Test-Path $msh_file) {
            $file_info = Get-Item $msh_file
            $size = $file_info.Length / 1MB
            $size_fmt = [math]::Round($size, 2)
            Write-Host ">> Phase 2: 32-Thread Parallel Fingerprinting (Mash Sketch)" -ForegroundColor Yellow
            Write-Host "  Writing Index... Current Size: $size_fmt MB" -ForegroundColor Magenta
            Write-Host "  (Est. final size ~12.5GB. Intensive CPU usage running...)" -ForegroundColor Gray
        } else {
             if ($lines_int -ge $total_prophages) {
                 Write-Host ">> Phase 2: 32-Thread Mash Sketch Launching... [Standby]" -ForegroundColor Yellow
             } else {
                 Write-Host ">> Phase 2: 32-Thread Mash Sketch ... [Waiting Phase 1]" -ForegroundColor Gray
             }
        }
        
        Write-Host ""
        Write-Host "  [Time: $(Get-Date -Format 'HH:mm:ss')] Press Ctrl+C or Close window to exit monitor." -ForegroundColor DarkGray
    } catch {
        # Silent fail to avoid looping error text
    }
    
    Start-Sleep -Seconds 3
}
