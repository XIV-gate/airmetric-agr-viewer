param([Parameter(Mandatory=$true)][string]$Script,
      [Parameter(Mandatory=$true)][string]$TestRoot,
      [Parameter(Mandatory=$true)][string]$Blender,
      [string]$Fixtures = '', [string]$BlendFile = '',
      [switch]$Gui, [string]$LogName = 'viewer_gui')
$ErrorActionPreference = 'Stop'
$ResolvedRoot = (Resolve-Path -LiteralPath $TestRoot).Path
$ApprovedRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../Workspace/Temp/AirmetricAGRViewer')).Path
if ($ResolvedRoot -ne $ApprovedRoot -or -not $ResolvedRoot.StartsWith('D:\')) {
    throw 'Unapproved Blender isolation root'
}
$env:BLENDER_USER_CONFIG = Join-Path $ResolvedRoot 'config'
$env:BLENDER_USER_SCRIPTS = Join-Path $ResolvedRoot 'scripts'
$env:BLENDER_USER_DATAFILES = Join-Path $ResolvedRoot 'datafiles'
$env:BLENDER_USER_EXTENSIONS = Join-Path $ResolvedRoot 'extensions'
$env:TEMP = Join-Path $ResolvedRoot 'temp'
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:AGR_VIEWER_TEST_ROOT = $ResolvedRoot
$env:AGR_VIEWER_FIXTURES = $Fixtures
foreach ($ProfilePath in @($env:BLENDER_USER_CONFIG, $env:BLENDER_USER_SCRIPTS, $env:BLENDER_USER_DATAFILES, $env:BLENDER_USER_EXTENSIONS, $env:TEMP)) {
    $ResolvedProfile = (Resolve-Path -LiteralPath $ProfilePath).Path
    if (-not $ResolvedProfile.StartsWith($ResolvedRoot + '\')) { throw 'Profile outside approved root' }
}
$Arguments = @('--disable-autoexec', '--threads', '4')
if (-not $Gui) { $Arguments += '--background' }
if ($BlendFile) { $Arguments += $BlendFile }
$Arguments += @('--python-exit-code', '1', '--python', $Script)
if ($Gui) {
    if ($LogName -notmatch '^[a-z0-9_]+$') { throw 'Invalid log name' }
    $Arguments += @('--window-geometry', '0', '0', '1600', '1000')
    $Process = Start-Process -FilePath $Blender -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $ResolvedRoot ($LogName + '.log')) -RedirectStandardError (Join-Path $ResolvedRoot ($LogName + '.err'))
    Get-Content -LiteralPath (Join-Path $ResolvedRoot ($LogName + '.log')) -Tail 25
    Get-Content -LiteralPath (Join-Path $ResolvedRoot ($LogName + '.err')) -Tail 15
    exit $Process.ExitCode
}
& $Blender @Arguments
exit $LASTEXITCODE
