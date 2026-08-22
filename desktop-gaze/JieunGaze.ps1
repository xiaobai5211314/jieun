[CmdletBinding()]
param(
    [string]$RigPath,
    [ValidateRange(360, 900)]
    [int]$DisplayHeight = 640,
    [ValidateSet('BottomRight', 'BottomLeft', 'TopRight', 'TopLeft')]
    [string]$Anchor = 'BottomRight',
    [ValidateRange(0, 200)]
    [int]$Margin = 24,
    [switch]$SelfTest,
    [ValidateRange(0, 60)]
    [int]$RuntimeTestSeconds = 0
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RigPath)) {
    $RigPath = Join-Path $PSScriptRoot '..\design-v4\gaze-rig'
}
$resolvedRig = (Resolve-Path -LiteralPath $RigPath).Path
$configPath = Join-Path $resolvedRig 'gaze-rig.json'
$basePath = Join-Path $resolvedRig 'base.png'
$leftIrisPath = Join-Path $resolvedRig 'left-iris.png'
$rightIrisPath = Join-Path $resolvedRig 'right-iris.png'
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

function Load-UnlockedBitmap {
    param([Parameter(Mandatory)][string]$Path)
    $source = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Path).Path)
    try {
        return [System.Drawing.Bitmap]::new($source)
    }
    finally {
        $source.Dispose()
    }
}

$baseBitmap = Load-UnlockedBitmap -Path $basePath
$leftIrisBitmap = Load-UnlockedBitmap -Path $leftIrisPath
$rightIrisBitmap = Load-UnlockedBitmap -Path $rightIrisPath

if (
    $baseBitmap.Width -ne [int]$config.canvasSize[0] -or
    $baseBitmap.Height -ne [int]$config.canvasSize[1]
) {
    throw 'Gaze rig base image does not match gaze-rig.json.'
}

if ($SelfTest) {
    try {
        [pscustomobject]@{
            Ok = $true
            RigPath = $resolvedRig
            CanvasWidth = $baseBitmap.Width
            CanvasHeight = $baseBitmap.Height
            DisplayHeight = $DisplayHeight
            BodyMoves = $false
            EyesTrackCursor = $true
            PerPixelAlpha = $true
            LayeredWindow = $true
            MaxGaze = @([int]$config.maxGaze[0], [int]$config.maxGaze[1])
            StartupPersistence = $false
        } | ConvertTo-Json -Depth 4
    }
    finally {
        $baseBitmap.Dispose()
        $leftIrisBitmap.Dispose()
        $rightIrisBitmap.Dispose()
    }
    exit 0
}

$createdNew = $false
$instanceMutex = [System.Threading.Mutex]::new(
    $true,
    'Local\CodexJieunGaze',
    [ref]$createdNew
)
if (-not $createdNew) {
    $baseBitmap.Dispose()
    $leftIrisBitmap.Dispose()
    $rightIrisBitmap.Dispose()
    $instanceMutex.Dispose()
    exit 0
}

