using AlyxDesktop.Controls;
using AlyxDesktop.Platform;
using AlyxDesktop.Services;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.Linq;

namespace AlyxDesktop;

/// <summary>
/// Widget de bureau : fenêtre transparente, sans bordure, toujours au premier plan, qui ne couvre que la zone utile
/// (l'orbe au repos, l'orbe et son menu une fois ouvert) pour ne pas bloquer les clics sur le reste du bureau.
/// Toutes les coordonnées sont en DIP, relatives à la zone de travail de l'écran (hors barre des tâches).
/// </summary>
public partial class WidgetWindow : Window
{
    private enum MenuState { Idle, Radial, Panel }

    private const double OrbSize = 84, NodeSize = 72, RadialRadius = 124, RadialSpread = 200;
    private const double IdleMargin = 30, PanelShadow = 40;

    private static readonly (string Key, string Label)[] NodeDefs =
    {
        ("chat", "Chat"), ("system", "Système"), ("tasks", "Tâches"), ("media", "Lecture"), ("models", "Modèles"), ("settings", "Réglages"),
    };

    private readonly BackendClient _backend;
    private readonly WidgetSettings _settings = WidgetSettings.Load();
    private readonly HotkeyService _hotkey = new();
    private readonly Animator _anim;
    private readonly Button[] _nodes = new Button[NodeDefs.Length];
    private readonly StackPanel[] _nodeTexts = new StackPanel[NodeDefs.Length];
    private readonly NodeIcon[] _nodeIcons = new NodeIcon[NodeDefs.Length];
    private readonly Vector[] _nodeOffsets = new Vector[NodeDefs.Length];

    private MenuState _state = MenuState.Idle;
    /// <summary>Menu à ouvrir au démarrage (argument --open).</summary>
    public string? StartupAction { get; set; }
    private ScaleTransform OrbScale => (ScaleTransform)Orb.RenderTransform!;
    private PixelRect _workAreaPx;
    private double _scaling = 1;
    private Size _work;            // zone de travail en DIP
    private Point _orb;            // coin haut-gauche de l'orbe
    private Rect _window;          // rectangle actuel de la fenêtre
    private Rect _panelRect;
    private int _layoutVersion;

    // Glisser-déposer de l'orbe
    private PixelPoint? _pressScreen;
    private Point _pressOrb;
    private bool _dragging;

    public WidgetWindow()
    {
        InitializeComponent();
        _anim = new Animator(this);
        _backend = new BackendClient(ReadPort());

        Panel.Init(_backend, _settings);
        Panel.CloseRequested += () => ClosePanel();
        Panel.StateChanged += OnPanelStateChanged;
        Panel.FollowCursorChanged += f => OrbEye.FollowCursor = f;
        OrbEye.FollowCursor = _settings.EyeFollowsCursor;

        BuildNodes();
        // État fermé du panneau : sections masquées et décalées de 10 px
        _anim.Set("panelop", 0, v => PanelHost.Opacity = v);
        foreach (var (key, section) in new (string, Control)[] { ("secA", Panel.HeaderSection), ("secB", Panel.StatsSection), ("secC", Panel.BodySection), ("secD", Panel.MediaSection) })
        {
            var tr = new TranslateTransform();
            section.RenderTransform = tr;
            _anim.Set(key + "op", 0, v => section.Opacity = v);
            _anim.Set(key + "y", 10, v => tr.Y = v);
        }

        Orb.PointerPressed += OnOrbPressed;
        Orb.PointerMoved += OnOrbMoved;
        Orb.PointerReleased += OnOrbReleased;
        Viewport.PointerPressed += OnViewportPressed;
        KeyDown += OnKeyDown;
        Deactivated += (_, _) => { if (_state == MenuState.Radial) CloseRadial(); };

        _hotkey.Pressed += () =>
        {
            ToggleMenu();
            if (_state != MenuState.Idle) Activate();
        };

        Opened += OnOpened;
    }

