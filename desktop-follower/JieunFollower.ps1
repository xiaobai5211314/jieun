[CmdletBinding()]
param(
    [string]$AtlasPath,
    [ValidateRange(1, 3)]
    [int]$Scale = 1,
    [switch]$SelfTest,
    [ValidateRange(0, 60)]
    [int]$RuntimeTestSeconds = 0
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($AtlasPath)) {
    $AtlasPath = Join-Path $PSScriptRoot '..\spritesheet.png'
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$resolvedAtlas = (Resolve-Path -LiteralPath $AtlasPath).Path
$sourceImage = [System.Drawing.Image]::FromFile($resolvedAtlas)
try {
    if ($sourceImage.Width -ne 1536 -or $sourceImage.Height -ne 1872) {
        throw "Expected a 1536x1872 atlas, got $($sourceImage.Width)x$($sourceImage.Height)."
    }
    $atlas = New-Object System.Drawing.Bitmap $sourceImage
}
finally {
    $sourceImage.Dispose()
}

$states = [ordered]@{
    idle     = @{ Row = 0; Durations = @(280, 110, 110, 140, 140, 320) }
    runRight = @{ Row = 1; Durations = @(120, 120, 120, 120, 120, 120, 120, 220) }
    runLeft  = @{ Row = 2; Durations = @(120, 120, 120, 120, 120, 120, 120, 220) }
    wave     = @{ Row = 3; Durations = @(140, 140, 140, 280) }
    jump     = @{ Row = 4; Durations = @(140, 140, 140, 140, 280) }
    failed   = @{ Row = 5; Durations = @(140, 140, 140, 140, 140, 140, 140, 240) }
    waiting  = @{ Row = 6; Durations = @(150, 150, 150, 150, 150, 260) }
    work     = @{ Row = 7; Durations = @(120, 120, 120, 120, 120, 220) }
    review   = @{ Row = 8; Durations = @(150, 150, 150, 150, 150, 280) }
}

if ($SelfTest) {
    try {
        [pscustomobject]@{
            Ok = $true
            AtlasPath = $resolvedAtlas
            Width = $atlas.Width
            Height = $atlas.Height
            States = @($states.Keys)
            StateCount = $states.Count
            ClickThrough = $true
            StartupPersistence = $false
        } | ConvertTo-Json -Depth 4
    }
    finally {
        $atlas.Dispose()
    }
    exit 0
}

if (-not ('JieunFollowerNative' -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;

public static class JieunFollowerNative
{
    private const int GWL_EXSTYLE = -20;
    private const int WS_EX_TRANSPARENT = 0x00000020;
    private const int WS_EX_TOOLWINDOW = 0x00000080;
    private const int WS_EX_NOACTIVATE = 0x08000000;

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll")]
    private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int vKey);

    public static void MakeClickThrough(IntPtr handle)
    {
        int style = GetWindowLong(handle, GWL_EXSTYLE);
        SetWindowLong(
            handle,
            GWL_EXSTYLE,
            style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        );
    }
}
'@
}

$cellWidth = 192
$cellHeight = 208
$transparentColor = [System.Drawing.Color]::FromArgb(1, 2, 3)

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.BackColor = $transparentColor
$form.TransparencyKey = $transparentColor
$form.ClientSize = New-Object System.Drawing.Size ($cellWidth * $Scale), ($cellHeight * $Scale)
$form.Text = 'Jieun Follower'

$doubleBuffered = $form.GetType().GetProperty(
    'DoubleBuffered',
    [System.Reflection.BindingFlags]'Instance,NonPublic'
)
$doubleBuffered.SetValue($form, $true, $null)

$script:stateName = 'idle'
$script:frameIndex = 0
$script:frameElapsed = 0.0
$script:lastTick = [Environment]::TickCount64
$script:specialUntil = 0L
$script:nextIdleAction = $script:lastTick + 4500
$script:lastCursor = [System.Windows.Forms.Cursor]::Position
$script:leftButtonWasDown = $false
$script:paused = $false
$random = [System.Random]::new()

function Set-PetState {
    param([Parameter(Mandatory)][string]$Name)
    if ($script:stateName -ne $Name) {
        $script:stateName = $Name
        $script:frameIndex = 0
        $script:frameElapsed = 0.0
    }
}

function Start-SpecialState {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$DurationMs,
        [Parameter(Mandatory)][long]$Now
    )
    Set-PetState -Name $Name
    $script:specialUntil = $Now + $DurationMs
}

$form.Add_Shown({
    [JieunFollowerNative]::MakeClickThrough($form.Handle)
    $cursor = [System.Windows.Forms.Cursor]::Position
    $form.Left = $cursor.X - $form.Width - 28
    $form.Top = $cursor.Y + 24
})

