# ai_run.ps1 - run an ExtendScript in Windows Illustrator via COM, write the result (UTF-8) to a file.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File ai_run.ps1 <script.jsx> <result.txt>
#
# Called from ai2spec.sh (the Windows counterpart of osascript on macOS).
# The result goes to a file, not stdout, because PowerShell 5.1 writes stdout in cp932
# and Japanese paths get garbled.
# If several Illustrator versions are installed, set AI_PROGID (e.g. Illustrator.Application.30 = 2026).
#
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads BOM-less .ps1 files as cp932,
# so any Japanese text here breaks parsing.
param(
  [Parameter(Mandatory = $true)][string]$Script,
  [Parameter(Mandatory = $true)][string]$Result
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding $false

try {
  $progId = if ($env:AI_PROGID) { $env:AI_PROGID } else { 'Illustrator.Application' }
  if (-not [type]::GetTypeFromProgID($progId)) {
    throw "Illustrator COM class not registered: $progId"
  }
  $code = [System.IO.File]::ReadAllText($Script, [System.Text.Encoding]::UTF8)
  $app = New-Object -ComObject $progId
  $res = $app.DoJavaScript($code)
  [System.IO.File]::WriteAllText($Result, [string]$res, $utf8)
} catch {
  [System.IO.File]::WriteAllText($Result, "ERR`t" + $_.Exception.Message, $utf8)
  exit 1
}