    private static int ReadPort()
    {
        // Port WebSocket depuis config.yaml (server.port), 8765 par défaut
        try
        {
            if (Shell.AppRoot is { } root)
            {
                bool inServer = false;
                foreach (var raw in System.IO.File.ReadAllLines(System.IO.Path.Combine(root, "config.yaml")))
                {
                    var line = raw.TrimEnd();
                    if (line.Length > 0 && !char.IsWhiteSpace(line[0])) inServer = line.StartsWith("server:");
                    else if (inServer && line.Trim().StartsWith("port:") && int.TryParse(line.Split(':')[1].Trim(), out var port))
                        return port;
                }
            }
        }
        catch (System.IO.IOException) { }
        return 8765;
    }

    // ================= Démarrage et géométrie =================

    private void OnOpened(object? sender, EventArgs e)
    {
        var screen = Screens.ScreenFromWindow(this) ?? Screens.Primary;
        if (screen != null)
        {
            _workAreaPx = screen.WorkingArea;
            _scaling = screen.Scaling;
        }
        _work = new Size(_workAreaPx.Width / _scaling, _workAreaPx.Height / _scaling);
        Stage.Width = _work.Width;
        Stage.Height = _work.Height;

        _orb = ClampOrb(_settings.OrbX is { } x && _settings.OrbY is { } y ? new Point(x, y) : DefaultOrb());
        Hint.IsVisible = !_settings.EverOpened;
        LayoutOrb();
        ApplyWindowRect(IdleRect());
        Opacity = 1;

        _backend.Start();
        if (!_hotkey.Start()) Hint.Children.OfType<TextBlock>().Last().Text = "glisser pour déplacer";
        if (StartupAction is { } action)
            DispatcherTimer.RunOnce(() => { if (action == "radial") OpenRadial(); else OpenPanel(action); }, TimeSpan.FromMilliseconds(400));
    }

    private Point DefaultOrb() => new(_work.Width - 150, Math.Round(_work.Height * .36));

    private Point ClampOrb(Point p) => new(
        Math.Clamp(p.X, 8, Math.Max(8, _work.Width - OrbSize - 8)),
        Math.Clamp(p.Y, 8, Math.Max(8, _work.Height - OrbSize - 8)));

    private Point OrbCenter => new(_orb.X + OrbSize / 2, _orb.Y + OrbSize / 2);
    private Rect OrbRect => new(_orb.X, _orb.Y, OrbSize, OrbSize);

    private Rect IdleRect()
    {
        var r = OrbRect.Inflate(IdleMargin);
        if (Hint.IsVisible) r = r.Union(new Rect(_orb.X - 210, OrbCenter.Y - 26, 210, 52));
        return r;
    }

    private Rect RadialRect()
    {
        double half = RadialRadius + NodeSize / 2 + 16;
        return new Rect(OrbCenter.X - half, OrbCenter.Y - half, half * 2, half * 2);
    }

    private Rect PanelWindowRect() => _panelRect.Inflate(PanelShadow).Union(OrbRect.Inflate(IdleMargin));

    /// <summary>Déplace/redimensionne la fenêtre sur la zone donnée et recale la scène dessous.</summary>
    private void ApplyWindowRect(Rect r)
    {
        r = r.Intersect(new Rect(0, 0, _work.Width, _work.Height));
        // Alignement sur la grille de pixels physiques
        double s = _scaling;
        r = new Rect(Math.Round(r.X * s) / s, Math.Round(r.Y * s) / s, Math.Round(r.Width * s) / s, Math.Round(r.Height * s) / s);
        _window = r;
        Position = new PixelPoint(_workAreaPx.X + (int)Math.Round(r.X * s), _workAreaPx.Y + (int)Math.Round(r.Y * s));
        Width = Math.Max(1, r.Width);
        Height = Math.Max(1, r.Height);
        Canvas.SetLeft(Stage, -r.X);
        Canvas.SetTop(Stage, -r.Y);
    }

