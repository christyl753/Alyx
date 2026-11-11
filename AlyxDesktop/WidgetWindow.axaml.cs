using AlyxDesktop.Controls;
using AlyxDesktop.Platform;
using AlyxDesktop.Services;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.Linq;

namespace AlyxDesktop;

/// <summary>
/// Widget de bureau : fenêtre transparente, sans bordure, toujours au premier plan, qui ne couvre que la zone utile
/// (languette / orbe au repos, panneau seul en Card/Side, zone de travail avec voile en Overlay) afin de ne pas bloquer
/// les clics sur le reste du bureau. Toutes les coordonnées sont en DIP, relatives à la zone de travail de l'écran.
/// </summary>
public partial class WidgetWindow : Window
{
    private enum MenuState { Idle, Radial, Panel }

    private const double OrbSize = 84, MiniOrbSize = 48, OrbEyeSize = 72, MiniOrbEyeSize = 40;
    private const double EdgeTabCollapsedW = 10, EdgeTabExpandedW = 36, EdgeTabH = 56, EdgeTabMargin = 16;
    private const double NodeSize = 72, RadialRadius = 106;
    private const double IdleMargin = 30, PanelShadow = 40;

    private static readonly (string Key, string Label)[] NodeDefs =
    {
        ("assistant", "Assistant"),
        ("scanner", "Scanner"),
        ("guardrail", "Garde-fou"),
        ("automations", "Automates"),
        ("appearance", "Style")
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
    public PanelLayoutMode CurrentPanelLayout => _settings.PanelLayout;
    public IdlePresenceMode CurrentIdleMode => _settings.IdleMode;
    public event Action? SettingsChanged;

    private ScaleTransform OrbScale => (ScaleTransform)Orb.RenderTransform!;
    private PixelRect _workAreaPx;
    private double _scaling = 1;
    private Size _work;            // zone de travail en DIP
    private Point _orb;            // coin haut-gauche de l'orbe
    private double _edgeTabY;      // position verticale de la languette
    private double _edgeTabHover;  // 0 (10 px) .. 1 (36 px)
    private double _edgeTabHide;   // 0 (visible) .. 1 (escamotée)
    private Rect _window;          // rectangle actuel de la fenêtre
    private Rect _panelRect;
    private int _layoutVersion;

    // Glisser-déposer de l'orbe ou de la languette
    private PixelPoint? _pressScreen;
    private Point _pressOrb;
    private double _pressTabY;
    private bool _dragging;
    private bool _draggingTab;

    public WidgetWindow()
    {
        InitializeComponent();
        _anim = new Animator(this);
        _backend = new BackendClient(ReadPort());

        Panel.Init(_backend, _settings);
        Panel.CloseRequested += () => ClosePanel();
        Panel.StateChanged += OnPanelStateChanged;
        Panel.LayoutRequested += SwitchPanelLayout;
        Panel.EntryModeRequested += SetEntryMode;
        Panel.IdleModeRequested += SetIdlePresenceMode;
        Panel.StyleSettingsChanged += OnStyleSettingsChanged;
        Panel.DockSideRequested += SetDockSide;
        PanelCard.Opacity = Math.Clamp(_settings.WidgetOpacityPercent / 100.0, 0.82, 1.0);
        UpdateEdgeTabCornerRadius();
        Panel.FollowCursorChanged += f =>
        {
            OrbEye.FollowCursor = f;
            EdgeTabEye.FollowCursor = f;
        };
        OrbEye.FollowCursor = _settings.EyeFollowsCursor;
        EdgeTabEye.FollowCursor = _settings.EyeFollowsCursor;

        BuildNodes();
        // État fermé du panneau : sections masquées et décalées de 10 px
        _anim.Set("panelop", 0, v => PanelHost.Opacity = v);
        _anim.Set("scrimop", 0, v => Scrim.Opacity = v);
        _anim.Set("orb", 1, v => OrbScale.ScaleX = OrbScale.ScaleY = v);
        _anim.Set("orbop", 1, v => Orb.Opacity = v);
        _anim.Set("tabhover", 0, v => _edgeTabHover = v);
        _anim.Set("tabhide", 0, v => _edgeTabHide = v);
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

        EdgeTab.PointerEntered += OnEdgeTabEntered;
        EdgeTab.PointerExited += OnEdgeTabExited;
        EdgeTab.PointerPressed += OnEdgeTabPressed;
        EdgeTab.PointerMoved += OnEdgeTabMoved;
        EdgeTab.PointerReleased += OnEdgeTabReleased;

        Scrim.PointerPressed += OnScrimPressed;
        Viewport.PointerPressed += OnViewportPressed;
        AddHandler(KeyDownEvent, OnKeyDown, RoutingStrategies.Tunnel);
        Deactivated += (_, _) => { if (_state == MenuState.Radial) CloseRadial(); };

        _hotkey.Pressed += ToggleFromExternal;

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

    private void NotifySettingsChanged()
    {
        Panel.SyncWidgetModeUI();
        SettingsChanged?.Invoke();
    }

    private static OpenEntryMode ToEntryMode(PanelLayoutMode layout) => layout switch
    {
        PanelLayoutMode.Side => OpenEntryMode.Side,
        PanelLayoutMode.Overlay => OpenEntryMode.Overlay,
        _ => OpenEntryMode.Card,
    };

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
        Scrim.Width = _work.Width;
        Scrim.Height = _work.Height;

        _orb = ClampOrb(_settings.OrbX is { } x && _settings.OrbY is { } y ? new Point(x, y) : DefaultOrb());
        _edgeTabY = ClampEdgeTabY(_settings.EdgeTabY ?? DefaultEdgeTabY());
        Hint.IsVisible = !_settings.EverOpened && _settings.IdleMode != IdlePresenceMode.Stealth;

        ApplyIdleWindowState();

        _backend.Start();
        if (!_hotkey.Start()) HintSub.Text = "glisser pour déplacer";
        if (StartupAction is { } action)
        {
            DispatcherTimer.RunOnce(() =>
            {
                switch (action)
                {
                    case "radial": OpenRadial(); break;
                    case "card": SelectPanelLayoutFromTray(PanelLayoutMode.Card); break;
                    case "side": SelectPanelLayoutFromTray(PanelLayoutMode.Side); break;
                    case "overlay": SelectPanelLayoutFromTray(PanelLayoutMode.Overlay); break;
                    default: OpenPanel(action); break;
                }
            }, TimeSpan.FromMilliseconds(400));
        }
    }

    private double CurrentOrbSize => _settings.IdleMode == IdlePresenceMode.MiniOrb ? MiniOrbSize : OrbSize;
    private double CurrentOrbEyeSize => _settings.IdleMode == IdlePresenceMode.MiniOrb ? MiniOrbEyeSize : OrbEyeSize;
    private bool IsTriggerHidden(PanelLayoutMode layout) =>
        _settings.IdleMode == IdlePresenceMode.Stealth || layout is PanelLayoutMode.Side or PanelLayoutMode.Overlay;

    private Point DefaultOrb() => new(_work.Width - 150, Math.Round(_work.Height * .36));
    private double DefaultEdgeTabY() => Math.Round(_work.Height * .36);

    private Point ClampOrb(Point p)
    {
        double sz = CurrentOrbSize;
        return new Point(
            Math.Clamp(p.X, 8, Math.Max(8, _work.Width - sz - 8)),
            Math.Clamp(p.Y, 8, Math.Max(8, _work.Height - sz - 8)));
    }

    private double ClampEdgeTabY(double y) =>
        Math.Clamp(y, 12, Math.Max(12, _work.Height - EdgeTabH - 12));

    private Point OrbCenter => new(_orb.X + CurrentOrbSize / 2, _orb.Y + CurrentOrbSize / 2);
    private Rect OrbRect => new(_orb.X, _orb.Y, CurrentOrbSize, CurrentOrbSize);

    private double EdgeTabCurrentWidth => EdgeTabCollapsedW + (EdgeTabExpandedW - EdgeTabCollapsedW) * _edgeTabHover;

    private Point EdgeTabCenter => _settings.DockSide == EdgeDockSide.Right
        ? new Point(_work.Width - EdgeTabCollapsedW / 2, _edgeTabY + EdgeTabH / 2)
        : new Point(EdgeTabCollapsedW / 2, _edgeTabY + EdgeTabH / 2);

    private Rect EdgeTabMaxRect => _settings.DockSide == EdgeDockSide.Right
        ? new Rect(_work.Width - EdgeTabExpandedW - EdgeTabMargin, _edgeTabY - EdgeTabMargin, EdgeTabExpandedW + EdgeTabMargin, EdgeTabH + EdgeTabMargin * 2)
        : new Rect(0, _edgeTabY - EdgeTabMargin, EdgeTabExpandedW + EdgeTabMargin, EdgeTabH + EdgeTabMargin * 2);

    private Point TriggerCenter => _settings.IdleMode switch
    {
        IdlePresenceMode.EdgeTab => EdgeTabCenter,
        IdlePresenceMode.Stealth => new Point(_work.Width - 24, _work.Height - 24),
        _ => OrbCenter,
    };

    private Point RevealOrigin(PanelLayoutMode layout)
    {
        if (_settings.IdleMode == IdlePresenceMode.Stealth)
            return layout == PanelLayoutMode.Overlay
                ? new Point(_work.Width / 2, _work.Height / 2)
                : new Point(_work.Width - 24, _work.Height - 24);
        return TriggerCenter;
    }

    private Point RadialCenter()
    {
        var c = _settings.IdleMode == IdlePresenceMode.Stealth
            ? new Point(_work.Width - 150 + OrbSize / 2, Math.Round(_work.Height * .36) + OrbSize / 2)
            : TriggerCenter;
        const double pad = 56;
        return new Point(
            Math.Clamp(c.X, pad, Math.Max(pad, _work.Width - pad)),
            Math.Clamp(c.Y, pad, Math.Max(pad, _work.Height - pad)));
    }

    private Rect TriggerIdleRect() => _settings.IdleMode switch
    {
        IdlePresenceMode.Stealth => new Rect(Math.Max(0, _work.Width - 2), Math.Max(0, _work.Height - 2), 1, 1),
        IdlePresenceMode.EdgeTab => EdgeTabMaxRect,
        _ => OrbRect.Inflate(IdleMargin),
    };

    private Rect HintRect()
    {
        double hx = Canvas.GetLeft(Hint);
        double hy = Canvas.GetTop(Hint);
        if (double.IsNaN(hx)) hx = 0;
        if (double.IsNaN(hy)) hy = 0;
        return new Rect(hx - 6, hy - 6, 202, 52);
    }

    private Rect IdleRect()
    {
        if (_settings.IdleMode == IdlePresenceMode.Stealth)
            return new Rect(Math.Max(0, _work.Width - 2), Math.Max(0, _work.Height - 2), 1, 1);

        var r = TriggerIdleRect();
        if (Hint.IsVisible) r = r.Union(HintRect());
        return r;
    }

    private Rect RadialRect()
    {
        var c = RadialCenter();
        double half = RadialRadius + NodeSize / 2 + 16;
        return new Rect(c.X - half, c.Y - half, half * 2, half * 2);
    }

    private Rect ActivePanelWindowRect(PanelLayoutMode mode)
    {
        if (mode == PanelLayoutMode.Overlay)
            return new Rect(0, 0, _work.Width, _work.Height);

        var r = _panelRect.Inflate(PanelShadow);
        if (!IsTriggerHidden(mode))
            r = r.Union(TriggerIdleRect());
        return r;
    }

    /// <summary>Déplace/redimensionne la fenêtre sur la zone donnée et recale la scène dessous.</summary>
    private void ApplyWindowRect(Rect r)
    {
        r = r.Intersect(new Rect(0, 0, _work.Width, _work.Height));
        if (r.Width <= 0 || r.Height <= 0)
            r = new Rect(Math.Max(0, _work.Width - 2), Math.Max(0, _work.Height - 2), 1, 1);
        // Alignement sur la grille de pixels physiques
        double s = _scaling;
        r = new Rect(Math.Round(r.X * s) / s, Math.Round(r.Y * s) / s, Math.Max(1, Math.Round(r.Width * s) / s), Math.Max(1, Math.Round(r.Height * s) / s));
        _window = r;
        Position = new PixelPoint(_workAreaPx.X + (int)Math.Round(r.X * s), _workAreaPx.Y + (int)Math.Round(r.Y * s));
        Width = Math.Max(1, r.Width);
        Height = Math.Max(1, r.Height);
        Canvas.SetLeft(Stage, -r.X);
        Canvas.SetTop(Stage, -r.Y);
    }

    private void SyncIdleControlsVisibility()
    {
        if (_settings.IdleMode == IdlePresenceMode.Stealth)
        {
            Orb.IsVisible = false;
            Orb.IsHitTestVisible = false;
            EdgeTab.IsVisible = false;
            EdgeTab.IsHitTestVisible = false;
            EdgeTabEye.IsVisible = false;
            return;
        }

        bool hide = _state == MenuState.Panel && IsTriggerHidden(_settings.PanelLayout);
        if (_settings.IdleMode == IdlePresenceMode.EdgeTab)
        {
            Orb.IsVisible = false;
            Orb.IsHitTestVisible = false;
            _anim.Set("tabhide", hide ? 1 : 0, v => _edgeTabHide = v);
            if (hide) _anim.Set("tabhover", 0, v => _edgeTabHover = v);
            EdgeTab.IsVisible = !hide;
            EdgeTab.IsHitTestVisible = !hide;
        }
        else
        {
            EdgeTab.IsVisible = false;
            EdgeTab.IsHitTestVisible = false;
            EdgeTabEye.IsVisible = false;
            _anim.Set("tabhover", 0, v => _edgeTabHover = v);
            double scale = hide ? 0.4 : (_state != MenuState.Idle ? 0.92 : 1.0);
            _anim.Set("orb", scale, v => OrbScale.ScaleX = OrbScale.ScaleY = v);
            _anim.Set("orbop", hide ? 0 : 1, v => Orb.Opacity = v);
            Orb.IsVisible = !hide;
            Orb.IsHitTestVisible = !hide;
        }
    }

    private void ApplyIdleWindowState()
    {
        PanelHost.IsVisible = false;
        Scrim.IsVisible = false;
        Scrim.IsHitTestVisible = false;
        Viewport.Background = null;
        SyncIdleControlsVisibility();
        LayoutTrigger();
        ApplyWindowRect(IdleRect());
        if (_settings.IdleMode == IdlePresenceMode.Stealth)
        {
            Opacity = 0;
            IsHitTestVisible = false;
        }
        else
        {
            Opacity = 1;
            IsHitTestVisible = true;
        }
    }

    /// <summary>Réduit la fenêtre à sa zone de repos une fois les animations de fermeture terminées.</summary>
    private void ShrinkWhenIdle()
    {
        int version = ++_layoutVersion;
        Dispatcher.UIThread.Post(() =>
        {
            if (version == _layoutVersion && _state == MenuState.Idle && !_anim.IsAnimating)
                ApplyIdleWindowState();
        }, DispatcherPriority.Background);
    }

    private void ApplyOrbSizing()
    {
        double sz = CurrentOrbSize;
        double eyeSz = CurrentOrbEyeSize;
        Orb.Width = Orb.Height = sz;
        Orb.CornerRadius = new CornerRadius(sz / 2);
        OrbEye.Width = OrbEye.Height = eyeSz;
    }

    private void LayoutHint()
    {
        Hint.Width = 190;
        if (_settings.IdleMode == IdlePresenceMode.EdgeTab)
        {
            bool right = _settings.DockSide == EdgeDockSide.Right;
            HintTitle.HorizontalAlignment = HintSub.HorizontalAlignment = right ? HorizontalAlignment.Right : HorizontalAlignment.Left;
            double hx = right ? _work.Width - EdgeTabExpandedW - 14 - 190 : EdgeTabExpandedW + 14;
            double hy = Math.Clamp(_edgeTabY + EdgeTabH / 2 - 20, 12, Math.Max(12, _work.Height - 52));
            Canvas.SetLeft(Hint, hx);
            Canvas.SetTop(Hint, hy);
        }
        else
        {
            bool onRight = OrbCenter.X >= _work.Width / 2;
            HintTitle.HorizontalAlignment = HintSub.HorizontalAlignment = onRight ? HorizontalAlignment.Right : HorizontalAlignment.Left;
            double hx = onRight ? _orb.X - 200 : _orb.X + CurrentOrbSize + 10;
            double hy = Math.Clamp(OrbCenter.Y - 20, 12, Math.Max(12, _work.Height - 52));
            Canvas.SetLeft(Hint, hx);
            Canvas.SetTop(Hint, hy);
        }
    }

    private void LayoutTrigger()
    {
        ApplyOrbSizing();
        Canvas.SetLeft(Orb, _orb.X);
        Canvas.SetTop(Orb, _orb.Y);

        double w = EdgeTabCurrentWidth;
        double hideShift = w * _edgeTabHide;
        bool right = _settings.DockSide == EdgeDockSide.Right;
        EdgeTab.Width = w;
        EdgeTab.Height = EdgeTabH;
        EdgeTab.CornerRadius = right ? new CornerRadius(12, 0, 0, 12) : new CornerRadius(0, 12, 12, 0);
        EdgeTab.BorderThickness = right ? new Thickness(1, 1, 0, 1) : new Thickness(0, 1, 1, 1);
        EdgeTab.Opacity = 1 - _edgeTabHide;
        Canvas.SetLeft(EdgeTab, right ? _work.Width - w + hideShift : -hideShift);
        Canvas.SetTop(EdgeTab, _edgeTabY);

        EdgeTabBar.Opacity = Math.Clamp(1 - _edgeTabHover * 1.4, 0, 1);
        EdgeTabEye.Opacity = Math.Clamp((_edgeTabHover - 0.15) / 0.85, 0, 1);
        EdgeTabEye.IsVisible = EdgeTab.IsVisible && _edgeTabHover > 0.02;

        LayoutHint();
    }

    public void ResetOrbPosition()
    {
        CloseAllImmediately();
        _settings.OrbX = _settings.OrbY = null;
        _settings.EdgeTabY = null;
        _settings.DockSide = EdgeDockSide.Right;
        _settings.Save();
        _orb = ClampOrb(DefaultOrb());
        _edgeTabY = ClampEdgeTabY(DefaultEdgeTabY());
        NotifySettingsChanged();
        ApplyIdleWindowState();
    }

    public void SetEntryMode(OpenEntryMode mode)
    {
        _settings.EntryMode = mode;
        if (mode != OpenEntryMode.Radial)
        {
            var targetLayout = mode switch
            {
                OpenEntryMode.Side => PanelLayoutMode.Side,
                OpenEntryMode.Overlay => PanelLayoutMode.Overlay,
                _ => PanelLayoutMode.Card,
            };
            if (_state == MenuState.Panel && _settings.PanelLayout != targetLayout)
            {
                SwitchPanelLayout(targetLayout);
                return;
            }
            _settings.PanelLayout = targetLayout;
        }
        _settings.Save();
        NotifySettingsChanged();
    }

    public void SetIdlePresenceMode(IdlePresenceMode mode)
    {
        if (_settings.IdleMode == mode && _work.Width > 0)
        {
            NotifySettingsChanged();
            return;
        }

        _settings.IdleMode = mode;
        if (_work.Width > 0)
        {
            _orb = ClampOrb(_orb);
            _edgeTabY = ClampEdgeTabY(_edgeTabY);
        }
        _settings.Save();
        NotifySettingsChanged();

        if (_work.Width <= 0) return;

        if (mode == IdlePresenceMode.Stealth)
            Hint.IsVisible = false;

        SyncIdleControlsVisibility();
        LayoutTrigger();

        if (_state == MenuState.Idle)
        {
            ApplyIdleWindowState();
        }
        else if (_state == MenuState.Radial)
        {
            Opacity = 1;
            IsHitTestVisible = true;
            LayoutNodes();
            var r = RadialRect();
            if (mode != IdlePresenceMode.Stealth) r = r.Union(TriggerIdleRect());
            ApplyWindowRect(r);
        }
        else if (_state == MenuState.Panel)
        {
            Opacity = 1;
            IsHitTestVisible = true;
            if (_settings.PanelLayout == PanelLayoutMode.Card)
                MorphPanelToLayout(PanelLayoutMode.Card);
            else
                ApplyWindowRect(ActivePanelWindowRect(_settings.PanelLayout));
        }
    }

    public void SelectPanelLayoutFromTray(PanelLayoutMode target)
    {
        if (_state == MenuState.Panel)
        {
            SwitchPanelLayout(target);
            Activate();
            return;
        }

        _settings.PanelLayout = target;
        if (_settings.EntryMode != OpenEntryMode.Radial)
            _settings.EntryMode = ToEntryMode(target);
        _settings.Save();
        NotifySettingsChanged();
        OpenPanel(Panel.ActiveTab);
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
        var c = RadialCenter();
        const double startAngleDeg = -160.0;
        const double endAngleDeg = -20.0;
        double spread = _nodes.Length > 1 ? (endAngleDeg - startAngleDeg) / (_nodes.Length - 1) : 0;
        for (int i = 0; i < _nodes.Length; i++)
        {
            double angleDeg = startAngleDeg + i * spread;
            double a = angleDeg * Math.PI / 180.0;
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

    private void AnimateTriggerForPanel(bool open, PanelLayoutMode layout, double durationMs)
    {
        if (_settings.IdleMode == IdlePresenceMode.Stealth) return;

        bool hide = open && IsTriggerHidden(layout);
        if (_settings.IdleMode == IdlePresenceMode.EdgeTab)
        {
            if (!hide)
            {
                EdgeTab.IsVisible = true;
                EdgeTab.IsHitTestVisible = true;
            }
            else
            {
                EdgeTab.IsHitTestVisible = false;
                _anim.Animate("tabhover", 0, 160, CubicBezierEasing.Standard, v => { _edgeTabHover = v; LayoutTrigger(); }, from: _edgeTabHover);
            }
            _anim.Animate("tabhide", hide ? 1 : 0, durationMs, CubicBezierEasing.Panel,
                          v => { _edgeTabHide = v; LayoutTrigger(); },
                          from: _edgeTabHide,
                          done: () =>
                          {
                              if (hide && _state == MenuState.Panel && IsTriggerHidden(_settings.PanelLayout))
                              {
                                  EdgeTab.IsVisible = false;
                                  EdgeTabEye.IsVisible = false;
                              }
                          });
        }
        else
        {
            if (!hide)
            {
                Orb.IsVisible = true;
                Orb.IsHitTestVisible = true;
            }
            else
            {
                Orb.IsHitTestVisible = false;
            }
            double targetScale = hide ? 0.4 : (open ? 0.92 : 1.0);
            double targetOp = hide ? 0.0 : 1.0;
            _anim.Animate("orb", targetScale, durationMs, CubicBezierEasing.OrbSpring, v => OrbScale.ScaleX = OrbScale.ScaleY = v);
            _anim.Animate("orbop", targetOp, Math.Min(300, durationMs), CubicBezierEasing.Standard, v => Orb.Opacity = v, from: Orb.Opacity,
                          done: () =>
                          {
                              if (hide && _state == MenuState.Panel && IsTriggerHidden(_settings.PanelLayout))
                                  Orb.IsVisible = false;
                          });
        }
    }

    private void OpenRadial()
    {
        MarkOpened();
        Opacity = 1;
        IsHitTestVisible = true;
        _state = MenuState.Radial;
        _layoutVersion++;
        LayoutNodes();
        var winRect = RadialRect();
        if (_settings.IdleMode != IdlePresenceMode.Stealth) winRect = winRect.Union(TriggerIdleRect());
        ApplyWindowRect(_window.Union(winRect));
        Viewport.Background = Brushes.Transparent; // un clic hors des bulles referme le menu radial
        Panel.SetMenuActive(true);
        UpdateNodeValues();
        AnimateNodes(true);
        if (_settings.IdleMode is IdlePresenceMode.Orb or IdlePresenceMode.MiniOrb)
            _anim.Animate("orb", .92, 420, CubicBezierEasing.OrbSpring, v => OrbScale.ScaleX = OrbScale.ScaleY = v);
    }

    private void CloseRadial()
    {
        if (_state != MenuState.Radial) return;
        _state = MenuState.Idle;
        Panel.SetMenuActive(false);
        AnimateNodes(false, ShrinkWhenIdle);
        if (_settings.IdleMode is IdlePresenceMode.Orb or IdlePresenceMode.MiniOrb)
            _anim.Animate("orb", 1, 420, CubicBezierEasing.OrbSpring, v => OrbScale.ScaleX = OrbScale.ScaleY = v);
    }

    private void OnNodeClick(object? sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string key }) return;
        OpenPanel(key);
    }

    private void OnPanelStateChanged()
    {
        OrbEye.Mode = Panel.EyeMode;
        EdgeTabEye.Mode = Panel.EyeMode;
        bool busy = Panel.EyeMode == EyeMode.Thinking;
        Orb.Classes.Set("busy", busy);
        EdgeTab.Classes.Set("busy", busy);
        if (_state == MenuState.Radial) UpdateNodeValues();
    }

    private void UpdateNodeValues()
    {
        string[] values =
        {
            "Demander",
            "Analyser",
            "Sécurité",
            "Routines",
            "Couleurs",
        };
        for (int i = 0; i < _nodes.Length; i++)
        {
            var stack = _nodeTexts[i];
            if (i < values.Length)
                ((TextBlock)stack.Children[1]).Text = values[i];
        }
    }

    // ================= Panneau (Card / Side / Overlay) =================

    /// <summary>Géométries exactes fidèles à Jane Fresh.dc.html:514-532.</summary>
    private Rect ComputePanelRect(PanelLayoutMode mode)
    {
        if (mode == PanelLayoutMode.Side)
        {
            double w = Math.Min(440, _work.Width - 24);
            double h = Math.Max(240, _work.Height - 24);
            bool dockLeft = _settings.IdleMode == IdlePresenceMode.EdgeTab && _settings.DockSide == EdgeDockSide.Left;
            double left = dockLeft ? 12 : Math.Max(12, _work.Width - w - 12);
            return new Rect(left, 12, w, h);
        }

        if (mode == PanelLayoutMode.Overlay)
        {
            double w = Math.Min(1000, Math.Max(280, _work.Width - 64));
            double h = Math.Min(680, Math.Max(240, _work.Height - 72));
            double left = Math.Max(12, (_work.Width - w) / 2);
            double top = Math.Max(12, (_work.Height - h) / 2);
            return new Rect(left, top, w, h);
        }

        // Card
        {
            double w = Math.Min(400, _work.Width - 24);
            double h = Math.Min(600, _work.Height - 24);
            if (_settings.IdleMode == IdlePresenceMode.Stealth)
            {
                double sLeft = Math.Max(12, _work.Width - w - 12);
                double sTop = Math.Max(12, _work.Height - h - 12);
                return new Rect(sLeft, sTop, w, h);
            }

            if (_settings.IdleMode == IdlePresenceMode.EdgeTab)
            {
                var tc = EdgeTabCenter;
                double eLeft = _settings.DockSide == EdgeDockSide.Right
                    ? _work.Width - EdgeTabCollapsedW - w - 12
                    : EdgeTabCollapsedW + 12;
                eLeft = Math.Max(12, Math.Min(_work.Width - w - 12, eLeft));
                double eTop = Math.Max(12, Math.Min(_work.Height - h - 12, tc.Y - h / 2));
                return new Rect(eLeft, eTop, w, h);
            }

            double orbSz = CurrentOrbSize;
            var c = OrbCenter;
            double left = c.X > _work.Width / 2 ? _orb.X - w - 16 : _orb.X + orbSz + 16;
            if (left < 12 || left + w > _work.Width - 12) left = Math.Max(12, Math.Min(_work.Width - w - 12, left));
            double top = Math.Max(12, Math.Min(_work.Height - h - 12, c.Y - h / 2));
            return new Rect(left, top, w, h);
        }
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

        Opacity = 1;
        IsHitTestVisible = true;
        _state = MenuState.Panel;
        int openVersion = ++_layoutVersion;
        if (wasRadial) AnimateNodes(false);

        var layout = _settings.PanelLayout;
        _panelRect = ComputePanelRect(layout);
        _anim.Set("px", _panelRect.X, v => Canvas.SetLeft(PanelHost, v));
        _anim.Set("py", _panelRect.Y, v => Canvas.SetTop(PanelHost, v));
        _anim.Set("pw", _panelRect.Width, v => PanelHost.Width = PanelCard.Width = v);
        _anim.Set("ph", _panelRect.Height, v => PanelHost.Height = PanelCard.Height = v);

        var targetWin = ActivePanelWindowRect(layout);
        var initialWin = _settings.IdleMode == IdlePresenceMode.Stealth ? targetWin : _window.Union(targetWin).Union(TriggerIdleRect());
        ApplyWindowRect(initialWin);
        Viewport.Background = null; // Ne bloque jamais les clics sur le reste du bureau en Card / Side

        if (layout == PanelLayoutMode.Overlay)
        {
            Scrim.Width = _work.Width;
            Scrim.Height = _work.Height;
            Scrim.IsVisible = true;
            Scrim.IsHitTestVisible = true;
            _anim.Animate("scrimop", 1, 400, CubicBezierEasing.Standard, v => Scrim.Opacity = v, from: Scrim.Opacity);
        }
        else
        {
            Scrim.IsVisible = false;
            Scrim.IsHitTestVisible = false;
            _anim.Set("scrimop", 0, v => Scrim.Opacity = v);
        }

        PanelHost.IsVisible = true;
        PanelHost.IsHitTestVisible = true;
        Panel.SyncWidgetModeUI();
        Panel.SelectTab(tab);
        Panel.SetMenuActive(true);
        AnimateTriggerForPanel(open: true, layout: layout, durationMs: 420);

        // Révélation circulaire depuis l'origine du déclencheur (clip-path: circle)
        var c = RevealOrigin(layout);
        double ox = c.X - _panelRect.X, oy = c.Y - _panelRect.Y, w = _panelRect.Width, h = _panelRect.Height;
        double radius = new[] { Hyp(ox, oy), Hyp(w - ox, oy), Hyp(ox, h - oy), Hyp(w - ox, h - oy) }.Max() + 30;
        _anim.Animate("clip", radius, 600, CubicBezierEasing.Panel, r => SetPanelClip(ox, oy, r), from: 0,
                      done: () =>
                      {
                          PanelHost.Clip = null; // ombre complète une fois ouvert
                          if (openVersion == _layoutVersion && _state == MenuState.Panel)
                              ApplyWindowRect(ActivePanelWindowRect(_settings.PanelLayout));
                      });
        _anim.Animate("panelop", 1, 240, CubicBezierEasing.Standard, v => PanelHost.Opacity = v);
        RevealSection("secA", Panel.HeaderSection, true, 160);
        RevealSection("secB", Panel.StatsSection, true, 230);
        RevealSection("secC", Panel.BodySection, true, 300);
        RevealSection("secD", Panel.MediaSection, true, 300);
        Activate();
    }

    /// <summary>Bascule Live 60 FPS à chaud entre Card, Side et Overlay (380 ms, CubicBezierEasing.Panel).</summary>
    public void SwitchPanelLayout(PanelLayoutMode target)
    {
        bool changed = _settings.PanelLayout != target;
        _settings.PanelLayout = target;
        if (_settings.EntryMode != OpenEntryMode.Radial)
            _settings.EntryMode = ToEntryMode(target);
        _settings.Save();
        NotifySettingsChanged();

        if (_state != MenuState.Panel || !changed) return;
        MorphPanelToLayout(target);
    }

    private void MorphPanelToLayout(PanelLayoutMode target)
    {
        int morphVersion = ++_layoutVersion;

        // Annule tout clip circulaire résiduel afin d'animer le cadre complet avec son ombre
        _anim.Set("clip", 0, _ => { });
        PanelHost.Clip = null;

        double fromX = Canvas.GetLeft(PanelHost);
        if (double.IsNaN(fromX)) fromX = _panelRect.X;
        double fromY = Canvas.GetTop(PanelHost);
        if (double.IsNaN(fromY)) fromY = _panelRect.Y;
        double fromW = PanelHost.Width > 0 ? PanelHost.Width : _panelRect.Width;
        double fromH = PanelHost.Height > 0 ? PanelHost.Height : _panelRect.Height;

        _panelRect = ComputePanelRect(target);
        var targetWin = ActivePanelWindowRect(target);
        var unionWin = _window.Union(targetWin);
        if (_settings.IdleMode != IdlePresenceMode.Stealth)
            unionWin = unionWin.Union(TriggerIdleRect());

        // Étend ApplyWindowRect une seule fois au début de l'animation pour un morphing GPU 60 FPS sans saccade Win32
        ApplyWindowRect(unionWin);
        Viewport.Background = null;

        bool showScrim = target == PanelLayoutMode.Overlay;
        if (showScrim)
        {
            Scrim.Width = _work.Width;
            Scrim.Height = _work.Height;
            Scrim.IsVisible = true;
            Scrim.IsHitTestVisible = true;
        }
        else
        {
            Scrim.IsHitTestVisible = false;
        }
        _anim.Animate("scrimop", showScrim ? 1 : 0, 380, CubicBezierEasing.Panel, v => Scrim.Opacity = v, from: Scrim.Opacity);

        AnimateTriggerForPanel(open: true, layout: target, durationMs: 380);

        _anim.Animate("px", _panelRect.X, 380, CubicBezierEasing.Panel, v => Canvas.SetLeft(PanelHost, v), from: fromX);
        _anim.Animate("py", _panelRect.Y, 380, CubicBezierEasing.Panel, v => Canvas.SetTop(PanelHost, v), from: fromY);
        _anim.Animate("pw", _panelRect.Width, 380, CubicBezierEasing.Panel, v => PanelHost.Width = PanelCard.Width = v, from: fromW);
        _anim.Animate("ph", _panelRect.Height, 380, CubicBezierEasing.Panel, v => PanelHost.Height = PanelCard.Height = v, from: fromH,
                      done: () => OnLayoutMorphDone(morphVersion));
    }

    private void OnLayoutMorphDone(int version)
    {
        if (version != _layoutVersion || _state != MenuState.Panel) return;
        if (_settings.PanelLayout != PanelLayoutMode.Overlay)
            Scrim.IsVisible = false;
        Viewport.Background = null;
        ApplyWindowRect(ActivePanelWindowRect(_settings.PanelLayout));
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
        _layoutVersion++;
        Panel.SetMenuActive(false);
        PanelHost.IsHitTestVisible = false;
        Scrim.IsHitTestVisible = false;

        if (_settings.IdleMode != IdlePresenceMode.Stealth)
            ApplyWindowRect(_window.Union(TriggerIdleRect()));

        if (Scrim.IsVisible)
            _anim.Animate("scrimop", 0, 300, CubicBezierEasing.Standard, v => Scrim.Opacity = v, from: Scrim.Opacity);

        var c = RevealOrigin(_settings.PanelLayout);
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
        AnimateTriggerForPanel(open: false, layout: _settings.PanelLayout, durationMs: 420);
    }

    // ================= Interactions =================

    public void ToggleFromExternal()
    {
        ToggleMenu();
        if (_state != MenuState.Idle) Activate();
    }

    public void ToggleMenu()
    {
        switch (_state)
        {
            case MenuState.Panel:
                ClosePanel();
                break;
            case MenuState.Radial:
                CloseRadial();
                break;
            default:
                if (_settings.EntryMode == OpenEntryMode.Radial)
                {
                    OpenRadial();
                }
                else
                {
                    var targetLayout = _settings.EntryMode switch
                    {
                        OpenEntryMode.Side => PanelLayoutMode.Side,
                        OpenEntryMode.Overlay => PanelLayoutMode.Overlay,
                        _ => PanelLayoutMode.Card,
                    };
                    if (_settings.PanelLayout != targetLayout)
                    {
                        _settings.PanelLayout = targetLayout;
                        _settings.Save();
                        NotifySettingsChanged();
                    }
                    OpenPanel(Panel.ActiveTab);
                }
                break;
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
        _layoutVersion++;
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
        _anim.Set("scrimop", 0, v => Scrim.Opacity = v);
        _anim.Set("orb", 1, v => OrbScale.ScaleX = OrbScale.ScaleY = v);
        _anim.Set("orbop", 1, v => Orb.Opacity = v);
        _anim.Set("tabhide", 0, v => _edgeTabHide = v);
        _anim.Set("tabhover", 0, v => _edgeTabHover = v);
        PanelHost.IsVisible = false;
        Scrim.IsVisible = false;
        Scrim.IsHitTestVisible = false;
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
        if (e.Key == Key.Escape && _state != MenuState.Idle)
        {
            CloseAll();
            e.Handled = true;
            return;
        }

        if (_state == MenuState.Panel && e.KeyModifiers == KeyModifiers.Control)
        {
            PanelLayoutMode? target = e.Key switch
            {
                Key.D1 or Key.NumPad1 => PanelLayoutMode.Card,
                Key.D2 or Key.NumPad2 => PanelLayoutMode.Side,
                Key.D3 or Key.NumPad3 => PanelLayoutMode.Overlay,
                _ => null,
            };
            if (target is { } layout)
            {
                SwitchPanelLayout(layout);
                e.Handled = true;
            }
        }
    }

    private void OnScrimPressed(object? sender, PointerPressedEventArgs e)
    {
        if (_state == MenuState.Panel && _settings.PanelLayout == PanelLayoutMode.Overlay)
        {
            ClosePanel();
            e.Handled = true;
        }
    }

    private void OnViewportPressed(object? sender, PointerPressedEventArgs e)
    {
        // Clic hors des bulles du menu radial
        if (e.Source == Viewport && _state == MenuState.Radial)
            CloseRadial();
    }

    private PixelPoint ScreenPoint(PointerEventArgs e) => this.PointToScreen(e.GetPosition(this));

    // --- Interactions Orbe (84 px / Mini-orbe 48 px) ---

    private void OnOrbPressed(object? sender, PointerPressedEventArgs e)
    {
        if (!e.GetCurrentPoint(Orb).Properties.IsLeftButtonPressed) return;
        _pressScreen = ScreenPoint(e);
        _pressOrb = _orb;
        _dragging = false;
        _draggingTab = false;
        e.Pointer.Capture(Orb);
        e.Handled = true;
    }

    private void OnOrbMoved(object? sender, PointerEventArgs e)
    {
        if (_pressScreen is not { } start || _draggingTab) return;
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
        LayoutTrigger();
        ApplyWindowRect(IdleRect());
    }

    private void OnOrbReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (_pressScreen == null || _draggingTab) return;
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

    // --- Interactions Languette de bord (EdgeTab) ---

    private void OnEdgeTabEntered(object? sender, PointerEventArgs e)
    {
        if (_edgeTabHide > 0.5) return;
        _anim.Animate("tabhover", 1, 180, CubicBezierEasing.Standard, v => { _edgeTabHover = v; LayoutTrigger(); }, from: _edgeTabHover);
    }

    private void OnEdgeTabExited(object? sender, PointerEventArgs e)
    {
        if (_dragging && _draggingTab) return;
        _anim.Animate("tabhover", 0, 180, CubicBezierEasing.Standard, v => { _edgeTabHover = v; LayoutTrigger(); }, from: _edgeTabHover);
    }

    private void OnEdgeTabPressed(object? sender, PointerPressedEventArgs e)
    {
        if (!e.GetCurrentPoint(EdgeTab).Properties.IsLeftButtonPressed) return;
        _pressScreen = ScreenPoint(e);
        _pressTabY = _edgeTabY;
        _dragging = false;
        _draggingTab = true;
        e.Pointer.Capture(EdgeTab);
        e.Handled = true;
    }

    private void OnEdgeTabMoved(object? sender, PointerEventArgs e)
    {
        if (_pressScreen is not { } start || !_draggingTab) return;
        var now = ScreenPoint(e);
        var delta = new Vector((now.X - start.X) / _scaling, (now.Y - start.Y) / _scaling);
        if (!_dragging && delta.Length > 5)
        {
            _dragging = true;
            EdgeTab.Cursor = new Cursor(StandardCursorType.SizeAll);
            if (_state != MenuState.Idle) CloseAllImmediately();
        }
        if (!_dragging) return;

        _edgeTabY = ClampEdgeTabY(_pressTabY + delta.Y);
        if (Math.Abs(delta.X) > 48)
        {
            double cursorWorkX = (now.X - _workAreaPx.X) / _scaling;
            var newSide = cursorWorkX < _work.Width / 2 ? EdgeDockSide.Left : EdgeDockSide.Right;
            if (newSide != _settings.DockSide)
            {
                _settings.DockSide = newSide;
                UpdateEdgeTabCornerRadius();
            }
        }
        LayoutTrigger();
        ApplyWindowRect(IdleRect());
    }

    private void OnStyleSettingsChanged(WidgetSettings s)
    {
        PanelCard.Opacity = Math.Clamp(s.WidgetOpacityPercent / 100.0, 0.82, 1.0);
        SettingsChanged?.Invoke();
    }

    public void SetDockSide(EdgeDockSide side)
    {
        if (_settings.DockSide == side) return;
        _settings.DockSide = side;
        _settings.Save();
        UpdateEdgeTabCornerRadius();
        ApplyIdleWindowState();
        SettingsChanged?.Invoke();
    }

    private void UpdateEdgeTabCornerRadius()
    {
        if (_settings.DockSide == EdgeDockSide.Left)
        {
            EdgeTab.CornerRadius = new CornerRadius(0, 16, 16, 0);
            EdgeTab.BorderThickness = new Thickness(0, 1, 1, 1);
        }
        else
        {
            EdgeTab.CornerRadius = new CornerRadius(16, 0, 0, 16);
            EdgeTab.BorderThickness = new Thickness(1, 1, 0, 1);
        }
    }

    private void OnEdgeTabReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (_pressScreen == null || !_draggingTab) return;
        _pressScreen = null;
        _draggingTab = false;
        e.Pointer.Capture(null);
        EdgeTab.Cursor = new Cursor(StandardCursorType.Hand);
        if (_dragging)
        {
            _dragging = false;
            _settings.EdgeTabY = _edgeTabY;
            _settings.Save();
            if (!EdgeTab.IsPointerOver)
                _anim.Animate("tabhover", 0, 180, CubicBezierEasing.Standard, v => { _edgeTabHover = v; LayoutTrigger(); }, from: _edgeTabHover);
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
