using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using System;

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
            _widget = new WidgetWindow();
            // --open radial|chat|system|tasks|models|settings : ouvre le menu au démarrage
            int i = System.Array.IndexOf(desktop.Args ?? System.Array.Empty<string>(), "--open");
            if (i >= 0 && i + 1 < desktop.Args!.Length) _widget.StartupAction = desktop.Args[i + 1];
            desktop.MainWindow = _widget;
            desktop.ShutdownMode = ShutdownMode.OnMainWindowClose;
        }

        base.OnFrameworkInitializationCompleted();
    }

    private void OnTrayClicked(object? sender, EventArgs e) => _widget?.ToggleMenu();
    private void OnTrayOpen(object? sender, EventArgs e) => _widget?.OpenPanel("chat");
    private void OnTrayRecenter(object? sender, EventArgs e) => _widget?.ResetOrbPosition();
    private void OnTrayQuit(object? sender, EventArgs e) => _widget?.Close();
}
