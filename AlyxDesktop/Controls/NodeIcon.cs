using AlyxDesktop.Services;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using System;
using System.Diagnostics;

namespace AlyxDesktop.Controls;

/// <summary>
/// Icône animée affichée au survol d'une bulle du menu radial (viewBox 40×40).
/// Elle apparaît avec un effet ressort, puis joue une animation continue tant que le pointeur reste dessus :
/// engrenage qui monte et tourne, top model qui prend la pose, signe pause de télécommande,
/// liste qui se coche, signal sur un écran, bulle de chat qui « écrit ».
/// </summary>
public sealed class NodeIcon : Control
{
    public static readonly StyledProperty<string> KindProperty =
        AvaloniaProperty.Register<NodeIcon, string>(nameof(Kind), "");

    /// <summary>Lecture : vrai si un média joue (signe pause), faux sinon (signe lecture/pause).</summary>
    public static readonly StyledProperty<bool> AlternateProperty =
        AvaloniaProperty.Register<NodeIcon, bool>(nameof(Alternate));

    public string Kind { get => GetValue(KindProperty); set => SetValue(KindProperty, value); }
    public bool Alternate { get => GetValue(AlternateProperty); set => SetValue(AlternateProperty, value); }

    /// <summary>Progression d'apparition (0 = caché, 1 = visible, dépasse 1 pendant le rebond).</summary>
    public event Action<double>? RevealChanged;

    private const double InMs = 460, OutMs = 200;

    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private bool _hovered, _frameRequested;
    private double _reveal, _from, _changedAt, _hoverStart;

    static NodeIcon()
    {
        AffectsRender<NodeIcon>(KindProperty, AlternateProperty);
        IsHitTestVisibleProperty.OverrideDefaultValue<NodeIcon>(false);
    }

    public bool Hovered
    {
        get => _hovered;
        set
        {
            if (_hovered == value) return;
            _hovered = value;
            _from = _reveal;
            _changedAt = Now;
            if (value) _hoverStart = Now;
            RequestFrame();
        }
    }

    /// <summary>Remet l'icône à l'état caché sans animation (menu refermé).</summary>
    public void Reset()
    {
        _hovered = false;
        _reveal = _from = 0;
        RevealChanged?.Invoke(0);
        InvalidateVisual();
    }

    private double Now => _clock.Elapsed.TotalMilliseconds;

    private void RequestFrame()
    {
        if (_frameRequested || TopLevel.GetTopLevel(this) is not { } top) return;
        _frameRequested = true;
        top.RequestAnimationFrame(_ => Frame());
    }

    private void Frame()
    {
        _frameRequested = false;
        double p = Math.Min(1, (Now - _changedAt) / (_hovered ? InMs : OutMs));
        double target = _hovered ? 1 : 0;
        var easing = _hovered ? CubicBezierEasing.Spring : CubicBezierEasing.Standard;
        _reveal = _from + (target - _from) * easing.Ease(p);
        RevealChanged?.Invoke(_reveal);
        InvalidateVisual();
        // Tant que l'icône est visible, l'animation continue tourne
        if (_hovered || p < 1) RequestFrame();
    }

    // ================= Dessin =================

    private static IBrush Ink => App.Res<IBrush>("Ink");
    private static IBrush Gold => App.Res<IBrush>("Accent");

    private static Pen Stroke(IBrush brush, double width = 2.2) =>
        new(brush, width, lineCap: PenLineCap.Round, lineJoin: PenLineJoin.Round);

    public override void Render(DrawingContext context)
    {
        if (_reveal <= 0.001) return;
        double s = Math.Min(Bounds.Width, Bounds.Height) / 40.0;
        if (s <= 0) return;
        double r = _reveal;
        double t = (Now - _hoverStart) / 1000.0; // secondes depuis le début du survol

        using var scale = context.PushTransform(Matrix.CreateScale(s, s)
            * Matrix.CreateTranslation((Bounds.Width - 40 * s) / 2, (Bounds.Height - 40 * s) / 2));
        using var fade = context.PushOpacity(Math.Clamp(r, 0, 1));

        switch (Kind)
        {
            case "settings": DrawGear(context, r, t); break;
            case "models": DrawTopModel(context, r, t); break;
            case "media": DrawPause(context, r, Alternate); break;
            case "tasks": DrawList(context, r, t); break;
            case "system": DrawMonitor(context, r, t); break;
            case "chat": DrawBubble(context, r, t); break;
        }
    }

    /// <summary>Transformation « pop » autour d'un point : échelle 0,6 → 1 (avec rebond).</summary>
    private static Matrix Pop(double r, double cx, double cy)
    {
        double k = .6 + .4 * r;
        return Matrix.CreateTranslation(-cx, -cy) * Matrix.CreateScale(k, k) * Matrix.CreateTranslation(cx, cy);
    }

