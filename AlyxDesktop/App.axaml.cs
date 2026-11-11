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

        string primaryHex = "#384C48";
        string secondaryHex = "#FBA620";

        // 5 Palettes d'accents supportées
        switch (settings.WatercolorPalette)
        {
            case "canopee-ambre":
                primaryHex = "#384C48";
                secondaryHex = "#FBA620";
                break;
            case "watercolor-duo":
                primaryHex = "#0284C7";
                secondaryHex = "#EC4899";
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
            default:
                primaryHex = "#384C48";
                secondaryHex = "#FBA620";
                break;
        }

        var primaryColor = Avalonia.Media.Color.Parse(primaryHex);
        var secondaryColor = Avalonia.Media.Color.Parse(secondaryHex);

        Current.Resources["Accent"] = new Avalonia.Media.SolidColorBrush(primaryColor);
        Current.Resources["AccentText"] = new Avalonia.Media.SolidColorBrush(
            settings.WatercolorPalette == "canopee-ambre" && isDark ? Avalonia.Media.Color.Parse("#FFE866") : primaryColor);
        Current.Resources["AccentBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(102, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentBorder28"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(71, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentBorder35"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(89, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentActivePill"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(38, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentTint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(28, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["AccentFocus"] = new Avalonia.Media.SolidColorBrush(
            settings.WatercolorPalette == "canopee-ambre" ? Avalonia.Media.Color.Parse("#FBA620") : Avalonia.Media.Color.FromArgb(115, primaryColor.R, primaryColor.G, primaryColor.B));
        Current.Resources["Danger"] = new Avalonia.Media.SolidColorBrush(secondaryColor);

        // Adaptation selon le style visuel actif et le mode sombre/clair
        string styleId = settings.ActiveVisualStyle ?? "canopee-ambre";

        if (isDark)
        {
            if (styleId == "canopee-ambre" || settings.WatercolorPalette == "canopee-ambre")
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
            else if (styleId == "kde")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#1B1E20"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#232629"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(242, 27, 30, 32));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#2A2E32"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#EFF0F1"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#BDC3C7"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3DAEE9"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#7F8C8D"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3DAEE9"));
            }
            else if (styleId == "gnome")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#1E1E1E"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#242424"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(242, 30, 30, 30));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#303030"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#D0D0D0"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3584E4"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#9A9996"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3584E4"));
            }
            else if (styleId == "eink")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#181818"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#1C1C1C"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(242, 24, 24, 24));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#262626"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F5F4F0"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#D4D4D4"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#71717A"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#A1A1AA"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#52525B"));
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
            if (styleId == "canopee-ambre" || settings.WatercolorPalette == "canopee-ambre")
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
            else if (styleId == "kde")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#EFF0F1"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#EFF0F1"));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#232629"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#31363B"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3DAEE9"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#7F8C8D"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3DAEE9"));
            }
            else if (styleId == "gnome")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FAFAFA"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FAFAFA"));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#EBEBEB"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#2E3436"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#555753"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3584E4"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#888A85"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3584E4"));
            }
            else if (styleId == "eink")
            {
                Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F5F4F0"));
                Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
                Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F5F4F0"));
                Current.Resources["NodeSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#EAE8E1"));
                Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#1C1C1C"));
                Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3F3F46"));
                Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#71717A"));
                Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#52525B"));
                Current.Resources["NeoBorder"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#71717A"));
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
