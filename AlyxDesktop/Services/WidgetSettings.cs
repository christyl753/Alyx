using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AlyxDesktop.Services;

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum PanelLayoutMode { Card, Side, Overlay }

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum OpenEntryMode { Radial, Card, Side, Overlay }

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum IdlePresenceMode { EdgeTab, Stealth, MiniOrb, Orb }

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum EdgeDockSide { Right, Left }

/// <summary>Préférences du widget, persistées dans %APPDATA%/Alyx/widget.json (~/.config/Alyx sous Linux).</summary>
public sealed class WidgetSettings
{
    /// <summary>Position de l'orbe en DIP, relative à la zone de travail de l'écran (null = position par défaut).</summary>
    public double? OrbX { get; set; }
    public double? OrbY { get; set; }
    public bool EverOpened { get; set; }
    public bool EyeFollowsCursor { get; set; } = true;
    public PanelLayoutMode PanelLayout { get; set; } = PanelLayoutMode.Card;
    public OpenEntryMode EntryMode { get; set; } = OpenEntryMode.Card;
    public IdlePresenceMode IdleMode { get; set; } = IdlePresenceMode.EdgeTab;
    public EdgeDockSide DockSide { get; set; } = EdgeDockSide.Right;
    public double? EdgeTabY { get; set; }
    public string WatercolorPalette { get; set; } = "canopee-ambre";
    public string ActiveVisualStyle { get; set; } = "canopee-ambre";
    public string ThemeMode { get; set; } = "light";
    public int WidgetOpacityPercent { get; set; } = 96;
    public bool LowRamEcoMode { get; set; } = false;

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
