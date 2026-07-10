' Hidden launcher for NapCat + QQ OneBot whitelist bot.
' Double-click this file to start both processes without visible console windows.
' Logs:
'   C:\Users\eryis\workspace\qq-onebot-whitelist\logs\napcat.log
'   C:\Users\eryis\workspace\qq-onebot-whitelist\logs\bot.log

Option Explicit

Dim shell, fso, napcatDir, botDir, logDir, napcatCmd, botCmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

napcatDir = "D:\Hermes\Data\tools\napcat\NapCat.Shell.Windows.Node"
botDir = "C:\Users\eryis\workspace\qq-onebot-whitelist"
logDir = botDir & "\logs"

If Not fso.FolderExists(logDir) Then
  fso.CreateFolder(logDir)
End If

If Not fso.FileExists(napcatDir & "\napcat.bat") Then
  MsgBox "NapCat launcher not found: " & napcatDir & "\napcat.bat", vbCritical, "QQ OneBot launcher"
  WScript.Quit 1
End If

If Not fso.FileExists(botDir & "\config.yaml") Then
  MsgBox "Bot config not found: " & botDir & "\config.yaml", vbCritical, "QQ OneBot launcher"
  WScript.Quit 1
End If

napcatCmd = "cmd /c cd /d """ & napcatDir & """ && call napcat.bat >> """ & logDir & "\napcat.log"" 2>&1"
botCmd = "cmd /c cd /d """ & botDir & """ && if exist .env call .env && uv run python -m qq_onebot_whitelist.onebot --config config.yaml >> """ & logDir & "\bot.log"" 2>&1"

' 0 = hidden window, False = do not wait.
shell.Run napcatCmd, 0, False
WScript.Sleep 8000
shell.Run botCmd, 0, False

MsgBox "已在后台启动 NapCat 和 QQ OneBot 白名单机器人。" & vbCrLf & vbCrLf & _
       "NapCat WebUI: http://127.0.0.1:6099" & vbCrLf & _
       "OneBot WS: ws://127.0.0.1:3001" & vbCrLf & vbCrLf & _
       "日志目录: " & logDir, vbInformation, "QQ OneBot launcher"
