' Starts the ngrok tunnel, so the server is reachable at the fixed ngrok domain for friends.
' The domain is read from NGROK_DOMAIN in .env. Does nothing if NGROK_DOMAIN is empty or ngrok already runs.
' Output goes to logs\ngrok.log. The file is ASCII only, because Windows Script Host reads it as ANSI.
' The tunnel only forwards to the server on 127.0.0.1:5000, which must be running.
Option Explicit
Dim fso, shell, folder, envFile, line, domain, status, command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
If Not fso.FolderExists(folder & "\logs") Then fso.CreateFolder(folder & "\logs")

domain = ""
Set envFile = fso.OpenTextFile(folder & "\.env", 1, False)
Do Until envFile.AtEndOfStream
  line = Trim(envFile.ReadLine)
  If Left(line, 13) = "NGROK_DOMAIN=" Then domain = Trim(Mid(line, 14))
Loop
envFile.Close
If domain = "" Then WScript.Quit 1

' findstr returns 0 when ngrok.exe is in the task list, so the tunnel is already running
status = shell.Run("cmd /c tasklist /FI ""IMAGENAME eq ngrok.exe"" | findstr /I ngrok.exe", 0, True)
If status = 0 Then WScript.Quit 0

command = "cmd /c ngrok http --url=" & domain & " 5000 >> logs\ngrok.log 2>&1"
shell.Run command, 0, False
