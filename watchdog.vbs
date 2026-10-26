' Keeps Playlistor running. Every minute it checks that the server and the ngrok tunnel are up,
' and starts whichever one is missing. install_autostart.vbs starts it at every sign-in.
' It keeps a lock file (logs\watchdog.lock) that it refreshes every minute, so only one watchdog runs.
' Restarts are written to logs\watchdog.log. The file is ASCII only, because Windows Script Host reads it as ANSI.
Option Explicit
Dim fso, shell, folder, lockFile, logFile, status, lock

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
If Not fso.FolderExists(folder & "\logs") Then fso.CreateFolder(folder & "\logs")
lockFile = folder & "\logs\watchdog.lock"
logFile = folder & "\logs\watchdog.log"

' A lock younger than 3 minutes means another watchdog is running. An older one was left by a previous sign-in.
If fso.FileExists(lockFile) Then
  If DateDiff("s", fso.GetFile(lockFile).DateLastModified, Now) < 180 Then WScript.Quit 0
End If

Do
  Set lock = fso.CreateTextFile(lockFile, True)
  lock.WriteLine Now
  lock.Close

  ' findstr returns 0 when the server listens on 127.0.0.1:5000
  status = shell.Run("cmd /c netstat -ano | findstr LISTENING | findstr 127.0.0.1:5000", 0, True)
  If status <> 0 Then
    Log "server is not listening, starting it"
    shell.Run "wscript.exe """ & folder & "\start_server.vbs""", 0, True
  End If

  ' findstr returns 0 when ngrok.exe is running
  status = shell.Run("cmd /c tasklist /FI ""IMAGENAME eq ngrok.exe"" | findstr /I ngrok.exe", 0, True)
  If status <> 0 Then
    Log "ngrok tunnel is not running, starting it"
    shell.Run "wscript.exe """ & folder & "\start_tunnel.vbs""", 0, True
  End If

  WScript.Sleep 60000
Loop

Sub Log(message)
  Dim file
  Set file = fso.OpenTextFile(logFile, 8, True)
  file.WriteLine Now & " " & message
  file.Close
End Sub
