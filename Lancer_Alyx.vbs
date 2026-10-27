' Script de lancement pour Alyx (Mode Silencieux)
' Ce script démarre l'application sans afficher la fenêtre noire du terminal

Set WshShell = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts://./root/cimv2")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Vérifie si l'API de CE dossier Alyx est déjà lancée (les \ doivent être doublés en WQL)
query = "Select * from Win32_Process Where Name = 'python.exe' And CommandLine Like '%" & Replace(scriptDir, "\", "\\") & "\\api.py%'"
Set processes = wmi.ExecQuery(query)
If processes.Count > 0 Then
    MsgBox "Alyx est déjà réveillé et actif sur votre système.", 64, "Alyx Agent"
    Set WshShell = Nothing
    Set wmi = Nothing
    WScript.Quit
End If

' Lance le fichier alyx.bat de façon cachée (0)
WshShell.Run chr(34) & scriptDir & "\alyx.bat" & chr(34), 0

Set WshShell = Nothing
