' Script d'arrêt pour Alyx (Mode Silencieux)
' Ce script arrête les services d'Alyx en arrière-plan et affiche un message de confirmation.

Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Lance le fichier stop.bat de façon cachée (0)
WshShell.Run chr(34) & scriptDir & "\stop.bat" & chr(34), 0, True

MsgBox "Les services Alyx ont été arrêtés avec succès.", 64, "Alyx"
Set WshShell = Nothing
