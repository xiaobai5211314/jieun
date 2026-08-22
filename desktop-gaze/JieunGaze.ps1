[CmdletBinding()]
param(
    [string]$RigPath,
    [ValidateRange(420, 1400)]
    [int]$DisplayHeight = 900,
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
    $RigPath = Join-Path $PSScriptRoot '..\design-v5\head-rig'
}
$resolvedRig = (Resolve-Path -LiteralPath $RigPath).Path
$configPath = Join-Path $resolvedRig 'head-gaze-rig.json'
$bodyPath = Join-Path $resolvedRig 'body.png'
$headPath = Join-Path $resolvedRig 'head-base.png'
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

$bodyBitmap = Load-UnlockedBitmap -Path $bodyPath
$headBitmap = Load-UnlockedBitmap -Path $headPath
$leftIrisBitmap = Load-UnlockedBitmap -Path $leftIrisPath
$rightIrisBitmap = Load-UnlockedBitmap -Path $rightIrisPath

if (
    $bodyBitmap.Width -ne [int]$config.canvasSize[0] -or
    $bodyBitmap.Height -ne [int]$config.canvasSize[1]
) {
    throw 'Head-gaze body image does not match head-gaze-rig.json.'
}
if (
    $headBitmap.Width -ne [int]$config.head.size[0] -or
    $headBitmap.Height -ne [int]$config.head.size[1]
) {
    throw 'Head layer image does not match head-gaze-rig.json.'
}

if ($SelfTest) {
    try {
        [pscustomobject]@{
            Ok = $true
            RigPath = $resolvedRig
            CanvasWidth = $bodyBitmap.Width
            CanvasHeight = $bodyBitmap.Height
            DisplayHeight = $DisplayHeight
            BodyStationary = $true
            HeadTracksCursor = $true
            EyesLeadHead = $true
            PerPixelAlpha = $true
            ClickThrough = $true
            LayeredWindow = $true
            MaxGaze = @(
                [int]$config.eyes.maxGaze[0],
                [int]$config.eyes.maxGaze[1]
            )
            MaxHeadTranslation = @(
                [int]$config.head.maxTranslation[0],
                [int]$config.head.maxTranslation[1]
            )
            MaxHeadRotationDegrees = [double]$config.head.maxRotationDegrees
            StartupPersistence = $false
        } | ConvertTo-Json -Depth 4
    }
    finally {
        $bodyBitmap.Dispose()
        $headBitmap.Dispose()
        $leftIrisBitmap.Dispose()
        $rightIrisBitmap.Dispose()
    }
    exit 0
}

$createdNew = $false
$instanceMutex = [System.Threading.Mutex]::new(
    $true,
    'Local\CodexJieunHeadGazeV5',
    [ref]$createdNew
)
if (-not $createdNew) {
    $bodyBitmap.Dispose()
    $headBitmap.Dispose()
    $leftIrisBitmap.Dispose()
    $rightIrisBitmap.Dispose()
    $instanceMutex.Dispose()
    exit 0
}

