using AlyxDesktop.Platform;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.Diagnostics;

namespace AlyxDesktop.Controls;

public enum EyeMode { Idle, Thinking, Listening }

/// <summary>
/// Logo animé d'Alyx : loupe contenant un œil en amande (viewBox 100×100 du design).
/// Clignement aléatoire, iris qui suit le curseur, mode réflexion (iris en orbite + arc doré)
/// et mode écoute (pupille dilatée).
/// </summary>
public sealed class AlyxEye : Control
{
    public static readonly StyledProperty<EyeMode> ModeProperty =
        AvaloniaProperty.Register<AlyxEye, EyeMode>(nameof(Mode));

    public static readonly StyledProperty<bool> FollowCursorProperty =
        AvaloniaProperty.Register<AlyxEye, bool>(nameof(FollowCursor), true);

    public EyeMode Mode { get => GetValue(ModeProperty); set => SetValue(ModeProperty, value); }
    public bool FollowCursor { get => GetValue(FollowCursorProperty); set => SetValue(FollowCursorProperty, value); }

    private static readonly IBrush Ink = new SolidColorBrush(Color.Parse("#14151A"));
    private static readonly IBrush PureWhite = Brushes.White;
    private static readonly IPen HandlePen = new Pen(Ink, 7, lineCap: PenLineCap.Round);
    private static readonly IPen LensPen = new Pen(Ink, 3.2);
    private static readonly IPen AlmondPen = new Pen(Ink, 2.4, lineJoin: PenLineJoin.Round);
    private static readonly Geometry Almond = Geometry.Parse("M17 42 Q42 21 67 42 Q42 63 17 42Z");
    private static readonly Geometry LensCircle = new EllipseGeometry(new Rect(9, 9, 66, 66));

    // Lavis d'aquarelle Bleu Céleste et Rose Pétale
    private static readonly IBrush WcBlueWash = new RadialGradientBrush
    {
        Center = new RelativePoint(0.35, 0.35, RelativeUnit.Relative),
        GradientOrigin = new RelativePoint(0.35, 0.35, RelativeUnit.Relative),
        Radius = 0.6,
        GradientStops = new GradientStops
        {
            new GradientStop(Color.FromArgb(160, 125, 211, 252), 0.0), // #7dd3fc
            new GradientStop(Color.FromArgb(56, 2, 132, 199), 0.6),    // #0284c7
            new GradientStop(Color.FromArgb(0, 2, 132, 199), 1.0)
        }
    };

    private static readonly IBrush WcRoseWash = new RadialGradientBrush
    {
        Center = new RelativePoint(0.68, 0.65, RelativeUnit.Relative),
        GradientOrigin = new RelativePoint(0.68, 0.65, RelativeUnit.Relative),
        Radius = 0.58,
        GradientStops = new GradientStops
        {
            new GradientStop(Color.FromArgb(178, 249, 168, 212), 0.0), // #f9a8d4
            new GradientStop(Color.FromArgb(64, 236, 72, 153), 0.6),    // #ec4899
            new GradientStop(Color.FromArgb(0, 236, 72, 153), 1.0)
        }
    };

    // Iris bicolore aquarelle (Bleu -> Rose)
    private static readonly IBrush IrisGradient = new LinearGradientBrush
    {
        StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
        EndPoint = new RelativePoint(1, 1, RelativeUnit.Relative),
        GradientStops = new GradientStops
        {
            new GradientStop(Color.Parse("#38BDF8"), 0.0),
            new GradientStop(Color.Parse("#0284C7"), 0.52),
            new GradientStop(Color.Parse("#EC4899"), 1.0)
        }
    };

    private static readonly IBrush LensBacking = new SolidColorBrush(Color.FromArgb(220, 255, 255, 255));
    private static readonly IBrush PupilBrush = new SolidColorBrush(Color.Parse("#111318"));
    private static readonly IPen SpinPen = new Pen(new SolidColorBrush(Color.Parse("#0284C7")), 2.4, lineCap: PenLineCap.Round);

    private readonly DispatcherTimer _frame;
    private readonly DispatcherTimer _blink;
    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private readonly Random _random = new();
    private double _cx, _cy, _rx = 1.8, _lid = 1, _spinOpacity;
    private double _lidTarget = 1;
    private Point? _localPointer;