    /// <summary>Réduit la fenêtre à sa zone de repos une fois les animations de fermeture terminées.</summary>
    private void ShrinkWhenIdle()
    {
        int version = ++_layoutVersion;
        Dispatcher.UIThread.Post(() =>
        {
            if (version == _layoutVersion && _state == MenuState.Idle && !_anim.IsAnimating)
            {
                PanelHost.IsVisible = false;
                Viewport.Background = null;
                ApplyWindowRect(IdleRect());
            }
        }, DispatcherPriority.Background);
    }

    private void LayoutOrb()
    {
        Canvas.SetLeft(Orb, _orb.X);
        Canvas.SetTop(Orb, _orb.Y);
        Canvas.SetLeft(Hint, _orb.X - 200);
        Canvas.SetTop(Hint, OrbCenter.Y - 22);
        Hint.Width = 190;
    }

    public void ResetOrbPosition()
    {
        CloseAllImmediately();
        _orb = ClampOrb(DefaultOrb());
        _settings.OrbX = _settings.OrbY = null;
        _settings.Save();
        LayoutOrb();
        ApplyWindowRect(IdleRect());
    }

    // ================= Menu radial =================

    private void BuildNodes()
    {
        for (int i = 0; i < NodeDefs.Length; i++)
        {
            var label = new TextBlock { Text = NodeDefs[i].Label, FontSize = 12, FontWeight = FontWeight.SemiBold, HorizontalAlignment = HorizontalAlignment.Center };
            var value = new TextBlock
            {
                FontFamily = App.Res<FontFamily>("MonoFont"),
                FontSize = 9.5,
                Foreground = App.Res<IBrush>("AccentText"),
                HorizontalAlignment = HorizontalAlignment.Center,
                MaxWidth = 64,
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
            var textScale = new ScaleTransform(1, 1);
            var text = new StackPanel { Spacing = 3, VerticalAlignment = VerticalAlignment.Center, RenderTransform = textScale, Children = { label, value } };
            // Au survol, le texte s'efface et laisse place à l'icône animée de la bulle
            var icon = new NodeIcon { Kind = NodeDefs[i].Key, Width = 44, Height = 44, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
            icon.RevealChanged += r =>
            {
                double k = Math.Clamp(r, 0, 1);
                text.Opacity = 1 - k;
                textScale.ScaleX = textScale.ScaleY = 1 - .2 * k;
            };
            var node = new Button
            {
                Classes = { "flat", "node" },
                Tag = NodeDefs[i].Key,
                Content = new Panel { Children = { text, icon } },
                RenderTransform = new TransformGroup { Children = { new ScaleTransform(.3, .3), new TranslateTransform() } },
                Opacity = 0,
                IsHitTestVisible = false,
                Effect = new DropShadowEffect { OffsetX = 0, OffsetY = 10, BlurRadius = 30, Color = Color.FromArgb(0x1F, 0x14, 0x20, 0x1A) },
            };
            Avalonia.Automation.AutomationProperties.SetName(node, NodeDefs[i].Label);
            node.Click += OnNodeClick;
            node.PointerEntered += (_, _) => icon.Hovered = true;
            node.PointerExited += (_, _) => icon.Hovered = false;
            node.GotFocus += (_, e) => { if (e.NavigationMethod == NavigationMethod.Tab) icon.Hovered = true; };
            node.LostFocus += (_, _) => { if (!node.IsPointerOver) icon.Hovered = false; };
            _nodes[i] = node;
            _nodeTexts[i] = text;
            _nodeIcons[i] = icon;
            NodeLayer.Children.Add(node);
        }
        UpdateNodeValues();
    }

    private void LayoutNodes()
    {
        var c = OrbCenter;
        // L'arc de 200° est orienté vers le centre de l'écran : le menu s'ouvre toujours vers l'intérieur
        double baseAngle = Math.Atan2(_work.Height / 2 - c.Y, _work.Width / 2 - c.X);
        double spread = RadialSpread * Math.PI / 180;
        for (int i = 0; i < _nodes.Length; i++)
        {
            double a = baseAngle + ((double)i / (_nodes.Length - 1) - .5) * spread;
            _nodeOffsets[i] = new Vector(Math.Cos(a) * RadialRadius, Math.Sin(a) * RadialRadius);
            Canvas.SetLeft(_nodes[i], c.X + _nodeOffsets[i].X - NodeSize / 2);
            Canvas.SetTop(_nodes[i], c.Y + _nodeOffsets[i].Y - NodeSize / 2);
        }
    }

    private void SetNodeProgress(int i, double p)
    {
        var group = (TransformGroup)_nodes[i].RenderTransform!;
        var scale = (ScaleTransform)group.Children[0];
        var translate = (TranslateTransform)group.Children[1];
        scale.ScaleX = scale.ScaleY = .3 + .7 * p;
        translate.X = -_nodeOffsets[i].X * (1 - p);
        translate.Y = -_nodeOffsets[i].Y * (1 - p);
    }

    private void AnimateNodes(bool open, Action? done = null)
    {
        int n = _nodes.Length;
        for (int i = 0; i < n; i++)
        {
            int idx = i;
            double delay = open ? i * 45 : (n - i) * 25;
            _nodes[i].IsHitTestVisible = open;
            if (!open) _nodeIcons[i].Hovered = false;
            _anim.Animate($"node{i}", open ? 1 : 0, 420, CubicBezierEasing.Spring, p => SetNodeProgress(idx, p), delay,
                          done: i == 0 ? done : null);
            _anim.Animate($"nodeop{i}", open ? 1 : 0, 260, CubicBezierEasing.Standard, v => _nodes[idx].Opacity = v, delay);
        }
    }

    private void SetOrbScale(double target) =>
        _anim.Animate("orb", target, 420, CubicBezierEasing.OrbSpring, v => OrbScale.ScaleX = OrbScale.ScaleY = v);

    private void OpenRadial()
    {
        MarkOpened();
        _state = MenuState.Radial;
        _layoutVersion++;
        LayoutNodes();
        ApplyWindowRect(_window.Union(RadialRect()));
        Viewport.Background = Brushes.Transparent; // un clic hors des bulles referme le menu
        Panel.SetMenuActive(true);
        UpdateNodeValues();
        AnimateNodes(true);
        SetOrbScale(.92);
    }

    private void CloseRadial()
    {
        if (_state != MenuState.Radial) return;
        _state = MenuState.Idle;
        Panel.SetMenuActive(false);
        AnimateNodes(false, ShrinkWhenIdle);
        SetOrbScale(1);
    }

    private async void OnNodeClick(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string key }) return;
        if (key == "media")
        {
            await Panel.TogglePlayAsync();
            return;
        }
        OpenPanel(key);
    }

