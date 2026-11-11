using AlyxDesktop.Services;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using System;
using System.Linq;

namespace AlyxDesktop;

public partial class App : Application
{
    private WidgetWindow? _widget;
    public static string ActiveVisualStyle { get; private set; } = "canopee-ambre";
    public static Avalonia.Media.Color ActiveAccentColor { get; private set; } = Avalonia.Media.Color.Parse("#384C48");
    public static Avalonia.Media.Color ActiveSecondaryColor { get; private set; } = Avalonia.Media.Color.Parse("#FBA620");

    private readonly record struct VisualStyleTokens(
        string CanvasLight, string CardLight, string WidgetLight, string ChipLight, string InkLight,
        string CanvasDark, string CardDark, string WidgetDark, string ChipDark, string InkDark,
        string BorderLight, string BorderDark, string PrimaryButtonLight, string PrimaryButtonDark,
        string ButtonTextLight, string ButtonTextDark, string PalettePrimary, string PaletteSecondary,
        double CardRadius, double WidgetRadius, double ChipRadius, double ButtonRadius,
        double CardBorder, double WidgetBorder);

    private static VisualStyleTokens GetVisualStyle(string id) => id switch
    {
        "canopee-ambre" => new("#F6EED9", "#FBF6EA", "#F6EED9", "#FBF6EA", "#384C48", "#1D2826", "#243230", "#1F2C2A", "#2A3A37", "#F6EED9", "#384C48", "#7DAE9B", "#384C48", "#7DAE9B", "#F6EED9", "#1D2826", "#384C48", "#FBA620", 24, 28, 999, 999, 1, 1),
        "watercolor" => new("#FAF9F6", "#FFFFFF", "#FFFFFF", "#FFFFFF", "#14151A", "#0D0E12", "#12141C", "#11131A", "#18181B", "#F5F6FA", "#E4E4E7", "#3F3F46", "#14151A", "#FFFFFF", "#FFFFFF", "#14151A", "#0284C7", "#EC4899", 32, 32, 999, 999, 1, 1),
        "kde" => new("#E3E7EC", "#EFF0F1", "#EFF0F1", "#FFFFFF", "#232629", "#14171A", "#232629", "#1B1E20", "#2A2E32", "#EFF0F1", "#3DAEE9", "#3DAEE9", "#3DAEE9", "#3DAEE9", "#FFFFFF", "#FFFFFF", "#3DAEE9", "#7DD3FC", 12, 12, 6, 6, 1, 2),
        "gnome" => new("#EBEAEA", "#FAFAFA", "#FAFAFA", "#EBEBEB", "#242424", "#181818", "#242424", "#1E1E1E", "#303030", "#FAFAFA", "#1A000000", "#1AFFFFFF", "#3584E4", "#3584E4", "#FFFFFF", "#FFFFFF", "#3584E4", "#7DD3FC", 16, 16, 12, 12, 1, 1),
        "sketch" => new("#FDFBF7", "#FFFDFA", "#FFFDFA", "#F0F9FF", "#283548", "#12131A", "#171821", "#15161F", "#1E293B", "#F5F7FF", "#BAE6FD", "#7DD3FC", "#1E293B", "#BAE6FD", "#FFFFFF", "#0F172A", "#38BDF8", "#F9A8D4", 28, 30, 16, 16, 1, 1.5),
        "sticker" => new("#FDF4F8", "#FFFFFF", "#FFFFFF", "#FDF2F8", "#3F2135", "#13111C", "#1C1926", "#1C1926", "#27272A", "#FFF1F8", "#FFFFFF", "#FBCFE8", "#EC4899", "#EC4899", "#FFFFFF", "#FFFFFF", "#EC4899", "#38BDF8", 28, 30, 999, 999, 5, 6),
        "win7" => new("#BAE6FD", "#F8FDFF", "#EFF9FE", "#F0F9FF", "#12334A", "#061C33", "#0F172A", "#0C2035", "#1E293B", "#E8F5FC", "#BAE6FD", "#7DD3FC", "#0284C7", "#0284C7", "#FFFFFF", "#FFFFFF", "#0284C7", "#7DD3FC", 12, 12, 6, 6, 1, 1),
        "school" => new("#FBFAF2", "#FFFEF9", "#FFFEF9", "#FEF3C7", "#312E81", "#12131A", "#181920", "#161821", "#292524", "#FFF7C2", "#C7D2FE", "#312E81", "#4338CA", "#4338CA", "#FFFFFF", "#FFFFFF", "#4338CA", "#FDE047", 16, 16, 6, 8, 2, 2),
        "office" => new("#F3EFE6", "#F7F4EB", "#F7F4EB", "#FEF9C3", "#292524", "#141311", "#1C1B18", "#191815", "#292524", "#FAFAF9", "#D6CFC2", "#38352E", "#292524", "#E7E5E4", "#FAFAF9", "#1C1917", "#292524", "#D6CFC2", 12, 12, 6, 6, 1, 2),
        "bento-pearl" => new("#F5F6F8", "#FFFFFF", "#FFFFFF", "#F8FAFC", "#1E293B", "#0E0F13", "#18181B", "#18181B", "#27272A", "#F8FAFC", "#E5E7EB", "#FFFFFF", "#0F172A", "#FFFFFF", "#FFFFFF", "#0F172A", "#6366F1", "#EC4899", 28, 32, 16, 16, 1, 1),
        "bauhaus" => new("#F4F1EC", "#FAF8F5", "#FAF8F5", "#FFFFFF", "#1D3557", "#121417", "#16181A", "#141619", "#1F2226", "#FAF8F5", "#E2DDD5", "#2A2E33", "#1D3557", "#1D3557", "#FFFFFF", "#FFFFFF", "#1D3557", "#E2DDD5", 16, 16, 12, 12, 1, 1),
        "eink" => new("#EFEEE9", "#F5F4F0", "#F5F4F0", "#EAE8E1", "#1C1C1C", "#141414", "#1C1C1C", "#181818", "#262626", "#F5F4F0", "#D4D4D8", "#52525B", "#1C1C1C", "#F5F4F0", "#F5F4F0", "#1C1C1C", "#1C1C1C", "#F5F4F0", 16, 16, 12, 12, 1, 1),
        "tactile" => new("#EAECF0", "#F2F3F5", "#F2F3F5", "#FFFFFF", "#24262B", "#15171C", "#1E2026", "#1B1D22", "#282B33", "#F2F3F5", "#FFFFFF", "#52525B", "#0284C7", "#0284C7", "#FFFFFF", "#FFFFFF", "#0284C7", "#7DD3FC", 24, 24, 12, 12, 1, 1),
        "alyx-prism" => new("#F8FAFF", "#FFFFFF", "#FFFFFF", "#F0F9FF", "#20243A", "#070911", "#0F111A", "#0C0E17", "#111827", "#F5F6FA", "#7DD3FC", "#F472B6", "#6366F1", "#6366F1", "#FFFFFF", "#FFFFFF", "#0284C7", "#EC4899", 30, 34, 999, 999, 1, 1),
        _ => GetVisualStyle("canopee-ambre")
    };