    public AlyxEye()
    {
        _frame = new DispatcherTimer(TimeSpan.FromMilliseconds(16), DispatcherPriority.Render, (_, _) => Tick());
        _blink = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1400 + _random.NextDouble() * 2000) };
        _blink.Tick += (_, _) => Blink();
    }

    protected override void OnAttachedToVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnAttachedToVisualTree(e);
        _frame.Start();
        _blink.Start();
        if (TopLevel.GetTopLevel(this) is { } top)
            top.PointerMoved += OnTopPointerMoved;
    }

    protected override void OnDetachedFromVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnDetachedFromVisualTree(e);
        _frame.Stop();
        _blink.Stop();
        if (TopLevel.GetTopLevel(this) is { } top)
            top.PointerMoved -= OnTopPointerMoved;
    }

    // Repli hors Windows : suivi du pointeur uniquement au-dessus de la fenêtre du widget
    private void OnTopPointerMoved(object? sender, PointerEventArgs e) => _localPointer = e.GetPosition(this);

    private void Blink()
    {
        Shut(110);
        if (_random.NextDouble() < .2)
            DispatcherTimer.RunOnce(() => Shut(100), TimeSpan.FromMilliseconds(240));
        _blink.Interval = TimeSpan.FromMilliseconds(2600 + _random.NextDouble() * 4200);
    }

    private void Shut(int ms)
    {
        _lidTarget = 0.06;
        DispatcherTimer.RunOnce(() => _lidTarget = 1, TimeSpan.FromMilliseconds(ms));
    }

    private void Tick()
    {
        if (!IsEffectivelyVisible || Bounds.Width <= 0) return;
        double now = _clock.Elapsed.TotalMilliseconds;
        double tx = 0, ty = 0;
        var mode = Mode;

        if (mode == EyeMode.Thinking)
        {
            tx = Math.Cos(now / 380) * 5;
            ty = Math.Sin(now / 380) * 2;
        }
        else if (FollowCursor && PointerOffset() is { } d)
        {
            double dist = Math.Max(1, Math.Sqrt(d.X * d.X + d.Y * d.Y));
            double k = Math.Min(1, dist / 260);
            tx = d.X / dist * 6 * k;
            ty = d.Y / dist * 2.6 * k;
        }

        double cx = _cx + (tx - _cx) * .12;
        double cy = _cy + (ty - _cy) * .12;
        double targetRx = mode == EyeMode.Thinking ? 1 : mode == EyeMode.Listening ? 3.2 : 1.8;
        double rx = _rx + (targetRx - _rx) * .1;
        // Paupière : transition de ~90 ms
        double lid = _lid + (_lidTarget - _lid) * .45;
        double spin = _spinOpacity + ((mode == EyeMode.Thinking ? 1 : 0) - _spinOpacity) * .1;

        bool changed = Math.Abs(cx - _cx) > .01 || Math.Abs(cy - _cy) > .01 || Math.Abs(rx - _rx) > .005
                       || Math.Abs(lid - _lid) > .002 || Math.Abs(spin - _spinOpacity) > .002 || mode == EyeMode.Thinking;
        _cx = cx; _cy = cy; _rx = rx; _lid = lid; _spinOpacity = spin;
        if (changed) InvalidateVisual();
    }

    /// <summary>Vecteur centre de l'œil → curseur, en DIP.</summary>
    private Vector? PointerOffset()
    {
        if (TopLevel.GetTopLevel(this) is not { } top) return null;
        var center = new Point(Bounds.Width / 2, Bounds.Height / 2);
        if (Shell.CursorPosition() is { } cursor)
        {
            var screenCenter = this.PointToScreen(center);
            double scaling = top.RenderScaling;
            return new Vector((cursor.X - screenCenter.X) / scaling, (cursor.Y - screenCenter.Y) / scaling);
        }
        return _localPointer is { } p ? p - center : null;
    }

    public override void Render(DrawingContext context)
    {
        double s = Math.Min(Bounds.Width, Bounds.Height) / 100.0;
        if (s <= 0) return;
        using var scale = context.PushTransform(Matrix.CreateScale(s, s));

        // 1. Taches d'aquarelle douces débordant légèrement de la lentille
        context.DrawEllipse(WcBlueWash, null, new Point(35, 34), 33, 33);
        context.DrawEllipse(WcRoseWash, null, new Point(49, 47), 31, 31);

        // 2. Manche de la loupe (trait d'encre arrondi)
        context.DrawLine(HandlePen, new Point(66, 66), new Point(88, 88));

        // 3. Fond et cercle principal de la lentille
        context.DrawEllipse(LensBacking, LensPen, new Point(42, 42), 33, 33);

        // Lavis d'aquarelle interne découpé dans la lentille
        using (context.PushGeometryClip(LensCircle))
        {
            context.DrawEllipse(WcBlueWash, null, new Point(38, 37), 26, 26);
            context.DrawEllipse(WcRoseWash, null, new Point(47, 45), 24, 24);
        }

        // 4. Arc céleste qui tourne dans la loupe pendant la réflexion (1,2 s/tour)
        if (_spinOpacity > .01)
        {
            double angle = _clock.Elapsed.TotalMilliseconds / 1200.0 * 360;
            using var rot = context.PushTransform(Matrix.CreateTranslation(-42, -42) * Matrix.CreateRotation(angle * Math.PI / 180) * Matrix.CreateTranslation(42, 42));
            using var op = context.PushOpacity(_spinOpacity);
            context.DrawGeometry(null, SpinPen, Arc(42, 42, 27.5, 0, 62.5));
        }

        // 5. Paupière et œil en amande
        using var lid = context.PushTransform(Matrix.CreateTranslation(-42, -42) * Matrix.CreateScale(1, _lid) * Matrix.CreateTranslation(42, 42));
        context.DrawGeometry(Brushes.White, AlmondPen, Almond);

        // 6. Iris aquarelle bicolore, pupille encre et éclat de lumière
        using (context.PushGeometryClip(Almond))
        using (context.PushTransform(Matrix.CreateTranslation(_cx, _cy)))
        {
            context.DrawEllipse(IrisGradient, null, new Point(42, 42), 9.5, 9.5);
            context.DrawEllipse(PupilBrush, null, new Point(42, 42), _rx, 7.8);
            context.DrawEllipse(PureWhite, null, new Point(45.5, 38.5), 1.6, 1.6);
        }
    }

    private static Geometry Arc(double cx, double cy, double r, double startDeg, double sweepDeg)
    {
        double a0 = startDeg * Math.PI / 180, a1 = (startDeg + sweepDeg) * Math.PI / 180;
        var g = new StreamGeometry();
        using var ctx = g.Open();
        ctx.BeginFigure(new Point(cx + r * Math.Cos(a0), cy + r * Math.Sin(a0)), false);
        ctx.ArcTo(new Point(cx + r * Math.Cos(a1), cy + r * Math.Sin(a1)), new Size(r, r), 0, sweepDeg > 180, SweepDirection.Clockwise);
        ctx.EndFigure(false);
        return g;
    }
}