    private void OnPanelStateChanged()
    {
        OrbEye.Mode = Panel.EyeMode;
        Orb.Classes.Set("busy", Panel.EyeMode == EyeMode.Thinking);
        if (_state == MenuState.Radial) UpdateNodeValues();
    }

    private void UpdateNodeValues()
    {
        var media = Panel.Media;
        string model = string.IsNullOrEmpty(Panel.CurrentModel) || Panel.CurrentModel == "Aucun modèle"
            ? "aucun" : Panel.CurrentModel.Split(':', ' ', '/')[0];
        string firstWord = media.HasSession ? media.Title.Split(' ', StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "" : "aucun";
        string[] values =
        {
            "Demander",
            $"CPU {Panel.CpuPercent:0}%",
            Panel.ProcessTotal > 0 ? $"{Panel.ProcessTotal} proc." : "—",
            firstWord,
            model,
            "Rapide",
        };
        for (int i = 0; i < _nodes.Length; i++)
        {
            var stack = _nodeTexts[i];
            ((TextBlock)stack.Children[1]).Text = values[i];
            if (NodeDefs[i].Key == "media")
            {
                ((TextBlock)stack.Children[0]).Text = media.Playing ? "Pause" : "Lecture";
                _nodeIcons[i].Alternate = media.Playing;
            }
        }
    }

    // ================= Panneau =================

    private void ComputePanelRect()
    {
        double w = Math.Min(400, _work.Width - 24), h = Math.Min(600, _work.Height - 24);
        var c = OrbCenter;
        double left = c.X > _work.Width / 2 ? _orb.X - w - 16 : _orb.X + OrbSize + 16;
        if (left < 12 || left + w > _work.Width - 12) left = Math.Max(12, Math.Min(_work.Width - w - 12, left));
        double top = Math.Max(12, Math.Min(_work.Height - h - 12, c.Y - h / 2));
        _panelRect = new Rect(left, top, w, h);
    }

    public void OpenPanel(string tab)
    {
        MarkOpened();
        bool wasRadial = _state == MenuState.Radial;
        if (_state == MenuState.Panel)
        {
            Panel.SelectTab(tab);
            Activate();
            return;
        }
        _state = MenuState.Panel;
        _layoutVersion++;
        if (wasRadial) AnimateNodes(false);

        ComputePanelRect();
        Canvas.SetLeft(PanelHost, _panelRect.X);
        Canvas.SetTop(PanelHost, _panelRect.Y);
        PanelHost.Width = PanelCard.Width = _panelRect.Width;
        PanelHost.Height = PanelCard.Height = _panelRect.Height;
        ApplyWindowRect(_window.Union(PanelWindowRect()));
        Viewport.Background = Brushes.Transparent;
        PanelHost.IsVisible = true;
        PanelHost.IsHitTestVisible = true;
        Panel.SelectTab(tab);
        Panel.SetMenuActive(true);
        SetOrbScale(.92);

        // Révélation circulaire depuis le centre de l'orbe (clip-path: circle)
        var c = OrbCenter;
        double ox = c.X - _panelRect.X, oy = c.Y - _panelRect.Y, w = _panelRect.Width, h = _panelRect.Height;
        double radius = new[] { Hyp(ox, oy), Hyp(w - ox, oy), Hyp(ox, h - oy), Hyp(w - ox, h - oy) }.Max() + 30;
        _anim.Animate("clip", radius, 600, CubicBezierEasing.Panel, r => SetPanelClip(ox, oy, r),
                      done: () => PanelHost.Clip = null); // ombre complète une fois ouvert
        _anim.Animate("panelop", 1, 240, CubicBezierEasing.Standard, v => PanelHost.Opacity = v);
        RevealSection("secA", Panel.HeaderSection, true, 160);
        RevealSection("secB", Panel.StatsSection, true, 230);
        RevealSection("secC", Panel.BodySection, true, 300);
        RevealSection("secD", Panel.MediaSection, true, 300);
        Activate();
    }

    private static double Hyp(double x, double y) => Math.Sqrt(x * x + y * y);

    private void SetPanelClip(double ox, double oy, double r) =>
        PanelHost.Clip = new EllipseGeometry(new Rect(ox - r, oy - r, Math.Max(0, 2 * r), Math.Max(0, 2 * r)));

    /// <summary>Apparition décalée des sections : fondu 300 ms + montée de 10 px sur 400 ms.</summary>
    private void RevealSection(string key, Control section, bool open, double delay)
    {
        var t = (TranslateTransform)section.RenderTransform!;
        _anim.Animate(key + "op", open ? 1 : 0, 300, CubicBezierEasing.Standard, v => section.Opacity = v, open ? delay : 0);
        _anim.Animate(key + "y", open ? 0 : 10, 400, CubicBezierEasing.Standard, v => t.Y = v, open ? delay : 0);
    }

    public void ClosePanel()
    {
        if (_state != MenuState.Panel) return;
        _state = MenuState.Idle;
        Panel.SetMenuActive(false);
        PanelHost.IsHitTestVisible = false;
        var c = OrbCenter;
        double ox = c.X - _panelRect.X, oy = c.Y - _panelRect.Y;
        double current = PanelHost.Clip is EllipseGeometry g ? g.Rect.Width / 2 : _anim.Get("clip", 0);
        if (PanelHost.Clip == null)
        {
            double w = _panelRect.Width, h = _panelRect.Height;
            current = new[] { Hyp(ox, oy), Hyp(w - ox, oy), Hyp(ox, h - oy), Hyp(w - ox, h - oy) }.Max() + 30;
        }
        _anim.Animate("clip", 0, 600, CubicBezierEasing.Panel, r => SetPanelClip(ox, oy, r), from: current, done: ShrinkWhenIdle);
        _anim.Animate("panelop", 0, 240, CubicBezierEasing.Standard, v => PanelHost.Opacity = v);
        RevealSection("secA", Panel.HeaderSection, false, 0);
        RevealSection("secB", Panel.StatsSection, false, 0);
        RevealSection("secC", Panel.BodySection, false, 0);
        RevealSection("secD", Panel.MediaSection, false, 0);
        SetOrbScale(1);
    }

    // ================= Interactions =================

    public void ToggleMenu()
    {
        switch (_state)
        {
            case MenuState.Panel: ClosePanel(); break;
            case MenuState.Radial: CloseRadial(); break;
            default: OpenRadial(); break;
        }
    }

    private void CloseAll()
    {
        if (_state == MenuState.Panel) ClosePanel();
        else if (_state == MenuState.Radial) CloseRadial();
    }

    private void CloseAllImmediately()
    {
        _state = MenuState.Idle;
        Panel.SetMenuActive(false);
        for (int i = 0; i < _nodes.Length; i++)
        {
            int idx = i;
            _anim.Set($"node{i}", 0, p => SetNodeProgress(idx, p));
            _anim.Set($"nodeop{i}", 0, v => _nodes[idx].Opacity = v);
            _nodes[i].IsHitTestVisible = false;
        }
        _anim.Set("clip", 0, _ => { });
        _anim.Set("panelop", 0, v => PanelHost.Opacity = v);
        _anim.Set("orb", 1, v => OrbScale.ScaleX = OrbScale.ScaleY = v);
        PanelHost.IsVisible = false;
        Viewport.Background = null;
    }

    private void MarkOpened()
    {
        if (_settings.EverOpened) return;
        _settings.EverOpened = true;
        _settings.Save();
        Hint.IsVisible = false;
    }

    private void OnKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            CloseAll();
            e.Handled = true;
        }
    }

    private void OnViewportPressed(object? sender, PointerPressedEventArgs e)
    {
        // Clic sur une zone vide de la fenêtre (hors orbe, bulles et panneau)
        if (e.Source == Viewport) CloseAll();
    }

    private PixelPoint ScreenPoint(PointerEventArgs e) => this.PointToScreen(e.GetPosition(this));

    private void OnOrbPressed(object? sender, PointerPressedEventArgs e)
    {
        if (!e.GetCurrentPoint(Orb).Properties.IsLeftButtonPressed) return;
        _pressScreen = ScreenPoint(e);
        _pressOrb = _orb;
        _dragging = false;
        e.Pointer.Capture(Orb);
        e.Handled = true;
    }

    private void OnOrbMoved(object? sender, PointerEventArgs e)
    {
        if (_pressScreen is not { } start) return;
        var now = ScreenPoint(e);
        var delta = new Vector((now.X - start.X) / _scaling, (now.Y - start.Y) / _scaling);
        if (!_dragging && delta.Length > 5)
        {
            _dragging = true;
            Orb.Cursor = new Cursor(StandardCursorType.SizeAll);
            if (_state != MenuState.Idle) CloseAllImmediately();
        }
        if (!_dragging) return;
        _orb = ClampOrb(_pressOrb + delta);
        LayoutOrb();
        ApplyWindowRect(IdleRect());
    }

    private void OnOrbReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (_pressScreen == null) return;
        _pressScreen = null;
        e.Pointer.Capture(null);
        Orb.Cursor = new Cursor(StandardCursorType.Hand);
        if (_dragging)
        {
            _dragging = false;
            _settings.OrbX = _orb.X;
            _settings.OrbY = _orb.Y;
            _settings.Save();
        }
        else
        {
            ToggleMenu();
        }
        e.Handled = true;
    }

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        _hotkey.Dispose();
        // Arrête aussi le backend Python et le STT (comme l'ancienne fenêtre)
        _backend.SendBlocking(new { type = "shutdown" }, TimeSpan.FromSeconds(1));
    }
}
