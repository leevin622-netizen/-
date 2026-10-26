' Starts Playlistor in the background, with no window. Installed to run at every sign-in by install_autostart.vbs.
' If the server is already listening on port 5000, it does not start a second one.
' Output goes to logs\server.log. The file is ASCII only, because Windows Script Host reads it as ANSI.
Option Explicit
Dim fso, shell, folder, python, status, command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder

' findstr returns 0 when it finds a LISTENING line on 127.0.0.1:5000, so the server is already running
status = shell.Run("cmd /c netstat -ano | findstr LISTENING | findstr 127.0.0.1:5000", 0, True)
If status = 0 Then WScript.Quit 0

python = folder & "\venv\Scripts\python.exe"
If Not fso.FileExists(python) Then WScript.Quit 1
If Not fso.FolderExists(folder & "\logs") Then fso.CreateFolder(folder & "\logs")

' waitress is a production WSGI server, steadier than the Flask development server.
' It listens on 127.0.0.1 only, so other computers on the network cannot reach it directly.
command = "cmd /c cd /d """ & folder & """ && set PYTHONUTF8=1 && """ & python & """" & _
          " -m waitress --listen=127.0.0.1:5000 app:app >> logs\server.log 2>&1"
shell.Run command, 0, False
