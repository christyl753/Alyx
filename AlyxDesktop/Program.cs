using Avalonia;
using Avalonia.Media;
using System;
using System.Collections.Generic;

namespace AlyxDesktop;

class Program
{
    // Initialization code. Don't use any Avalonia, third-party APIs or any
    // SynchronizationContext-reliant code before AppMain is called: things aren't initialized
    // yet and stuff might break.
    [STAThread]
    public static void Main(string[] args) => BuildAvaloniaApp()
        .StartWithClassicDesktopLifetime(args);

    // Avalonia configuration, don't remove; also used by visual designer.
    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()

            .WithInterFont()
            // Inter (police par défaut) ne contient aucun glyphe emoji : sans repli
            // explicite, "🎤"/"📱"/"✕" etc. dans l'UI (boutons, indicateurs d'état)
            // s'affichent en blanc, y compris ceux déjà présents avant ce correctif.
            // Avalonia ne découvre pas automatiquement les polices emoji du système —
            // il faut les déclarer nommément. Une police absente de l'OS est simplement
            // ignorée par la chaîne de repli, donc lister les trois OS cibles est sûr.
            .With(new FontManagerOptions
            {
                FontFallbacks = new List<FontFallback>
                {
                    new FontFallback { FontFamily = new FontFamily("Noto Color Emoji") },   // Linux (Fedora/Nobara)
                    new FontFallback { FontFamily = new FontFamily("Segoe UI Emoji") },     // Windows
                    new FontFallback { FontFamily = new FontFamily("Apple Color Emoji") },  // macOS
                }
            })
            .LogToTrace();
}
