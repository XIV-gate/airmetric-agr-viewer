param([Parameter(Mandatory=$true)][string]$Script,
      [Parameter(Mandatory=$true)][string]$TestRoot,
      [Parameter(Mandatory=$true)][string]$Blender,
      [string]$Fixtures = '', [string]$BlendFile = '')
$ErrorActionPreference = 'Stop'
$ResolvedRoot = (Resolve-Path -LiteralPath $TestRoot).Path
if (-not $ResolvedRoot.StartsWith('D:\') -or $ResolvedRoot.Length -le 3) {
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
$Arguments = @('--background', '--threads', '4')
if ($BlendFile) { $Arguments += $BlendFile }
$Arguments += @('--python-exit-code', '1', '--python', $Script)
& $Blender @Arguments
exit $LASTEXITCODE
