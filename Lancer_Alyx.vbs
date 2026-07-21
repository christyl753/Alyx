' Script de lancement pour Alyx (Mode Silencieux)
' Ce script démarre l'application sans afficher la fenêtre noire du terminal

Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Lance le fichier alyx.bat de façon cachée (0)
WshShell.Run chr(34) & scriptDir & "\alyx.bat" & chr(34), 0

Set WshShell = Nothing