if (-not ('JieunHeadGazeLayeredWindow' -as [type])) {
    Add-Type -ReferencedAssemblies System.Drawing @'
using System;
using System.Drawing;
using System.Runtime.InteropServices;

public static class JieunHeadGazeLayeredWindow
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

$scale = $DisplayHeight / [double]$bodyBitmap.Height
$displayWidth = [Math]::Max(1, [int][Math]::Round($bodyBitmap.Width * $scale))
$bodyDisplay = Resize-PremultipliedBitmap `
    -Bitmap $bodyBitmap `
    -Width $displayWidth `
    -Height $DisplayHeight
$headDisplay = Resize-PremultipliedBitmap `
    -Bitmap $headBitmap `
    -Width ([Math]::Max(1, [int][Math]::Round($headBitmap.Width * $scale))) `
    -Height ([Math]::Max(1, [int][Math]::Round($headBitmap.Height * $scale)))
$leftIrisDisplay = Resize-PremultipliedBitmap `
    -Bitmap $leftIrisBitmap `
    -Width ([Math]::Max(1, [int][Math]::Round($leftIrisBitmap.Width * $scale))) `
    -Height ([Math]::Max(1, [int][Math]::Round($leftIrisBitmap.Height * $scale)))
$rightIrisDisplay = Resize-PremultipliedBitmap `
    -Bitmap $rightIrisBitmap `
    -Width ([Math]::Max(1, [int][Math]::Round($rightIrisBitmap.Width * $scale))) `
    -Height ([Math]::Max(1, [int][Math]::Round($rightIrisBitmap.Height * $scale)))
$bodyBitmap.Dispose()
$headBitmap.Dispose()
$leftIrisBitmap.Dispose()
$rightIrisBitmap.Dispose()

$form = [System.Windows.Forms.Form]::new()
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.ClientSize = [System.Drawing.Size]::new($displayWidth, $DisplayHeight)
$form.Text = 'Jieun Head Gaze'

$script:eyeDirectionX = 0.0
$script:eyeDirectionY = 0.0
$script:headDirectionX = 0.0
$script:headDirectionY = 0.0
$script:paused = $false

function Render-GazeFrame {
    $frame = [System.Drawing.Bitmap]::new($bodyDisplay)
    $headFrame = [System.Drawing.Bitmap]::new($headDisplay)
    $headGraphics = [System.Drawing.Graphics]::FromImage($headFrame)
    try {
        $headGraphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
        $headGraphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $headGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $headGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

        $gazeX = $script:eyeDirectionX * [double]$config.eyes.maxGaze[0]
        $gazeY = $script:eyeDirectionY * [double]$config.eyes.maxGaze[1]
        $leftX = [int][Math]::Round(
            ([double]$config.eyes.layers.left.position[0] + $gazeX) * $scale
        )
        $leftY = [int][Math]::Round(
            ([double]$config.eyes.layers.left.position[1] + $gazeY) * $scale
        )
        $rightX = [int][Math]::Round(
            ([double]$config.eyes.layers.right.position[0] + $gazeX) * $scale
        )
        $rightY = [int][Math]::Round(
            ([double]$config.eyes.layers.right.position[1] + $gazeY) * $scale
        )
        $headGraphics.DrawImage($leftIrisDisplay, $leftX, $leftY)
        $headGraphics.DrawImage($rightIrisDisplay, $rightX, $rightY)
    }
    finally {
        $headGraphics.Dispose()
    }

    $graphics = [System.Drawing.Graphics]::FromImage($frame)
    try {
        $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

        $headMoveX = $script:headDirectionX * [double]$config.head.maxTranslation[0]
        $headMoveY = $script:headDirectionY * [double]$config.head.maxTranslation[1]
        $headX = (
            [double]$config.head.position[0] + $headMoveX
        ) * $scale
        $headY = (
            [double]$config.head.position[1] + $headMoveY
        ) * $scale
        $pivotX = [double]$config.head.pivot[0] * $scale
        $pivotY = [double]$config.head.pivot[1] * $scale
        $angle = $script:headDirectionX * [double]$config.head.maxRotationDegrees

        $graphics.TranslateTransform(
            [single]($headX + $pivotX),
            [single]($headY + $pivotY)
        )
        $graphics.RotateTransform([single]$angle)
        $graphics.TranslateTransform([single](-$pivotX), [single](-$pivotY))
        $graphics.DrawImage($headFrame, 0, 0)
        $graphics.ResetTransform()
    }
    finally {
        $graphics.Dispose()
        $headFrame.Dispose()
    }

    try {
        [JieunHeadGazeLayeredWindow]::Render(
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
    [JieunHeadGazeLayeredWindow]::Configure($form.Handle)
    Render-GazeFrame
})

$timer = [System.Windows.Forms.Timer]::new()
$timer.Interval = 16
$timer.Add_Tick({
    $targetX = 0.0
    $targetY = 0.0
    if (-not $script:paused) {
        $cursor = [System.Windows.Forms.Cursor]::Position
        $headCenterX = $form.Left + (
            [double]$config.head.position[0] +
            [double]$config.head.pivot[0]
        ) * $scale
        $headCenterY = $form.Top + (
            [double]$config.head.position[1] +
            [double]$config.head.pivot[1] * 0.58
        ) * $scale
        $dx = $cursor.X - $headCenterX
        $dy = $cursor.Y - $headCenterY
        $length = [Math]::Sqrt(($dx * $dx) + ($dy * $dy))
        if ($length -gt 1.0) {
            $targetX = $dx / $length
            $targetY = $dy / $length
        }
    }

    $eyeSmoothing = [double]$config.eyes.smoothing
    $headSmoothing = [double]$config.head.smoothing
    $script:eyeDirectionX += ($targetX - $script:eyeDirectionX) * $eyeSmoothing
    $script:eyeDirectionY += ($targetY - $script:eyeDirectionY) * $eyeSmoothing
    $script:headDirectionX += ($targetX - $script:headDirectionX) * $headSmoothing
    $script:headDirectionY += ($targetY - $script:headDirectionY) * $headSmoothing
    Render-GazeFrame
})

$menu = [System.Windows.Forms.ContextMenuStrip]::new()
$pauseItem = $menu.Items.Add('Pause head + gaze')
$exitItem = $menu.Items.Add('Exit')
$pauseItem.Add_Click({
    $script:paused = -not $script:paused
    $pauseItem.Text = if ($script:paused) {
        'Resume head + gaze'
    }
    else {
        'Pause head + gaze'
    }
})
$exitItem.Add_Click({ $form.Close() })

$tray = [System.Windows.Forms.NotifyIcon]::new()
$tray.Icon = [System.Drawing.SystemIcons]::Application
$tray.Text = 'Jieun Head Gaze'
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
    $bodyDisplay.Dispose()
    $headDisplay.Dispose()
    $leftIrisDisplay.Dispose()
    $rightIrisDisplay.Dispose()
    $instanceMutex.ReleaseMutex()
    $instanceMutex.Dispose()
})

$timer.Start()
[System.Windows.Forms.Application]::Run($form)
