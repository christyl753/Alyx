using System;
using System.IO;
using System.Text.Json;

namespace AlyxDesktop.Services;

/// <summary>Préférences du widget, persistées dans %APPDATA%/Alyx/widget.json (~/.config/Alyx sous Linux).</summary>
public sealed class WidgetSettings
{
    /// <summary>Position de l'orbe en DIP, relative à la zone de travail de l'écran (null = position par défaut).</summary>
    public double? OrbX { get; set; }
    public double? OrbY { get; set; }
    public bool EverOpened { get; set; }
    public bool EyeFollowsCursor { get; set; } = true;

    private static string FilePath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Alyx", "widget.json");

    public static WidgetSettings Load()
    {
        try
        {
            if (File.Exists(FilePath))
                return JsonSerializer.Deserialize<WidgetSettings>(File.ReadAllText(FilePath)) ?? new WidgetSettings();
        }
        catch (Exception)
        {
            // Fichier corrompu : valeurs par défaut
        }
        return new WidgetSettings();
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch (Exception)
        {
            // Préférences non critiques
        }
    }
}
