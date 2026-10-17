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
$IntervalSeconds = 30                     # fastest check: 120 requests/hour
$Reserve = 3                              # requests/hour left for the hourly GitHub collector
$BaseUrl = "https://api.ewgf.gg"
$MinWait = 60                             # shortest pause after a "too many requests" reply
if ($env:EWGF_BASE_URL) { $BaseUrl = $env:EWGF_BASE_URL }   # for testing only
if ($env:EWGF_TEST_FAST) { $IntervalSeconds = 2; $MinWait = 2 } # for testing only

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$KeyFile = Join-Path $Here "ewgf-key.txt"
$OutFile = Join-Path $Here "overlay-data.js"
$TmpFile = Join-Path $Here "overlay-data.tmp"
$LogFile = Join-Path $Here "poller-log.txt"
$LogMaxLines = 2000                       # about two weeks of streaming; older lines are trimmed

# Print a message in the window and keep a copy in poller-log.txt (stays on this PC).
function Write-Log($text, $color) {
    if ($color) { Write-Host $text -ForegroundColor $color } else { Write-Host $text }
    try { [System.IO.File]::AppendAllText($LogFile, ("{0:yyyy-MM-dd} {1}" -f (Get-Date), $text) + "`r`n") } catch {}
}

# Keep the log from growing forever: on start, keep only the newest lines.
function Limit-Log {
    try {
        if (Test-Path $LogFile) {
            $lines = [System.IO.File]::ReadAllLines($LogFile)
            if ($lines.Count -gt $LogMaxLines) {
                [System.IO.File]::WriteAllLines($LogFile, $lines[($lines.Count - $LogMaxLines)..($lines.Count - 1)])
            }
        }
    } catch {}
}

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