    private static Avalonia.Media.IBrush CreateWidgetSurfaceBrush(string styleId, bool isDark, double opacity, Avalonia.Media.Color fallback)
    {
        string[]? stops = styleId switch
        {
            "watercolor" => isDark ? new[] { "#1E2230", "#11131A", "#241A28" } : new[] { "#EBF8FF", "#FFFFFF", "#FDF2F8" },
            "win7" => isDark ? new[] { "#111827", "#0C2035", "#102A43" } : new[] { "#FFFFFF", "#F0F9FF", "#FFFFFF" },
            "alyx-prism" => isDark ? new[] { "#111827", "#0F111A", "#211329" } : new[] { "#EFFAFF", "#FFFFFF", "#FFF1F7" },
            _ => null
        };
        if (stops == null)
            return new Avalonia.Media.SolidColorBrush(fallback) { Opacity = opacity };

        return new Avalonia.Media.LinearGradientBrush
        {
            StartPoint = new Avalonia.RelativePoint(0, 0, Avalonia.RelativeUnit.Relative),
            EndPoint = new Avalonia.RelativePoint(1, 1, Avalonia.RelativeUnit.Relative),
            Opacity = opacity,
            GradientStops = new Avalonia.Media.GradientStops
            {
                new(Avalonia.Media.Color.Parse(stops[0]), 0),
                new(Avalonia.Media.Color.Parse(stops[1]), 0.5),
                new(Avalonia.Media.Color.Parse(stops[2]), 1),
            }
        };
    }

