# 注册"邮箱附件轮询"Windows 计划任务（schtasks）。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\install_mail_poll_task.ps1 -IntervalMinutes 5
# 说明：每 N 分钟运行一次 .venv 的 scheduler --once；日志写入 %TEMP%\mail_poll.log。
param(
    [int]$IntervalMinutes = 5,
    [string]$TaskName = "Doubao_MailDownload_Poll"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到 $python"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m src.mail_download.scheduler --once --since-days 7 --verbose *>> `"$env:TEMP\mail_poll.log`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "从 QQ 邮箱下载拼接 fasta 附件（豆包工作·噬菌体注释自动回传）" `
        -Force | Out-Null
    Write-Output "已注册计划任务: $TaskName（每 $IntervalMinutes 分钟轮询一次）"
    Write-Output "查看: schtasks /query /tn $TaskName"
    Write-Output "卸载: schtasks /delete /tn $TaskName /f"
} catch {
    Write-Error "注册失败: $_"
    exit 1
}