if (-not ('JieunGazeLayeredWindow' -as [type])) {
    Add-Type -ReferencedAssemblies System.Drawing @'
using System;
using System.Drawing;
using System.Runtime.InteropServices;

public static class JieunGazeLayeredWindow
{
    private const int GWL_EXSTYLE = -20;
    private const int WS_EX_LAYERED = 0x00080000;
    private const int WS_EX_TRANSPARENT = 0x00000020;
    private const int WS_EX_TOOLWINDOW = 0x00000080;
    private const int WS_EX_NOACTIVATE = 0x08000000;
    private const int ULW_ALPHA = 0x00000002;
    private const byte AC_SRC_OVER = 0x00;
    private const byte AC_SRC_ALPHA = 0x01;

    [StructLayout(LayoutKind.Sequential)]
    private struct PointValue
    {
        public int X;
        public int Y;
        public PointValue(int x, int y) { X = x; Y = y; }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SizeValue
    {
        public int Width;
        public int Height;
        public SizeValue(int width, int height) { Width = width; Height = height; }
    }

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    private struct BlendFunction
    {
        public byte BlendOp;
        public byte BlendFlags;
        public byte SourceConstantAlpha;
        public byte AlphaFormat;
    }

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll")]
    private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int value);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr GetDC(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);

    [DllImport("gdi32.dll", SetLastError = true)]
    private static extern IntPtr CreateCompatibleDC(IntPtr hDC);

    [DllImport("gdi32.dll", SetLastError = true)]
    private static extern bool DeleteDC(IntPtr hDC);

    [DllImport("gdi32.dll", SetLastError = true)]
    private static extern IntPtr SelectObject(IntPtr hDC, IntPtr hObject);

    [DllImport("gdi32.dll", SetLastError = true)]
    private static extern bool DeleteObject(IntPtr hObject);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UpdateLayeredWindow(
        IntPtr hWnd,
        IntPtr destinationDc,
        ref PointValue destinationPoint,
        ref SizeValue size,
        IntPtr sourceDc,
        ref PointValue sourcePoint,
        int colorKey,
        ref BlendFunction blend,
        int flags
    );

    public static void Configure(IntPtr handle)
    {
        int style = GetWindowLong(handle, GWL_EXSTYLE);
        SetWindowLong(
            handle,
            GWL_EXSTYLE,
            style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        );
    }

    public static void Render(IntPtr handle, Bitmap bitmap, int left, int top)
    {
        IntPtr screenDc = GetDC(IntPtr.Zero);
        IntPtr memoryDc = CreateCompatibleDC(screenDc);
        IntPtr hBitmap = IntPtr.Zero;
        IntPtr previous = IntPtr.Zero;
        try
        {
            hBitmap = bitmap.GetHbitmap(Color.FromArgb(0));
            previous = SelectObject(memoryDc, hBitmap);
            PointValue destination = new PointValue(left, top);
            PointValue source = new PointValue(0, 0);
            SizeValue size = new SizeValue(bitmap.Width, bitmap.Height);
            BlendFunction blend = new BlendFunction
            {
                BlendOp = AC_SRC_OVER,
                BlendFlags = 0,
                SourceConstantAlpha = 255,
                AlphaFormat = AC_SRC_ALPHA
            };
            if (!UpdateLayeredWindow(
                handle,
                screenDc,
                ref destination,
                ref size,
                memoryDc,
                ref source,
                0,
                ref blend,
                ULW_ALPHA
            ))
            {
                throw new System.ComponentModel.Win32Exception();
            }
        }
        finally
        {
            if (previous != IntPtr.Zero) SelectObject(memoryDc, previous);
            if (hBitmap != IntPtr.Zero) DeleteObject(hBitmap);
            if (memoryDc != IntPtr.Zero) DeleteDC(memoryDc);
            if (screenDc != IntPtr.Zero) ReleaseDC(IntPtr.Zero, screenDc);
        }
    }
}
'@
}

function Resize-PremultipliedBitmap {
    param(
        [Parameter(Mandatory)][System.Drawing.Bitmap]$Bitmap,
        [Parameter(Mandatory)][int]$Width,
        [Parameter(Mandatory)][int]$Height
    )
    $result = [System.Drawing.Bitmap]::new(
        $Width,
        $Height,
        [System.Drawing.Imaging.PixelFormat]::Format32bppPArgb
    )
    $graphics = [System.Drawing.Graphics]::FromImage($result)
    try {
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.DrawImage(
            $Bitmap,
            [System.Drawing.Rectangle]::new(0, 0, $Width, $Height)
        )
    }
    finally {
        $graphics.Dispose()
    }
    return $result
}

$scale = $DisplayHeight / [double]$baseBitmap.Height
$displayWidth = [Math]::Max(1, [int][Math]::Round($baseBitmap.Width * $scale))
$baseDisplay = Resize-PremultipliedBitmap -Bitmap $baseBitmap -Width $displayWidth -Height $DisplayHeight
$leftIrisDisplay = Resize-PremultipliedBitmap `
    -Bitmap $leftIrisBitmap `
    -Width ([Math]::Max(1, [int][Math]::Round($leftIrisBitmap.Width * $scale))) `
    -Height ([Math]::Max(1, [int][Math]::Round($leftIrisBitmap.Height * $scale)))
$rightIrisDisplay = Resize-PremultipliedBitmap `
    -Bitmap $rightIrisBitmap `
    -Width ([Math]::Max(1, [int][Math]::Round($rightIrisBitmap.Width * $scale))) `
    -Height ([Math]::Max(1, [int][Math]::Round($rightIrisBitmap.Height * $scale)))
$baseBitmap.Dispose()
$leftIrisBitmap.Dispose()
$rightIrisBitmap.Dispose()

$form = [System.Windows.Forms.Form]::new()
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.ClientSize = [System.Drawing.Size]::new($displayWidth, $DisplayHeight)
$form.Text = 'Jieun Gaze'

$script:gazeX = 0.0
$script:gazeY = 0.0
$script:paused = $false

