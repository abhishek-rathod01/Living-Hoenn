# demo/demo.ps1 -- one-click open-day launcher for Living Hoenn.
#
# Run through the .bat files in the repo root (double-click them):
#   START_DEMO.bat       Ollama + model + tests + bridge + dashboard + mGBA
#   RESTART_BRIDGE.bat   restart only the bridge (then reload the hook in mGBA)
#   STOP_DEMO.bat        stop the bridge and dashboard, optionally mGBA and the model
#
# Or from PowerShell:
#   .\demo\demo.ps1 -Action start -Model qwen3:8b -SkipTests -State 1
#
# This script never deletes anything. It stops only the processes it started
# (found by the ports they listen on) and asks before closing mGBA.
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI.

param(
    [ValidateSet("start", "stop", "restart-bridge")]
    [string]$Action = "start",
    [string]$Model = "",        # empty = pick the best installed model
    [switch]$SkipTests,
    [switch]$NoMgba,
    [int]$State = 0,            # 1-9: load that savestate slot when mGBA opens
    [string]$Mgba = "",         # full path to mGBA.exe if it can't be found
    [string]$Rom = "",          # full path to the .gba if it isn't the default
    [switch]$Quiet              # never prompt: every question takes its default answer
)

$ErrorActionPreference = "Stop"
$Repo        = Split-Path -Parent $PSScriptRoot
$LivingHoenn = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Repo))
$DemoDir     = $PSScriptRoot
$Trace       = Join-Path $DemoDir "trace.jsonl"
$Hook        = Join-Path $Repo "lua\mgba_hook.lua"
$LastModel   = Join-Path $DemoDir ".last_model"
$MgbaCache   = Join-Path $DemoDir ".mgba_path"
$OllamaUrl   = "http://127.0.0.1:11434"
$BridgePort  = 8888
$DashPort    = 8890
$NumCtx      = 2048   # must match CHATTER_OPTIONS in bridge/dialogue_bridge_server.py
$Preferred   = @("qwen3:8b", "qwen2.5:7b-instruct-q4_0", "llama3.2:3b")
if (-not $Rom) { $Rom = Join-Path $LivingHoenn "pokeemerald\pokeemerald.gba" }

# ---------------------------------------------------------------- output
function Head($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "   ok   $t" -ForegroundColor Green }
function Info($t) { Write-Host "        $t" -ForegroundColor Gray }
function Warn($t) { Write-Host "   !!   $t" -ForegroundColor Yellow }
function Bad($t)  { Write-Host "   XX   $t" -ForegroundColor Red }
function Ask($q, [bool]$default) {
    if ($Quiet) { Info "$q -> $(if ($default) { 'yes' } else { 'no' }) (-Quiet)"; return $default }
    $hint = if ($default) { "(Y/n)" } else { "(y/N)" }
    $a = Read-Host "        $q $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return $a.Trim().ToLower().StartsWith("y")
}

