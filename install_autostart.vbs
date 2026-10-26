' Installs Playlistor to the Windows Startup folder, so the server starts at every sign-in.
' Double-click it once. It also starts the server right away. To undo, delete the shortcut in shell:startup.
Option Explicit
Dim shell, fso, folder, startup, shortcut

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
startup = shell.SpecialFolders("Startup")

Set shortcut = shell.CreateShortcut(startup & "\Playlistor server.lnk")
shortcut.TargetPath = "wscript.exe"
shortcut.Arguments = """" & folder & "\start_server.vbs"""
shortcut.WorkingDirectory = folder
shortcut.Description = "Starts Playlistor in the background at sign-in"
shortcut.Save

shell.Run "wscript.exe """ & folder & "\start_server.vbs""", 0, False
MsgBox ChrW(1508)&ChrW(1500)&ChrW(1497)&ChrW(1497)&ChrW(1500)&ChrW(1497)&ChrW(1505)&ChrW(1496)&ChrW(1493)&ChrW(1512)&" "&ChrW(1502)&ChrW(1493)&ChrW(1514)&ChrW(1511)&ChrW(1503)&"."&" "&ChrW(1492)&ChrW(1513)&ChrW(1512)&ChrW(1514)&" "&ChrW(1497)&ChrW(1506)&ChrW(1500)&ChrW(1492)&" "&ChrW(1500)&ChrW(1489)&ChrW(1491)&" "&ChrW(1489)&ChrW(1499)&ChrW(1500)&" "&ChrW(1499)&ChrW(1504)&ChrW(1497)&ChrW(1505)&ChrW(1492)&" "&ChrW(1500)&"-"&"W"&"i"&"n"&"d"&"o"&"w"&"s"&","&" "&ChrW(1493)&ChrW(1506)&ChrW(1499)&ChrW(1513)&ChrW(1497)&ChrW(1493)&" "&ChrW(1492)&ChrW(1493)&ChrW(1488)&" "&ChrW(1506)&ChrW(1493)&ChrW(1500)&ChrW(1492)&" "&ChrW(1490)&ChrW(1501)&" "&ChrW(1499)&ChrW(1503)&"." & vbCrLf & "http://127.0.0.1:5000", 64, "Playlistor"