    // Réglages : l'engrenage monte depuis le bas puis tourne en continu
    private static void DrawGear(DrawingContext dc, double r, double t)
    {
        double rise = (1 - r) * 14;
        double angle = t * 140 * Math.PI / 180;
        using var _ = dc.PushTransform(Matrix.CreateTranslation(-20, -20) * Matrix.CreateRotation(angle)
                                       * Matrix.CreateTranslation(20, 20 + rise));
        dc.DrawGeometry(Brushes.White, Stroke(Ink), Gear(20, 20, 8, 15.5, 11.8));
        dc.DrawEllipse(Gold, Stroke(Ink, 2), new Point(20, 20), 4.6, 4.6);
    }

    private static Geometry Gear(double cx, double cy, int teeth, double outer, double root)
    {
        var g = new StreamGeometry();
        using var ctx = g.Open();
        double step = 2 * Math.PI / teeth, baseHalf = step * .31, tipHalf = step * .17;
        Point P(double rad, double a) => new(cx + rad * Math.Cos(a), cy + rad * Math.Sin(a));
        for (int k = 0; k < teeth; k++)
        {
            double a = k * step - Math.PI / 2;
            if (k == 0) ctx.BeginFigure(P(root, a - baseHalf), true);
            ctx.LineTo(P(outer, a - tipHalf));
            ctx.LineTo(P(outer, a + tipHalf));
            ctx.LineTo(P(root, a + baseHalf));
            ctx.ArcTo(P(root, a + step - baseHalf), new Size(root, root), 0, false, SweepDirection.Clockwise);
        }
        ctx.EndFigure(true);
        return g;
    }

    // Modèles : silhouette de top model, main sur la hanche, qui balance sa pose ; une étincelle scintille
    private static readonly Geometry Dress = Geometry.Parse("M16.2 13.6 L23.8 13.6 L21.6 21 L26.6 33 L13.4 33 L18.4 21 Z");
    private static readonly Geometry Hair = Geometry.Parse("M16.3 8.6 C16.3 4.2 23.7 4.2 23.7 8.6 C23.9 11 25 12.4 25.6 13.4 C23.2 13.6 21.6 12.2 20 10 C18.4 12.2 16.8 13.6 14.4 13.4 C15 12.4 16.1 11 16.3 8.6 Z");

    private static readonly Geometry Sparkle = Geometry.Parse("M31 3.5 L32.1 6.9 L35.5 8 L32.1 9.1 L31 12.5 L29.9 9.1 L26.5 8 L29.9 6.9 Z");
    private static readonly Geometry PlayTriangle = Geometry.Parse("M8.6 12.4 L19.4 20 L8.6 27.6 Z");

    private static void DrawTopModel(DrawingContext dc, double r, double t)
    {
        double sway = Math.Sin(t * 2.6) * 3.5 * Math.PI / 180;
        using var pop = dc.PushTransform(Pop(r, 20, 38));
        using (dc.PushTransform(Matrix.CreateTranslation(-20, -38) * Matrix.CreateRotation(sway) * Matrix.CreateTranslation(20, 38)))
        {
            var ink = Stroke(Ink, 2);
            dc.DrawLine(ink, new Point(18.6, 33), new Point(17.6, 38));     // jambes
            dc.DrawLine(ink, new Point(21.4, 33), new Point(23.4, 37.6));
            dc.DrawLine(ink, new Point(16.4, 14.2), new Point(14.6, 22.4)); // bras le long du corps
            var arm = new StreamGeometry();                                  // main sur la hanche
            using (var c = arm.Open())
            {
                c.BeginFigure(new Point(23.6, 14.2), false);
                c.LineTo(new Point(27.6, 18.4));
                c.LineTo(new Point(22, 21.2));
                c.EndFigure(false);
            }
            dc.DrawGeometry(null, ink, arm);
            dc.DrawGeometry(Gold, Stroke(Ink, 1.8), Dress);
            dc.DrawGeometry(Ink, null, Hair);
            dc.DrawEllipse(Brushes.White, Stroke(Ink, 1.6), new Point(20, 8.4), 3.1, 3.4);
        }
        // Étincelle : apparaît et disparaît en tournant
        double tw = Math.Max(0, Math.Sin(t * 3.4));
        if (tw > .02)
        {
            using var sp = dc.PushTransform(Matrix.CreateTranslation(-31, -8) * Matrix.CreateScale(tw, tw)
                                            * Matrix.CreateRotation(t * 1.5) * Matrix.CreateTranslation(31, 8));
            dc.DrawGeometry(Gold, Stroke(Ink, 1), Sparkle);
        }
    }

    // Lecture : signe pause de télécommande (deux barres) ; ▶‖ quand rien ne joue
    private static void DrawPause(DrawingContext dc, double r, bool playing)
    {
        double Bar(double delay) => Math.Clamp((r - delay) / (1 - delay), 0, 1.15);
        void DrawBar(double x, double w, double grow)
        {
            double h = 18 * grow;
            dc.DrawRectangle(Ink, null, new Rect(x, 20 - h / 2, w, h), 1.6, 1.6);
        }
        if (playing)
        {
            DrawBar(13.5, 4.6, Bar(0));
            DrawBar(21.9, 4.6, Bar(.18));
        }
        else
        {
            using (dc.PushTransform(Pop(Bar(0), 13, 20)))
                dc.DrawGeometry(Ink, Stroke(Ink, 1.4), PlayTriangle);
            DrawBar(22.6, 3.6, Bar(.15));
            DrawBar(28.4, 3.6, Bar(.3));
        }
    }

