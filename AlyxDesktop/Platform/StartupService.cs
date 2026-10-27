using System;
using System.IO;

namespace AlyxDesktop.Platform;

/// <summary>« Démarrer avec Windows / la session » : clé Run (Windows) ou ~/.config/autostart (Linux).</summary>
public static class StartupService
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "Alyx";

    private static string LinuxEntry =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config", "autostart", "alyx.desktop");

    public static bool IsEnabled()
    {
#if WINDOWS
        using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(RunKey);
        return key?.GetValue(ValueName) != null;
#else
        return File.Exists(LinuxEntry);
#endif
    }

    /// <summary>Active ou désactive le démarrage automatique. false si le dossier d'Alyx est introuvable.</summary>
    public static bool SetEnabled(bool enabled)
    {
        string? root = Shell.AppRoot;
        if (enabled && root == null) return false;
        try
        {
#if WINDOWS
            using var key = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(RunKey);
            if (enabled)
                key.SetValue(ValueName, $"wscript.exe \"{Path.Combine(root!, "Lancer_Alyx.vbs")}\"");
            else
                key.DeleteValue(ValueName, false);
#else
            if (enabled)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(LinuxEntry)!);
                File.WriteAllText(LinuxEntry,
                    "[Desktop Entry]\nType=Application\nName=Alyx\nComment=Assistant local Alyx\n" +
                    $"Exec=\"{Path.Combine(root!, "alyx.sh")}\"\nX-GNOME-Autostart-enabled=true\n");
            }
            else if (File.Exists(LinuxEntry))
            {
                File.Delete(LinuxEntry);
            }
#endif
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            return false;
        }
    }
}
