param([string]$IconPath = (Join-Path $PSScriptRoot 'PromptTransAgentAssistant.exe'))
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $IconPath).Path
if (-not ('PromptAssistant.ShellIconRefresh' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace PromptAssistant {
    public static class ShellIconRefresh {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        public static extern void SHChangeNotify(int eventId, uint flags,
            [MarshalAs(UnmanagedType.LPWStr)] string item1,
            [MarshalAs(UnmanagedType.LPWStr)] string item2);
    }
}
'@
}
# Refresh the file entry and invalidate Shell's cached icons without deleting
# cache files or restarting Explorer. PATHW | FLUSH = 0x1005.
[PromptAssistant.ShellIconRefresh]::SHChangeNotify(0x2000, 0x1005, $target, $null)
[PromptAssistant.ShellIconRefresh]::SHChangeNotify(0x1000, 0x1005, (Split-Path -Parent $target), $null)
[PromptAssistant.ShellIconRefresh]::SHChangeNotify(0x08000000, 0, $null, $null)
Write-Host 'Windows icon refresh requested. Refresh the folder if it is already open.'
