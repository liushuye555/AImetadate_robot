' Hidden stopper for NapCat + QQ OneBot whitelist bot.
' Stops only processes whose command line contains the configured project paths.

Option Explicit
Dim wmi, processes, p, napcatNeedle, botNeedle, killed
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
napcatNeedle = "D:\Hermes\Data\tools\napcat\NapCat.Shell.Windows.Node"
botNeedle = "C:\Users\eryis\workspace\qq-onebot-whitelist"
killed = 0

Set processes = wmi.ExecQuery("SELECT ProcessId, Name, CommandLine FROM Win32_Process")
For Each p In processes
  If Not IsNull(p.CommandLine) Then
    If InStr(1, p.CommandLine, napcatNeedle, vbTextCompare) > 0 Or _
       InStr(1, p.CommandLine, botNeedle, vbTextCompare) > 0 Then
      On Error Resume Next
      p.Terminate()
      If Err.Number = 0 Then killed = killed + 1
      Err.Clear
      On Error GoTo 0
    End If
  End If
Next

MsgBox "已尝试停止相关后台进程。匹配并终止数量: " & killed, vbInformation, "QQ OneBot stopper"
