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

        string primaryHex = "#0284C7";
        string secondaryHex = "#EC4899";

        switch (settings.WatercolorPalette)
        {
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
            case "watercolor-duo":
            default:
                primaryHex = "#0284C7";
                secondaryHex = "#EC4899";
                break;
        }

        var primaryColor = Avalonia.Media.Color.Parse(primaryHex);
        var secondaryColor = Avalonia.Media.Color.Parse(secondaryHex);

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
            Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#0D0E12"));
            Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#11131A"));
            Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.FromArgb(242, 17, 19, 26));
            Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#F5F6FA"));
            Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#D4D4D8"));
            Current.Resources["TextBody"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#E4E4E7"));
            Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#A1A1AA"));
            Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#71717A"));
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
            Current.Resources["Bg"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FAF9F6"));
            Current.Resources["Surface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
            Current.Resources["PanelSurface"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#FFFFFF"));
            Current.Resources["Ink"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#14151A"));
            Current.Resources["Ink2"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#27272A"));
            Current.Resources["TextBody"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#3F3F46"));
            Current.Resources["Muted"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#71717A"));
            Current.Resources["Faint"] = new Avalonia.Media.SolidColorBrush(Avalonia.Media.Color.Parse("#A1A1AA"));
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