$form.Add_Paint({
    param($sender, $eventArgs)

    $state = $states[$script:stateName]
    $source = New-Object System.Drawing.Rectangle `
        ($script:frameIndex * $cellWidth), `
        ($state.Row * $cellHeight), `
        $cellWidth, `
        $cellHeight
    $destination = New-Object System.Drawing.Rectangle 0, 0, $form.ClientSize.Width, $form.ClientSize.Height

    $eventArgs.Graphics.Clear($transparentColor)
    $eventArgs.Graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
    $eventArgs.Graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $eventArgs.Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $eventArgs.Graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $eventArgs.Graphics.DrawImage(
        $atlas,
        $destination,
        $source,
        [System.Drawing.GraphicsUnit]::Pixel
    )
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 16
$timer.Add_Tick({
    $now = [Environment]::TickCount64
    $elapsed = [Math]::Max(1, $now - $script:lastTick)
    $script:lastTick = $now

    if ($script:paused) {
        Set-PetState -Name 'idle'
    }
    else {
        $cursor = [System.Windows.Forms.Cursor]::Position
        $screen = [System.Windows.Forms.Screen]::FromPoint($cursor).WorkingArea

        $offsetX = -$form.Width - 28
        if (($cursor.X + $offsetX) -lt $screen.Left) {
            $offsetX = 28
        }

        $targetX = $cursor.X + $offsetX
        $targetY = $cursor.Y + 34
        $targetX = [Math]::Max($screen.Left, [Math]::Min($targetX, $screen.Right - $form.Width))
        $targetY = [Math]::Max($screen.Top, [Math]::Min($targetY, $screen.Bottom - $form.Height))

        $dx = $targetX - $form.Left
        $dy = $targetY - $form.Top
        $distance = [Math]::Sqrt(($dx * $dx) + ($dy * $dy))

        $leftButtonDown = (([JieunFollowerNative]::GetAsyncKeyState(1) -band 0x8000) -ne 0)
        $leftClick = $leftButtonDown -and -not $script:leftButtonWasDown
        $script:leftButtonWasDown = $leftButtonDown

        if ($leftClick -and $distance -lt 220) {
            Start-SpecialState -Name 'jump' -DurationMs 1050 -Now $now
        }

        if ($distance -gt 16) {
            $moveFactor = [Math]::Min(1.0, 0.13 * ($elapsed / 16.0))
            $form.Left = [int]($form.Left + ($dx * $moveFactor))
            $form.Top = [int]($form.Top + ($dy * $moveFactor))

            if ([Math]::Abs($dx) -ge 2) {
                if ($dx -gt 0) {
                    Set-PetState -Name 'runRight'
                }
                else {
                    Set-PetState -Name 'runLeft'
                }
                $script:specialUntil = 0
            }
        }
        elseif ($now -ge $script:specialUntil) {
            Set-PetState -Name 'idle'
            if ($now -ge $script:nextIdleAction) {
                $choices = @('wave', 'waiting', 'work', 'review')
                $choice = $choices[$random.Next(0, $choices.Count)]
                Start-SpecialState -Name $choice -DurationMs ($random.Next(1500, 2400)) -Now $now
                $script:nextIdleAction = $now + $random.Next(5000, 9500)
            }
        }

        $cursorTravel = [Math]::Abs($cursor.X - $script:lastCursor.X) + [Math]::Abs($cursor.Y - $script:lastCursor.Y)
        if ($cursorTravel -gt 0) {
            $script:lastCursor = $cursor
        }
    }

    $state = $states[$script:stateName]
    $script:frameElapsed += $elapsed
    $duration = $state.Durations[$script:frameIndex]
    while ($script:frameElapsed -ge $duration) {
        $script:frameElapsed -= $duration
        $script:frameIndex = ($script:frameIndex + 1) % $state.Durations.Count
        $duration = $state.Durations[$script:frameIndex]
    }

    $form.Invalidate()
})

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$pauseItem = $menu.Items.Add('Pause')
$exitItem = $menu.Items.Add('Exit')
$pauseItem.Add_Click({
    $script:paused = -not $script:paused
    $pauseItem.Text = if ($script:paused) { 'Resume' } else { 'Pause' }
})
$exitItem.Add_Click({ $form.Close() })

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = [System.Drawing.SystemIcons]::Application
$tray.Text = 'Jieun Follower'
$tray.ContextMenuStrip = $menu
$tray.Visible = $true

$runtimeTestTimer = $null
if ($RuntimeTestSeconds -gt 0) {
    $runtimeTestTimer = New-Object System.Windows.Forms.Timer
    $runtimeTestTimer.Interval = $RuntimeTestSeconds * 1000
    $runtimeTestTimer.Add_Tick({
        $runtimeTestTimer.Stop()
        $form.Close()
    })
    $runtimeTestTimer.Start()
}

$form.Add_FormClosed({
    $timer.Stop()
    if ($null -ne $runtimeTestTimer) {
        $runtimeTestTimer.Dispose()
    }
    $tray.Visible = $false
    $tray.Dispose()
    $menu.Dispose()
    $atlas.Dispose()
})

$timer.Start()
[System.Windows.Forms.Application]::Run($form)