# Only one poller at a time: two copies would use the hourly limit twice as fast.
$script:Lock = New-Object System.Threading.Mutex($false, "Local\TekkenOverlayPoller")
$haveLock = $false
try { $haveLock = $script:Lock.WaitOne(0) }
catch [System.Threading.AbandonedMutexException] { $haveLock = $true }   # last copy crashed; take over
if (-not $haveLock) {
    Write-Host ""
    Write-Host "  The overlay poller is already running in another window." -ForegroundColor Yellow
    Write-Host "  Check your taskbar for 'Tekken overlay poller'. One copy is all you need."
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

$Modes = @{ RANKED_BATTLE = "ranked"; QUICK_BATTLE = "quick"; PLAYER_BATTLE = "player"; GROUP_BATTLE = "group" }

function ConvertTo-IsoUtc($value) {
    # PowerShell 7 turns ISO strings into dates; 5.1 leaves them as text.
    if ($value -is [datetime]) { return $value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
    return [string]$value
}

function ConvertTo-UtcDate($value) {
    if ($null -eq $value -or "$value" -eq "") { return $null }
    if ($value -is [datetime]) { return $value.ToUniversalTime() }
    try { return ([DateTimeOffset]::Parse([string]$value)).UtcDateTime } catch { return $null }
}

# How long to wait before the next check. ewgf.gg tells us how many requests
# are left this hour and when the hour resets, so we spread what's left
# evenly over the rest of the hour and never run dry.
function Get-PollDelay($remaining, $resetUtc) {
    if ($null -eq $remaining -or $null -eq $resetUtc) { return $IntervalSeconds }
    $secondsLeft = ($resetUtc - (Get-Date).ToUniversalTime()).TotalSeconds
    if ($secondsLeft -le 0) { return $IntervalSeconds }
    $usable = [int]$remaining - $Reserve
    if ($usable -le 0) { return [int][Math]::Ceiling($secondsLeft) + 5 }   # wait for the reset
    $even = [int][Math]::Ceiling($secondsLeft / $usable)
    return [Math]::Max($IntervalSeconds, $even)
}

# Status code and Retry-After from a failed request (PowerShell 5.1 and 7).
function Get-HttpStatus($err) {
    try { $r = $err.Exception.Response; if ($r) { return [int]$r.StatusCode } } catch {}
    return $null
}
function Get-RetryAfterSeconds($err) {
    $r = $err.Exception.Response
    if (-not $r) { return $null }
    try {
        $ra = $r.Headers.RetryAfter                          # PowerShell 7
        if ($ra -and $ra.Delta) { return [int]$ra.Delta.Value.TotalSeconds }
        if ($ra -and $ra.Date) { return [int]($ra.Date.Value.UtcDateTime - (Get-Date).ToUniversalTime()).TotalSeconds }
    } catch {}
    try { $v = $r.Headers["Retry-After"]; if ($v) { return [int]$v } } catch {}   # PowerShell 5.1
    return $null
}

function Write-OverlayData($battles, $tier, $errorText, $pausedUntil) {
    $paused = $null
    if ($pausedUntil) { $paused = $pausedUntil.ToString("yyyy-MM-ddTHH:mm:ssZ") }
    $payload = [pscustomobject]@{
        updated      = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        tier         = $tier
        error        = $errorText
        paused_until = $paused
        battles      = @($battles)
    }
    $json = $payload | ConvertTo-Json -Depth 4 -Compress
    # Write to a temp file, then swap it in, so the overlay never reads half a file.
    [System.IO.File]::WriteAllText($TmpFile, "window.OVERLAY_DATA = $json;")
    Move-Item -Path $TmpFile -Destination $OutFile -Force
}

Limit-Log
Write-Log ("[{0:h:mm:ss tt}] Poller started (checks every {1}s or more)" -f (Get-Date), $IntervalSeconds) "DarkGray"
Write-Host "Tekken overlay poller running. Leave this window open while you stream." -ForegroundColor Green
Write-Host "Checks ewgf.gg every $IntervalSeconds seconds or more, pacing itself to stay under the hourly limit."
Write-Host "Close this window to stop. A copy of these lines is saved in poller-log.txt."
Write-Host ""

$lastGood = @()
$lastTier = $null
$lastReset = $null
while ($true) {
    $sleep = $IntervalSeconds
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
        $meta = $resp._metadata
        $lastTier = $meta.tier
        $remaining = $meta.rate_limit_remaining
        $lastReset = ConvertTo-UtcDate $meta.rate_limit_reset
        Write-OverlayData $rows $lastTier $null $null
        $sleep = Get-PollDelay $remaining $lastReset
        $newest = "none"; if ($rows.Count -gt 0) { $newest = ($rows | Sort-Object battle_at | Select-Object -Last 1).battle_at }
        Write-Log ("[{0:h:mm:ss tt}] {1} battles, newest {2} | {3} tier, {4} requests left this hour, next check in {5}s" -f `
            (Get-Date), $rows.Count, $newest, $lastTier, $remaining, $sleep)
    }
    catch {
        $msg = $_.Exception.Message
        if ((Get-HttpStatus $_) -eq 429) {
            # Hourly limit used up. Wait it out instead of knocking every few seconds.
            $wait = Get-RetryAfterSeconds $_
            if (-not $wait -and $lastReset) { $wait = [int](($lastReset - (Get-Date).ToUniversalTime()).TotalSeconds) + 5 }
            if (-not $wait -or $wait -lt $MinWait) { $wait = [Math]::Max($MinWait, 300) }
            if ($env:EWGF_TEST_FAST -and $wait -gt 5) { $wait = 3 }
            $wait = [Math]::Min($wait, 3600)
            $resume = (Get-Date).ToUniversalTime().AddSeconds($wait)
            Write-Log ("[{0:h:mm:ss tt}] ewgf.gg hourly limit reached. Pausing until {1:h:mm tt}." -f `
                (Get-Date), $resume.ToLocalTime()) "Yellow"
            Write-OverlayData $lastGood $lastTier "rate_limited" $resume
            $sleep = $wait
        }
        else {
            Write-Log ("[{0:h:mm:ss tt}] Could not reach ewgf.gg: {1}" -f (Get-Date), $msg) "Yellow"
            # Keep showing the last good data, flagged with the error.
            Write-OverlayData $lastGood $lastTier $msg $null
        }
    }
    Start-Sleep -Seconds $sleep
}