function Render-GazeFrame {
    $frame = [System.Drawing.Bitmap]::new($baseDisplay)
    $graphics = [System.Drawing.Graphics]::FromImage($frame)
    try {
        $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $leftX = [int][Math]::Round(
            ([double]$config.eyes.left.position[0] + $script:gazeX) * $scale
        )
        $leftY = [int][Math]::Round(
            ([double]$config.eyes.left.position[1] + $script:gazeY) * $scale
        )
        $rightX = [int][Math]::Round(
            ([double]$config.eyes.right.position[0] + $script:gazeX) * $scale
        )
        $rightY = [int][Math]::Round(
            ([double]$config.eyes.right.position[1] + $script:gazeY) * $scale
        )
        $graphics.DrawImage($leftIrisDisplay, $leftX, $leftY)
        $graphics.DrawImage($rightIrisDisplay, $rightX, $rightY)
    }
    finally {
        $graphics.Dispose()
    }
    try {
        [JieunGazeLayeredWindow]::Render(
            $form.Handle,
            $frame,
            $form.Left,
            $form.Top
        )
    }
    finally {
        $frame.Dispose()
    }
}

$form.Add_Shown({
    $cursor = [System.Windows.Forms.Cursor]::Position
    $workingArea = [System.Windows.Forms.Screen]::FromPoint($cursor).WorkingArea
    switch ($Anchor) {
        'BottomRight' {
            $form.Left = $workingArea.Right - $form.Width - $Margin
            $form.Top = $workingArea.Bottom - $form.Height - $Margin
        }
        'BottomLeft' {
            $form.Left = $workingArea.Left + $Margin
            $form.Top = $workingArea.Bottom - $form.Height - $Margin
        }
        'TopRight' {
            $form.Left = $workingArea.Right - $form.Width - $Margin
            $form.Top = $workingArea.Top + $Margin
        }
        'TopLeft' {
            $form.Left = $workingArea.Left + $Margin
            $form.Top = $workingArea.Top + $Margin
        }
    }
    [JieunGazeLayeredWindow]::Configure($form.Handle)
    Render-GazeFrame
})

$timer = [System.Windows.Forms.Timer]::new()
$timer.Interval = 16
$timer.Add_Tick({
    $targetX = 0.0
    $targetY = 0.0
    if (-not $script:paused) {
        $cursor = [System.Windows.Forms.Cursor]::Position
        $eyeCenterX = $form.Left + (
            ([double]$config.eyes.left.center[0] + [double]$config.eyes.right.center[0]) / 2.0
        ) * $scale
        $eyeCenterY = $form.Top + (
            ([double]$config.eyes.left.center[1] + [double]$config.eyes.right.center[1]) / 2.0
        ) * $scale
        $dx = $cursor.X - $eyeCenterX
        $dy = $cursor.Y - $eyeCenterY
        $length = [Math]::Sqrt(($dx * $dx) + ($dy * $dy))
        if ($length -gt 1.0) {
            $targetX = ($dx / $length) * [double]$config.maxGaze[0]
            $targetY = ($dy / $length) * [double]$config.maxGaze[1]
        }
    }
    $script:gazeX += ($targetX - $script:gazeX) * 0.22
    $script:gazeY += ($targetY - $script:gazeY) * 0.22
    Render-GazeFrame
})

$menu = [System.Windows.Forms.ContextMenuStrip]::new()
$pauseItem = $menu.Items.Add('Pause gaze')
$exitItem = $menu.Items.Add('Exit')
$pauseItem.Add_Click({
    $script:paused = -not $script:paused
    $pauseItem.Text = if ($script:paused) { 'Resume gaze' } else { 'Pause gaze' }
})
$exitItem.Add_Click({ $form.Close() })

$tray = [System.Windows.Forms.NotifyIcon]::new()
$tray.Icon = [System.Drawing.SystemIcons]::Application
$tray.Text = 'Jieun Gaze'
$tray.ContextMenuStrip = $menu
$tray.Visible = $true

$runtimeTestTimer = $null
if ($RuntimeTestSeconds -gt 0) {
    $runtimeTestTimer = [System.Windows.Forms.Timer]::new()
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
    $baseDisplay.Dispose()
    $leftIrisDisplay.Dispose()
    $rightIrisDisplay.Dispose()
    $instanceMutex.ReleaseMutex()
    $instanceMutex.Dispose()
})

$timer.Start()
[System.Windows.Forms.Application]::Run($form)
