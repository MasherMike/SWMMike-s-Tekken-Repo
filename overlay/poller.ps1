# Tekken 8 stream overlay - battle poller
#
# Asks ewgf.gg for your latest battles every 30 seconds and writes them to
# overlay-data.js, which overlay.html reads. Start it with start-overlay.bat
# before you go live, and leave the window open while streaming.
#
# Your API key is read from ewgf-key.txt in this folder. That file never
# leaves your PC (the repo's .gitignore keeps it out of GitHub).
#
# Works with Windows PowerShell 5.1 (built into Windows) and PowerShell 7.

$TekkenId = "4bN6AEeddYT6"               # your Tekken ID
$IntervalSeconds = 30                     # 120 requests/hour; EWGF Pro allows 1,000
$BaseUrl = "https://api.ewgf.gg"
if ($env:EWGF_BASE_URL) { $BaseUrl = $env:EWGF_BASE_URL }   # for testing only

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$KeyFile = Join-Path $Here "ewgf-key.txt"
$OutFile = Join-Path $Here "overlay-data.js"
$TmpFile = Join-Path $Here "overlay-data.tmp"

if (-not (Test-Path $KeyFile)) {
    Write-Host ""
    Write-Host "  Missing ewgf-key.txt" -ForegroundColor Red
    Write-Host "  Create a file named ewgf-key.txt in this folder and paste your"
    Write-Host "  EWGF API key into it (the key starts with ewgf_)."
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}
$Key = (Get-Content $KeyFile -Raw).Trim()

$Modes = @{ RANKED_BATTLE = "ranked"; QUICK_BATTLE = "quick"; PLAYER_BATTLE = "player"; GROUP_BATTLE = "group" }

function ConvertTo-IsoUtc($value) {
    # PowerShell 7 turns ISO strings into dates; 5.1 leaves them as text.
    if ($value -is [datetime]) { return $value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
    return [string]$value
}

function Write-OverlayData($battles, $tier, $errorText) {
    $payload = [pscustomobject]@{
        updated = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        tier    = $tier
        error   = $errorText
        battles = @($battles)
    }
    $json = $payload | ConvertTo-Json -Depth 4 -Compress
    # Write to a temp file, then swap it in, so the overlay never reads half a file.
    [System.IO.File]::WriteAllText($TmpFile, "window.OVERLAY_DATA = $json;")
    Move-Item -Path $TmpFile -Destination $OutFile -Force
}

Write-Host "Tekken overlay poller running. Leave this window open while you stream." -ForegroundColor Green
Write-Host "Checking ewgf.gg every $IntervalSeconds seconds. Close this window to stop."
Write-Host ""

$lastGood = @()
while ($true) {
    try {
        $resp = Invoke-RestMethod -Uri "$BaseUrl/external/battles/$TekkenId" `
            -Headers @{ Authorization = "Bearer $Key" } -TimeoutSec 30
        $rows = @()
        foreach ($b in $resp.data) {
            if ($b.p1_tekken_id -eq $TekkenId) { $me = "p1"; $op = "p2"; $iWon = ($b.winner -eq 1) }
            elseif ($b.p2_tekken_id -eq $TekkenId) { $me = "p2"; $op = "p1"; $iWon = ($b.winner -eq 2) }
            else { continue }
            $mode = $Modes[[string]$b.battle_type]
            if (-not $mode) { $mode = ([string]$b.battle_type).ToLower() }
            $result = "L"; if ($iWon) { $result = "W" }
            # Only what the overlay shows: no names, IDs or regions.
            $rows += [pscustomobject]@{
                battle_at = ConvertTo-IsoUtc $b.battle_at
                mode      = $mode
                my_char   = $b."$($me)_char"
                my_rank   = $b."$($me)_dan_rank"
                opp_char  = $b."$($op)_char"
                opp_rank  = $b."$($op)_dan_rank"
                result    = $result
                rounds    = "{0}-{1}" -f $b."$($me)_rounds_won", $b."$($op)_rounds_won"
            }
        }
        $lastGood = $rows
        Write-OverlayData $rows $resp._metadata.tier $null
        $newest = "none"; if ($rows.Count -gt 0) { $newest = ($rows | Sort-Object battle_at | Select-Object -Last 1).battle_at }
        Write-Host ("[{0:h:mm:ss tt}] {1} battles, newest {2}" -f (Get-Date), $rows.Count, $newest)
    }
    catch {
        $msg = $_.Exception.Message
        Write-Host ("[{0:h:mm:ss tt}] Could not reach ewgf.gg: {1}" -f (Get-Date), $msg) -ForegroundColor Yellow
        # Keep showing the last good data, flagged with the error.
        Write-OverlayData $lastGood $null $msg
    }
    Start-Sleep -Seconds $IntervalSeconds
}
