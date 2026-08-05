' launch.vbs
'
' Silent launcher — runs the app with ZERO console window, exactly like
' the behavior you'll get from the --windowed PyInstaller build. Use
' this for a final "does it feel like a real desktop app" check before
' you package the .exe, and/or as the target of a desktop shortcut if
' you'd rather ship the raw Python project instead of a compiled exe.
'
' Double-click this file (or point a desktop shortcut at it) to launch
' with no CMD window ever appearing.

Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonExe = scriptDir & "\venv\Scripts\pythonw.exe"   ' pythonw = no console, ever
appScript = scriptDir & "\app.py"

If Not fso.FileExists(pythonExe) Then
    MsgBox "Virtual environment not found." & vbCrLf & vbCrLf & _
           "Run this once from a command prompt in this folder:" & vbCrLf & _
           "  python -m venv venv" & vbCrLf & _
           "  venv\Scripts\pip install -r requirements.txt", _
           vbCritical, "AI OrderFlow Pro — Setup Needed"
    WScript.Quit 1
End If

objShell.CurrentDirectory = scriptDir

' 0 = hidden window, False = don't wait for it to exit
objShell.Run """" & pythonExe & """ """ & appScript & """", 0, False
