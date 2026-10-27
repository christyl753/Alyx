using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

namespace AlyxDesktop.Platform;

/// <summary>Utilitaires communs aux intégrations système.</summary>
public static class Shell
{
    /// <summary>Exécute un outil en ligne de commande (Linux surtout) ; null si absent ou en échec.</summary>
    public static async Task<string?> RunAsync(string fileName, params string[] args)
    {
        try
        {
            var psi = new ProcessStartInfo(fileName)
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            foreach (var a in args) psi.ArgumentList.Add(a);
            using var proc = Process.Start(psi);
            if (proc == null) return null;
            var output = proc.StandardOutput.ReadToEndAsync();
            var exited = proc.WaitForExitAsync();
            if (await Task.WhenAny(exited, Task.Delay(3000)) != exited)
            {
                try { proc.Kill(); } catch (InvalidOperationException) { }
                return null;
            }
            return proc.ExitCode == 0 ? (await output).Trim() : null;
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            return null;
        }
    }

    /// <summary>Ouvre une URI système (ex. ms-settings:nightlight).</summary>
    public static void OpenUri(string uri)
    {
        try
        {
            Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Ouverture de {uri} impossible: {ex.Message}");
        }
    }

    /// <summary>Racine du projet Alyx (dossier contenant config.yaml), en remontant depuis l'exécutable.</summary>
    public static string? AppRoot
    {
        get
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null)
            {
                if (File.Exists(Path.Combine(dir.FullName, "config.yaml"))) return dir.FullName;
                dir = dir.Parent;
            }
            return null;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT { public int X, Y; }

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out POINT point);

    /// <summary>Position du curseur à l'écran en pixels physiques (Windows), null ailleurs.</summary>
    public static (int X, int Y)? CursorPosition()
    {
        if (!OperatingSystem.IsWindows()) return null;
        return GetCursorPos(out var p) ? (p.X, p.Y) : null;
    }
}
