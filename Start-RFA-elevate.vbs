On Error Resume Next
Set shell = CreateObject("Shell.Application")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(root, "Start-RFA-launch.ps1")
runtimeDir = fso.BuildPath(root, "go-app\.runtime\desktop-launcher")
If Not fso.FolderExists(runtimeDir) Then fso.CreateFolder(runtimeDir)
Set logFile = fso.OpenTextFile(fso.BuildPath(runtimeDir, "bootstrap.log"), 8, True)
logFile.WriteLine Now & " | wrapper started | " & script
args = "-NoProfile -ExecutionPolicy Bypass -STA -File " & Chr(34) & script & Chr(34)
shell.ShellExecute fso.BuildPath(fso.GetSpecialFolder(1), "WindowsPowerShell\v1.0\powershell.exe"), args, root, "runas", 1
If Err.Number <> 0 Then
  logFile.WriteLine Now & " | launch error | " & Err.Number & " | " & Err.Description
  MsgBox "اجرای لانچر ناموفق بود: " & Err.Description, 16, "RFA Launcher"
Else
  logFile.WriteLine Now & " | elevated PowerShell launched"
End If
logFile.Close