    /// <summary>Ressource du thème (utilisable avant que le contrôle soit attaché à l'arbre visuel).</summary>
    public static T Res<T>(string key) => (T)Current!.FindResource(key)!;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var initialSettings = WidgetSettings.Load();
            ApplyStyleSettings(initialSettings);

            _widget = new WidgetWindow();
            _widget.SettingsChanged += SyncTrayMenu;
            // --open radial|chat|system|tasks|models|settings|style : ouvre le menu au démarrage
            int i = System.Array.IndexOf(desktop.Args ?? System.Array.Empty<string>(), "--open");
            if (i >= 0 && i + 1 < desktop.Args!.Length) _widget.StartupAction = desktop.Args[i + 1];
            desktop.MainWindow = _widget;
            desktop.ShutdownMode = ShutdownMode.OnMainWindowClose;
            SyncTrayMenu();
        }

        base.OnFrameworkInitializationCompleted();
    }

    public static void ApplyStyleSettings(WidgetSettings settings)
    {
        if (Current == null) return;

        Current.RequestedThemeVariant = settings.ThemeMode switch
        {
            "dark" => Avalonia.Styling.ThemeVariant.Dark,
            "light" => Avalonia.Styling.ThemeVariant.Light,
            _ => Avalonia.Styling.ThemeVariant.Default
        };

        bool isDark = settings.ThemeMode == "dark";

        string primaryHex = "#0284C7";
        string secondaryHex = "#EC4899";

        switch (settings.WatercolorPalette)
        {
            case "canopee-ambre":
                primaryHex = "#384C48";
                secondaryHex = "#FBA620";
                break;
            case "watercolor-blue":
                primaryHex = "#0284C7";
                secondaryHex = "#7DD3FC";
                break;
            case "watercolor-rose":
                primaryHex = "#DB2777";
                secondaryHex = "#F9A8D4";
                break;
            case "ink-minimal":
                primaryHex = isDark ? "#E4E4E7" : "#18181B";
                secondaryHex = "#F472B6";
                break;
            case "alyx-prism":
                primaryHex = "#0284C7";
                secondaryHex = "#EC4899";
                break;
            case "watercolor-duo":
                primaryHex = "#0284C7";
                secondaryHex = "#EC4899";
                break;
            default:
                primaryHex = "#384C48";
                secondaryHex = "#FBA620";
                break;
        }

        var primaryColor = Avalonia.Media.Color.Parse(primaryHex);
        var secondaryColor = Avalonia.Media.Color.Parse(secondaryHex);
        ActiveVisualStyle = settings.ActiveVisualStyle;
        ActiveAccentColor = primaryColor;
        ActiveSecondaryColor = secondaryColor;

        Current.Resources["Accent"] = new Avalonia.Media.SolidColorBrush(primaryColor);
        Current.Resources["AccentText"] = new Avalonia.Media.SolidColorBrush(primaryColor);
        Current.Resources["AccentBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(102, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentBorder28"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(71, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentBorder35"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(89, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentActivePill"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(38, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentTint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(28, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentFocus"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(115, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["Danger"] = new Avalonia.Media.SolidColorBrush(secondaryColor);

        if (isDark)
        {
            if (settings.WatercolorPalette == "canopee-ambre")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#1F2C2A"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#243230"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(242, 31, 44, 42));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#2A3A37"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F6EED9"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#E2D8BF"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#7DAE9B"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#A4C3B7"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#7DAE9B"));
            }
            else
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#0D0E12"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#11131A"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(242, 17, 19, 26));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#191B24"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F5F6FA"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#D4D4D8"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#71717A"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#A1A1AA"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#384C48"));
            }
            Current.Resources["TextBody"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#E4E4E7"));
            Current.Resources["Fill035"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(14, 255, 255, 255));
            Current.Resources["Fill04"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(18, 255, 255, 255));
            Current.Resources["Fill07"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(26, 255, 255, 255));
            Current.Resources["Hair6"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(20, 255, 255, 255));
            Current.Resources["Hair8"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(28, 255, 255, 255));
            Current.Resources["Hair9"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(32, 255, 255, 255));
            Current.Resources["Hair10"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(38, 255, 255, 255));
        }
        else
        {
            if (settings.WatercolorPalette == "canopee-ambre")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F6EED9"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FBF6EA"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F6EED9"));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FBF6EA"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#384C48"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#243230"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#7DAE9B"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#5D726D"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#384C48"));
            }
            else
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FAF9F6"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F5FFFFFF"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#14151A"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#27272A"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#A1A1AA"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#71717A"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#14151A"));
            }
            Current.Resources["TextBody"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3F3F46"));
            Current.Resources["Fill035"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(9, 20, 21, 26));
            Current.Resources["Fill04"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(12, 20, 21, 26));
            Current.Resources["Fill07"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(20, 20, 21, 26));
            Current.Resources["Hair6"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(15, 20, 21, 26));
            Current.Resources["Hair8"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(20, 20, 21, 26));
            Current.Resources["Hair9"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(24, 20, 21, 26));
            Current.Resources["Hair10"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(30, 20, 21, 26));
        }

        // Les préréglages de design définissent aussi les surfaces principales du client.
        // Les anciennes palettes restent utilisées pour les accents, en complément du style.
        var style = GetVisualStyle(settings.ActiveVisualStyle);
        Current.Resources["StyleUiFont"] = settings.ActiveVisualStyle == "canopee-ambre"
            ? Current.FindResource("UiFont")!
            : new Avalonia.Media.FontFamily("avares://AlyxDesktop/Assets/Fonts#Manrope, Segoe UI, sans-serif");
        var bg = Avalonia.Media.Color.Parse(isDark ? style.CanvasDark : style.CanvasLight);
        var card = Avalonia.Media.Color.Parse(isDark ? style.CardDark : style.CardLight);
        var widget = Avalonia.Media.Color.Parse(isDark ? style.WidgetDark : style.WidgetLight);
        var chip = Avalonia.Media.Color.Parse(isDark ? style.ChipDark : style.ChipLight);
        var ink = Avalonia.Media.Color.Parse(isDark ? style.InkDark : style.InkLight);
        var border = Avalonia.Media.Color.Parse(isDark ? style.BorderDark : style.BorderLight);
        var primaryButton = Avalonia.Media.Color.Parse(isDark ? style.PrimaryButtonDark : style.PrimaryButtonLight);
        var buttonText = Avalonia.Media.Color.Parse(isDark ? style.ButtonTextDark : style.ButtonTextLight);
        var opacity = (byte)Math.Clamp(settings.WidgetOpacityPercent * 255 / 100, 0, 255);

        Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(bg);
        Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(card);
        Current.Resources["CardSurface"] = new Avalonia.Media.SolidColorBrush(card);
        Current.Resources["PanelSurface"] = CreateWidgetSurfaceBrush(settings.ActiveVisualStyle, isDark, opacity / 255d, widget);
        Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(chip);
        Current.Resources["ChipSurface"] = new Avalonia.Media.SolidColorBrush(chip);
        Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(ink);
        Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(ink);
        Current.Resources["TextBody"] = new Avalonia.Media.SolidColorBrush(ink);
        Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(border);
        Current.Resources["StyleBorder"] = new Avalonia.Media.SolidColorBrush(border);
        Current.Resources["WidgetBorder"] = new Avalonia.Media.SolidColorBrush(border);
        Current.Resources["PrimaryButton"] = new Avalonia.Media.SolidColorBrush(primaryButton);
        Current.Resources["PrimaryButtonText"] = new Avalonia.Media.SolidColorBrush(buttonText);
        Current.Resources["CardCornerRadius"] = new Avalonia.CornerRadius(style.CardRadius);
        Current.Resources["WidgetCornerRadius"] = new Avalonia.CornerRadius(style.WidgetRadius);
        Current.Resources["ChipCornerRadius"] = new Avalonia.CornerRadius(style.ChipRadius);
        Current.Resources["PrimaryButtonCornerRadius"] = new Avalonia.CornerRadius(style.ButtonRadius);
        Current.Resources["CardBorderThickness"] = new Avalonia.Thickness(style.CardBorder);
        Current.Resources["WidgetBorderThickness"] = new Avalonia.Thickness(style.WidgetBorder);

        // La palette de couleurs reste un réglage d’accent indépendant.
        Current.Resources["Accent"] = new Avalonia.Media.SolidColorBrush(primaryColor);
        Current.Resources["AccentText"] = new Avalonia.Media.SolidColorBrush(primaryColor);
        Current.Resources["AccentBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(102, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentBorder28"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(71, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentBorder35"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(89, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentActivePill"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(38, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentTint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(28, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentFocus"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(115, primaryColor.R, primaryColor.G, primaryColor.B));
    }

    private void SyncTrayMenu()
    {
        if (_widget == null) return;
        var menu = TrayIcon.GetIcons(this)?.FirstOrDefault()?.Menu;
        if (menu == null || menu.Items.Count < 3) return;

        if (menu.Items[1] is NativeMenuItem { Menu: { } layoutMenu } && layoutMenu.Items.Count >= 3)
        {
            var layout = _widget.CurrentPanelLayout;
            if (layoutMenu.Items[0] is NativeMenuItem c0) c0.IsChecked = layout == PanelLayoutMode.Card;
            if (layoutMenu.Items[1] is NativeMenuItem c1) c1.IsChecked = layout == PanelLayoutMode.Side;
            if (layoutMenu.Items[2] is NativeMenuItem c2) c2.IsChecked = layout == PanelLayoutMode.Overlay;
        }

        if (menu.Items[2] is NativeMenuItem { Menu: { } idleMenu } && idleMenu.Items.Count >= 4)
        {
            var idle = _widget.CurrentIdleMode;
            if (idleMenu.Items[0] is NativeMenuItem i0) i0.IsChecked = idle == IdlePresenceMode.EdgeTab;
            if (idleMenu.Items[1] is NativeMenuItem i1) i1.IsChecked = idle == IdlePresenceMode.Stealth;
            if (idleMenu.Items[2] is NativeMenuItem i2) i2.IsChecked = idle == IdlePresenceMode.MiniOrb;
            if (idleMenu.Items[3] is NativeMenuItem i3) i3.IsChecked = idle == IdlePresenceMode.Orb;
        }
    }

    private void OnTrayClicked(object? sender, EventArgs e) => _widget?.ToggleFromExternal();
    private void OnTrayToggle(object? sender, EventArgs e) => _widget?.ToggleFromExternal();
    private void OnTrayLayoutCard(object? sender, EventArgs e) => _widget?.SelectPanelLayoutFromTray(PanelLayoutMode.Card);
    private void OnTrayLayoutSide(object? sender, EventArgs e) => _widget?.SelectPanelLayoutFromTray(PanelLayoutMode.Side);
    private void OnTrayLayoutOverlay(object? sender, EventArgs e) => _widget?.SelectPanelLayoutFromTray(PanelLayoutMode.Overlay);
    private void OnTrayIdleEdgeTab(object? sender, EventArgs e) => _widget?.SetIdlePresenceMode(IdlePresenceMode.EdgeTab);
    private void OnTrayIdleStealth(object? sender, EventArgs e) => _widget?.SetIdlePresenceMode(IdlePresenceMode.Stealth);
    private void OnTrayIdleMiniOrb(object? sender, EventArgs e) => _widget?.SetIdlePresenceMode(IdlePresenceMode.MiniOrb);
    private void OnTrayIdleOrb(object? sender, EventArgs e) => _widget?.SetIdlePresenceMode(IdlePresenceMode.Orb);
    private void OnTrayRecenter(object? sender, EventArgs e) => _widget?.ResetOrbPosition();
    private void OnTrayQuit(object? sender, EventArgs e) => _widget?.Close();
}