# ---------------------------------------------------------------- helpers
function Get-Python {
    foreach ($c in @("python", "py")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Test-Ollama {
    try { Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 3 | Out-Null; return $true }
    catch { return $false }
}

function Get-ListenPid([int]$port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return $null
}

function Wait-Port([int]$port, [int]$seconds) {
    for ($i = 0; $i -lt ($seconds * 4); $i++) {
        if (Get-ListenPid $port) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Stop-PortOwner([int]$port, [string]$what) {
    $procId = Get-ListenPid $port
    if (-not $procId) { return $false }
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    $name = if ($p) { $p.ProcessName } else { "unknown" }
    if ($name -notmatch "python|py") {
        Warn "Port $port is held by '$name' (PID $procId), not by Python. Leaving it alone."
        return $false
    }
    Stop-Process -Id $procId -Force
    for ($i = 0; $i -lt 20 -and (Get-ListenPid $port); $i++) { Start-Sleep -Milliseconds 250 }
    Ok "Stopped the $what (PID $procId)"
    return $true
}

function Start-Window([string]$title, [string]$command) {
    # A visible PowerShell window per service, so its log is on screen.
    $full = "`$host.UI.RawUI.WindowTitle = '$title'; Set-Location -LiteralPath '$Repo'; $command; " +
            "Write-Host ''; Write-Host '$title has stopped. You can close this window.' -ForegroundColor Yellow"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-NoExit", "-Command", $full) -WorkingDirectory $Repo | Out-Null
}

function Get-InstalledModels {
    try { return @((Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 5).models | ForEach-Object { $_.name }) }
    catch { return @() }
}

function Select-Model {
    $installed = Get-InstalledModels
    if ($installed.Count -eq 0) { return $null }
    if ($Model) {
        if ($installed -contains $Model) { return $Model }
        Bad "$Model isn't installed. Installed: $($installed -join ', ')"
        return $null
    }
    foreach ($m in $Preferred) { if ($installed -contains $m) { return $m } }
    return $installed[0]
}

function Find-Mgba {
    if ($Mgba -and (Test-Path -LiteralPath $Mgba)) { return $Mgba }
    if (Test-Path -LiteralPath $MgbaCache) {
        $cached = (Get-Content -LiteralPath $MgbaCache -Raw).Trim()
        if ($cached -and (Test-Path -LiteralPath $cached)) { return $cached }
    }
    $candidates = @(
        "$env:ProgramFiles\mGBA\mGBA.exe",
        "${env:ProgramFiles(x86)}\mGBA\mGBA.exe",
        "$env:LOCALAPPDATA\Programs\mGBA\mGBA.exe"
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    $cmd = Get-Command "mGBA" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # Start Menu shortcuts point at wherever the installer put it
    $menus = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
    $shell = New-Object -ComObject WScript.Shell
    foreach ($m in $menus) {
        if (-not (Test-Path -LiteralPath $m)) { continue }
        foreach ($lnk in (Get-ChildItem -LiteralPath $m -Recurse -Filter "mGBA*.lnk" -ErrorAction SilentlyContinue)) {
            $t = $shell.CreateShortcut($lnk.FullName).TargetPath
            if ($t -and (Test-Path -LiteralPath $t) -and $t -like "*.exe") { return $t }
        }
    }
    # portable zips usually live in Downloads, Desktop or Documents
    foreach ($d in @("$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop", "$env:USERPROFILE\Documents", "C:\mGBA", "C:\Tools")) {
        if (-not (Test-Path -LiteralPath $d)) { continue }
        $hit = Get-ChildItem -LiteralPath $d -Recurse -Depth 4 -Filter "mGBA.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Show-HookSteps {
    Info "In mGBA: Tools > Scripting...  then  File > Reset  (always, if a hook was loaded before)"
    Info "then  File > Load recent script > mgba_hook.lua   (or File > Load script... and pick:)"
    Info "    $Hook"
    Info "The scripting console should say: [hook] connected to bridge"
    Info "Why Reset: loading the hook over an old copy on mGBA 0.10.3 dropped the new"
    Info "connection a few seconds later in live testing; Reset first avoids it."
}

function Get-ProcsLike([string]$pattern) {
    # Python processes whose command line matches. Callers wrap the result in
    # @(...): PowerShell unrolls a one-element array on return, and .Count on a
    # lone CimInstance is not 1 -- that exact bug let RESTART_BRIDGE miss a
    # running supervisor and start a second one (found in live testing).
    Get-CimInstance Win32_Process -Filter "Name like 'py%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like $pattern }
}

function Stop-BridgeProcs {
    # Every supervisor (watchdog.py ... dialogue_bridge_server.py) AND every
    # bridge, supervisors first so none of them restarts a bridge we just
    # stopped. Matching the command line also catches strays that hold no port.
    $w = @(Get-ProcsLike "*watchdog.py*dialogue_bridge_server.py*")
    foreach ($p in $w) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    $b = @(Get-ProcsLike "*dialogue_bridge_server.py*" | Where-Object { $_.CommandLine -notlike "*watchdog.py*" })
    foreach ($p in $b) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    for ($i = 0; $i -lt 20 -and (Get-ListenPid $BridgePort); $i++) { Start-Sleep -Milliseconds 250 }
    if ($w.Count -or $b.Count) { Ok "Stopped $($w.Count) supervisor(s) and $($b.Count) bridge process(es)" }
    return ($w.Count + $b.Count)
}

function Close-OldWindows {
    # The "Living Hoenn bridge" / "Living Hoenn dashboard" PowerShell windows
    # this script opened; after their service stops they only say "has
    # stopped". Matched by the exact window-title command they were started
    # with, so no other PowerShell window is touched.
    $w = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*WindowTitle = 'Living Hoenn bridge'*" -or
                       $_.CommandLine -like "*WindowTitle = 'Living Hoenn dashboard'*" })
    foreach ($p in $w) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    if ($w.Count) { Ok "Closed $($w.Count) old bridge/dashboard window(s)" }
}

function Stop-Dashboards {
    $d = @(Get-ProcsLike "*demo\dashboard.py*")
    foreach ($p in $d) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    for ($i = 0; $i -lt 20 -and (Get-ListenPid $DashPort); $i++) { Start-Sleep -Milliseconds 250 }
    if ($d.Count) { Ok "Stopped the dashboard" }
    return $d.Count
}

function Start-Bridge([string]$py, [string]$model) {
    # watchdog.py restarts the bridge within 3 s if it ever exits, forever,
    # so a crash (or Ollama going away and coming back) heals by itself.
    $cmd = "& '$py' 'watchdog.py' --backoff 3 --max-restarts 0 --log 'demo\watchdog.log' -- " +
           "'$py' -u 'bridge\dialogue_bridge_server.py' --model '$model' --trace 'demo\trace.jsonl'"
    Start-Window "Living Hoenn bridge" $cmd
    if (Wait-Port $BridgePort 25) { Ok "Bridge listening on 127.0.0.1:$BridgePort with $model"; return $true }
    Bad "The bridge didn't start. Read the window titled 'Living Hoenn bridge' for the error."
    return $false
}

# ================================================================ STOP
if ($Action -eq "stop") {
    Head "Stopping the demo"
    if ((Stop-BridgeProcs) -eq 0) { Info "Bridge wasn't running" }
    if ((Stop-Dashboards) -eq 0) { Info "Dashboard wasn't running" }
    Stop-PortOwner $BridgePort "leftover bridge" | Out-Null
    Stop-PortOwner $DashPort "leftover dashboard" | Out-Null
    Close-OldWindows
    $mg = Get-Process -Name "mGBA" -ErrorAction SilentlyContinue
    if ($mg) {
        if (Ask "Close mGBA too? Save in the game first, anything unsaved is lost." $false) {
            $mg | Stop-Process; Ok "Closed mGBA"
        } else { Info "Left mGBA open" }
    }
    $m = if (Test-Path -LiteralPath $LastModel) { (Get-Content -LiteralPath $LastModel -Raw).Trim() } else { "" }
    if ($m -and (Test-Ollama)) {
        if (Ask "Unload $m from the GPU?" $false) {
            try { Invoke-RestMethod -Uri "$OllamaUrl/api/generate" -Method Post -ContentType "application/json" -Body (@{ model = $m; keep_alive = 0 } | ConvertTo-Json) -TimeoutSec 30 | Out-Null; Ok "Unloaded $m" }
            catch { Warn "Couldn't unload $m : $($_.Exception.Message)" }
        }
    }
    Head "Done"
    exit 0
}

# ================================================================ common checks
Head "Living Hoenn open-day launcher"
Info "Repo: $Repo"
Set-Location -LiteralPath $Repo

$py = Get-Python
if (-not $py) { Bad "Python isn't on PATH. Install it or open this from the terminal you normally use."; exit 1 }
Ok ("Python: " + (& $py --version 2>&1))

# ================================================================ RESTART BRIDGE
if ($Action -eq "restart-bridge") {
    if (-not (Test-Ollama)) { Bad "Ollama isn't running. Use START_DEMO.bat instead."; exit 1 }
    $m = $Model
    if (-not $m -and (Test-Path -LiteralPath $LastModel)) { $m = (Get-Content -LiteralPath $LastModel -Raw).Trim() }
    if (-not $m) { $m = Select-Model }
    if (-not $m) { Bad "No model found in Ollama."; exit 1 }
    Head "Restarting the bridge"
    # Stop every supervisor and bridge, then start exactly one fresh pair.
    # Deterministic: no relying on an old supervisor to notice and respawn.
    Stop-BridgeProcs | Out-Null
    Stop-PortOwner $BridgePort "leftover bridge" | Out-Null
    # only the bridge window: the dashboard keeps running through a restart
    @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*WindowTitle = 'Living Hoenn bridge'*" }) |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (-not (Start-Bridge $py $m)) { exit 1 }
    Head "Now reconnect the game"
    Info "The hook only connects when it loads, so load it again:"
    Show-HookSteps
    exit 0
}

# ================================================================ START
# ---- 1. Ollama
Head "1. Ollama"
if (Test-Ollama) { Ok "Ollama is running" }
else {
    $app = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    if (Test-Path -LiteralPath $app) { Info "Starting the Ollama app..."; Start-Process -FilePath $app | Out-Null }
    elseif (Get-Command "ollama" -ErrorAction SilentlyContinue) { Info "Starting 'ollama serve'..."; Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Minimized | Out-Null }
    else { Bad "Ollama isn't installed or isn't on PATH."; exit 1 }
    $up = $false
    for ($i = 0; $i -lt 60; $i++) { if (Test-Ollama) { $up = $true; break }; Start-Sleep -Milliseconds 500 }
    if (-not $up) { Bad "Ollama didn't come up within 30 seconds. Start it from the Start menu and run this again."; exit 1 }
    Ok "Ollama is running"
}
$ka = [Environment]::GetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "User")
if ($ka -eq "-1") { Ok "OLLAMA_KEEP_ALIVE=-1, the model stays loaded" }
else { Warn "OLLAMA_KEEP_ALIVE isn't -1 (it's '$ka'). The dashboard keeps the model warm while it's open." }

# ---- 2. Model
Head "2. Model"
$chosen = Select-Model
if (-not $chosen) { Bad "No usable model in Ollama. Pull one first:  ollama pull qwen3:8b"; exit 1 }
Ok "Using $chosen"
if ($chosen -notlike "qwen3*") { Warn "$chosen can't show its thinking. Only reasoning models such as qwen3 can." }
Set-Content -LiteralPath $LastModel -Value $chosen -Encoding ASCII
Info "Loading it onto the GPU (num_ctx $NumCtx, the same as the bridge, so Ollama won't reload it)..."
try {
    $body = @{ model = $chosen; keep_alive = -1; options = @{ num_ctx = $NumCtx } } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Uri "$OllamaUrl/api/generate" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 240 | Out-Null
    $ps = (Invoke-RestMethod -Uri "$OllamaUrl/api/ps" -TimeoutSec 5).models | Where-Object { $_.name -eq $chosen } | Select-Object -First 1
    if ($ps -and $ps.size -gt 0) {
        $pct = [math]::Round(100 * $ps.size_vram / $ps.size)
        if ($pct -ge 100) { Ok "Loaded, 100% on GPU" } else { Warn "Loaded, but only $pct% on GPU. Close other GPU apps (browsers with video, games) for faster replies." }
    } else { Ok "Loaded" }
} catch { Warn "Preload failed ($($_.Exception.Message)). The first NPC will be slower." }

# ---- 3. Tests
Head "3. Tests"
if ($SkipTests) { Info "Skipped (-SkipTests)" }
else {
    & $py "run_all_tests.py"
    if ($LASTEXITCODE -eq 0) { Ok "All tests passed" }
    else {
        Bad "Some tests failed (exit code $LASTEXITCODE)."
        if (-not (Ask "Start the demo anyway?" $false)) { exit 1 }
    }
}

# ---- 4. Old windows
Head "4. Bridge and dashboard"
if ((Get-ListenPid $BridgePort) -or (Get-ListenPid $DashPort) -or (@(Get-ProcsLike "*dialogue_bridge_server.py*").Count -gt 0)) {
    Warn "A bridge or dashboard from an earlier run is still going."
    if (Ask "Stop them and start fresh?" $true) {
        Stop-BridgeProcs | Out-Null
        Stop-Dashboards | Out-Null
        Stop-PortOwner $BridgePort "old bridge" | Out-Null
        Stop-PortOwner $DashPort "old dashboard" | Out-Null
        Close-OldWindows
    } else { Bad "Can't start a second copy on the same ports. Run STOP_DEMO.bat first."; exit 1 }
}
# keep earlier traces: move, never delete
if (Test-Path -LiteralPath $Trace) {
    $arch = Join-Path $DemoDir "trace-archive"
    New-Item -ItemType Directory -Force -Path $arch | Out-Null
    $dest = Join-Path $arch ("trace-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".jsonl")
    Move-Item -LiteralPath $Trace -Destination $dest
    Info "Previous trace saved to demo\trace-archive\"
}

# ---- 5. Bridge, then dashboard
if (-not (Start-Bridge $py $chosen)) { exit 1 }
Start-Window "Living Hoenn dashboard" "& '$py' 'demo\dashboard.py' --model '$chosen'"
if (Wait-Port $DashPort 15) { Ok "Dashboard at http://127.0.0.1:$DashPort/ (opening in your browser)" }
else { Warn "The dashboard didn't start. Read the window titled 'Living Hoenn dashboard'." }

# ---- 6. mGBA
Head "5. mGBA"
if ($NoMgba) { Info "Skipped (-NoMgba)"; Show-HookSteps }
else {
    $running = Get-Process -Name "mGBA" -ErrorAction SilentlyContinue
    $launch = $true
    if ($running) {
        Warn "mGBA is already open. Its hook (if loaded) was talking to the old bridge."
        if (Ask "Close it and open a fresh copy? Save in the game first, anything unsaved is lost." $false) { $running | Stop-Process; Start-Sleep -Seconds 1 }
        else { $launch = $false; Info "Left it open. Reload the hook in that window:"; Show-HookSteps }
    }
    if ($launch) {
        $exe = Find-Mgba
        if (-not $exe) {
            Warn "Couldn't find mGBA.exe. Open mGBA yourself, load the ROM, then:"
            Show-HookSteps
            Info "Next time:  START_DEMO.bat -Mgba ""C:\path\to\mGBA.exe""  and it will remember."
        } elseif (-not (Test-Path -LiteralPath $Rom)) {
            Warn "ROM not found at $Rom. Run with -Rom ""C:\path\to\pokeemerald.gba""."
        } else {
            Set-Content -LiteralPath $MgbaCache -Value $exe -Encoding ASCII
            $romArgs = @()
            if ($State -ge 1 -and $State -le 9) {
                $ss = [IO.Path]::ChangeExtension($Rom, ".ss$State")
                if (Test-Path -LiteralPath $ss) { $romArgs += @("-t", "`"$ss`"") } else { Warn "No savestate slot $State next to the ROM, starting normally" }
            }
            $romArgs += "`"$Rom`""
            Info "mGBA: $exe"
            # --script exists in newer mGBA builds only; older ones exit at once on it.
            $p = Start-Process -FilePath $exe -ArgumentList (@("--script", "`"$Hook`"") + $romArgs) -WorkingDirectory $Repo -PassThru
            Start-Sleep -Seconds 3
            if ($p.HasExited) {
                Warn "This mGBA version can't load scripts from the command line. Opening it normally..."
                Start-Process -FilePath $exe -ArgumentList $romArgs -WorkingDirectory $Repo | Out-Null
                Show-HookSteps
            } else {
                Info "Waiting for the hook to connect to the bridge..."
                $connected = $false
                for ($i = 0; $i -lt 40; $i++) {
                    if (Get-NetTCPConnection -LocalPort $BridgePort -State Established -ErrorAction SilentlyContinue) { $connected = $true; break }
                    Start-Sleep -Milliseconds 500
                }
                if ($connected) { Ok "Hook connected. The game is live." }
                else { Warn "mGBA is open but the hook hasn't connected yet. Load it by hand:"; Show-HookSteps }
            }
        }
    }
}

Head "Ready"
Info "Dashboard:      http://127.0.0.1:$DashPort/"
Info "Model:          $chosen"
Info "If the bridge crashes it restarts by itself; then reload the hook in mGBA."
Info "Need a manual restart? RESTART_BRIDGE.bat"
Info "All done?       Double-click STOP_DEMO.bat"
Write-Host ""
