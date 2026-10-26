' Installs Playlistor to the Windows Startup folder, so it runs at every sign-in.
' Double-click it once. It adds one shortcut (watchdog) to shell:startup, removes the two older shortcuts
' (server and tunnel, which the watchdog now starts), and starts the watchdog now.
' The watchdog starts the server and the ngrok tunnel, and restarts them if they stop.
' To undo, delete the "Playlistor watchdog" shortcut in shell:startup.
Option Explicit
Dim shell, fso, folder, startup, shortcut, name

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
startup = shell.SpecialFolders("Startup")

For Each name In Array("Playlistor server.lnk", "Playlistor tunnel.lnk")
  If fso.FileExists(startup & "\" & name) Then fso.DeleteFile startup & "\" & name
Next

Set shortcut = shell.CreateShortcut(startup & "\Playlistor watchdog.lnk")
shortcut.TargetPath = "wscript.exe"
shortcut.Arguments = """" & folder & "\watchdog.vbs"""
shortcut.WorkingDirectory = folder
shortcut.Description = "Starts Playlistor and its ngrok tunnel at sign-in, and restarts them if they stop"
shortcut.Save

shell.Run "wscript.exe """ & folder & "\watchdog.vbs""", 0, False
MsgBox ChrW(1508)&ChrW(1500)&ChrW(1497)&ChrW(1497)&ChrW(1500)&ChrW(1497)&ChrW(1505)&ChrW(1496)&ChrW(1493)&ChrW(1512)&" "&ChrW(1502)&ChrW(1493)&ChrW(1514)&ChrW(1511)&ChrW(1503)&"."&" "&ChrW(1492)&ChrW(1513)&ChrW(1512)&ChrW(1514)&" "&ChrW(1497)&ChrW(1506)&ChrW(1500)&ChrW(1492)&" "&ChrW(1500)&ChrW(1489)&ChrW(1491)&" "&ChrW(1489)&ChrW(1499)&ChrW(1500)&" "&ChrW(1499)&ChrW(1504)&ChrW(1497)&ChrW(1505)&ChrW(1492)&" "&ChrW(1500)&"-"&"W"&"i"&"n"&"d"&"o"&"w"&"s"&","&" "&ChrW(1493)&ChrW(1506)&ChrW(1499)&ChrW(1513)&ChrW(1497)&ChrW(1493)&" "&ChrW(1492)&ChrW(1493)&ChrW(1488)&" "&ChrW(1506)&ChrW(1493)&ChrW(1500)&ChrW(1492)&" "&ChrW(1490)&ChrW(1501)&" "&ChrW(1499)&ChrW(1503)&"." & vbCrLf & "http://127.0.0.1:5000", 64, "Playlistor"