    // Tâches : trois lignes qui arrivent l'une après l'autre, les cases se cochent en boucle
    private static void DrawList(DrawingContext dc, double r, double t)
    {
        var ink = Stroke(Ink, 2);
        int ticked = (int)(t / .5) % 5; // 0..3 cases cochées, puis une pause
        for (int i = 0; i < 3; i++)
        {
            double row = Math.Clamp((r - i * .14) / (1 - .28), 0, 1.1);
            if (row <= 0) continue;
            double y = 11.5 + i * 8.5, dx = (1 - Math.Min(row, 1)) * -8;
            using var o = dc.PushOpacity(Math.Min(row, 1));
            using var m = dc.PushTransform(Matrix.CreateTranslation(dx, 0));
            bool done = i < ticked;
            dc.DrawRectangle(done ? Gold : Brushes.White, Stroke(Ink, 1.8), new Rect(7.5, y - 3, 6, 6), 1.6, 1.6);
            if (done)
            {
                var check = new StreamGeometry();
                using (var c = check.Open())
                {
                    c.BeginFigure(new Point(9, y), false);
                    c.LineTo(new Point(10.4, y + 1.4));
                    c.LineTo(new Point(12.4, y - 1.4));
                    c.EndFigure(false);
                }
                dc.DrawGeometry(null, Stroke(Ink, 1.5), check);
            }
            double len = (i == 1 ? 12 : 16) * Math.Min(row, 1);
            dc.DrawLine(ink, new Point(17.5, y), new Point(17.5 + len, y));
        }
    }

    // Système : un signal (pouls) qui défile sur un écran
    private static readonly Point[] Pulse =
    {
        new(9.5, 18.5), new(14, 18.5), new(15.6, 15.5), new(17.6, 22.5), new(20.2, 11.5),
        new(22.6, 21), new(24.2, 18.5), new(30.5, 18.5),
    };

    private static void DrawMonitor(DrawingContext dc, double r, double t)
    {
        using var pop = dc.PushTransform(Pop(r, 20, 20));
        var ink = Stroke(Ink, 2.2);
        dc.DrawRectangle(Brushes.White, ink, new Rect(5.5, 8, 29, 21), 3.2, 3.2);
        dc.DrawLine(ink, new Point(20, 29), new Point(20, 32.5));
        dc.DrawLine(ink, new Point(14, 33), new Point(26, 33));

        var line = new StreamGeometry();
        using (var c = line.Open())
        {
            c.BeginFigure(Pulse[0], false);
            for (int i = 1; i < Pulse.Length; i++) c.LineTo(Pulse[i]);
            c.EndFigure(false);
        }
        // Trace complète discrète + segment lumineux qui balaie l'écran
        using (dc.PushOpacity(.22)) dc.DrawGeometry(null, Stroke(Ink, 1.8), line);
        double head = 9.5 + ((t * 18) % 32);
        using (dc.PushClip(new Rect(Math.Max(7.5, head - 12), 9.5, Math.Max(0, Math.Min(head, 32.5) - Math.Max(7.5, head - 12)), 18)))
            dc.DrawGeometry(null, Stroke(Gold, 2.4), line);
        using (dc.PushClip(new Rect(Math.Max(7.5, head - 5), 9.5, Math.Max(0, Math.Min(head, 32.5) - Math.Max(7.5, head - 5)), 18)))
            dc.DrawGeometry(null, Stroke(Ink, 1.8), line);
    }

    // Chat : la bulle surgit depuis sa pointe, trois points « en train d'écrire »
    private static readonly Geometry Bubble = Geometry.Parse(
        "M13 8.5 L27 8.5 C30.6 8.5 33.5 11.4 33.5 15 L33.5 20.5 C33.5 24.1 30.6 27 27 27 L18.5 27 L11.5 32.5 L12.6 27 C9.2 26.6 6.5 23.8 6.5 20.5 L6.5 15 C6.5 11.4 9.4 8.5 13 8.5 Z");

    private static void DrawBubble(DrawingContext dc, double r, double t)
    {
        using var pop = dc.PushTransform(Pop(r, 12, 32));
        dc.DrawGeometry(Brushes.White, Stroke(Ink, 2.2), Bubble);
        for (int i = 0; i < 3; i++)
        {
            double phase = t * 2 * Math.PI / .9 - i * .7;
            double dy = -2.6 * Math.Max(0, Math.Sin(phase));
            dc.DrawEllipse(i == 1 ? Gold : Ink, i == 1 ? Stroke(Ink, 1) : null, new Point(14 + i * 6, 17.8 + dy), 1.9, 1.9);
        }
    }
}
