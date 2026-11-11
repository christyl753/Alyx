using AlyxDesktop.Platform;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
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

    private static readonly IBrush CanopySageWash = Radial("#7DAE9B", 118);
    private static readonly IBrush CanopySunWash = Radial("#FFE866", 130);
    private static readonly IBrush CanopyLensBacking = new SolidColorBrush(Color.Parse("#FBF6EA"));
    private static readonly IBrush AeroLensBacking = new SolidColorBrush(Color.FromArgb(105, 186, 230, 253));
    private static readonly IPen SchoolHighlightPen = new Pen(new SolidColorBrush(Color.FromArgb(145, 254, 240, 138)), 8, lineCap: PenLineCap.Round);
    private static readonly IBrush AeroGloss = new LinearGradientBrush
    {
        StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
        EndPoint = new RelativePoint(1, 1, RelativeUnit.Relative),
        GradientStops = new GradientStops
        {
            new GradientStop(Color.FromArgb(210, 255, 255, 255), 0),
            new GradientStop(Color.FromArgb(22, 255, 255, 255), 1)
        }
    };
    private static readonly Dictionary<string, IBrush> StyleIrises = new()
    {
        ["canopee-ambre"] = Gradient("#384C48", "#7DAE9B", "#FBA620"),
        ["watercolor"] = Gradient("#38BDF8", "#0284C7", "#EC4899"),
        ["kde"] = Gradient("#1D99F3", "#3DAEE9", "#7DD3FC"),
        ["gnome"] = Gradient("#3584E4", "#4C9AE8", "#7AB7F5"),
        ["sketch"] = Gradient("#0284C7", "#38BDF8", "#EC4899"),
        ["sticker"] = Gradient("#EC4899", "#F472B6", "#38BDF8"),
        ["win7"] = Gradient("#0369A1", "#0284C7", "#7DD3FC"),
        ["school"] = Gradient("#3730A3", "#4338CA", "#F43F5E"),
        ["office"] = Gradient("#78350F", "#B45309", "#D6CFC2"),
        ["bento-pearl"] = Gradient("#38BDF8", "#6366F1", "#EC4899"),
        ["bauhaus"] = Gradient("#1D3557", "#36577A", "#E07A5F"),
        ["eink"] = Gradient("#1C1C1C", "#3F3F46", "#71717A"),
        ["tactile"] = Gradient("#0284C7", "#38BDF8", "#CBD5E1"),
        ["alyx-prism"] = Gradient("#0284C7", "#6366F1", "#EC4899")
    };
    private static readonly Dictionary<string, IPen> StyleLensPens = new()
    {
        ["canopee-ambre"] = new Pen(new SolidColorBrush(Color.Parse("#384C48")), 3.2),
        ["watercolor"] = new Pen(new SolidColorBrush(Color.Parse("#14151A")), 3.2),
        ["kde"] = new Pen(new SolidColorBrush(Color.Parse("#3DAEE9")), 2.4),
        ["gnome"] = new Pen(new SolidColorBrush(Color.Parse("#3584E4")), 2.5),
        ["sketch"] = new Pen(new SolidColorBrush(Color.Parse("#283548")), 2.2),
        ["sticker"] = new Pen(new SolidColorBrush(Color.Parse("#EC4899")), 3.2),
        ["win7"] = new Pen(new SolidColorBrush(Color.Parse("#0284C7")), 3),
        ["school"] = new Pen(new SolidColorBrush(Color.Parse("#3730A3")), 2.8),
        ["office"] = new Pen(new SolidColorBrush(Color.Parse("#92400E")), 3),
        ["bento-pearl"] = new Pen(new SolidColorBrush(Color.Parse("#CBD5E1")), 2.6),
        ["bauhaus"] = new Pen(new SolidColorBrush(Color.Parse("#1D3557")), 2.4),
        ["eink"] = new Pen(new SolidColorBrush(Color.Parse("#1C1C1C")), 3),
        ["tactile"] = new Pen(new SolidColorBrush(Color.Parse("#9CA3AF")), 3),
        ["alyx-prism"] = new Pen(new SolidColorBrush(Color.Parse("#7DD3FC")), 3)
    };
    private static readonly Dictionary<string, IPen> StyleHandlePens = new()
    {
        ["canopee-ambre"] = new Pen(new SolidColorBrush(Color.Parse("#384C48")), 7, lineCap: PenLineCap.Round),
        ["watercolor"] = new Pen(new SolidColorBrush(Color.Parse("#14151A")), 7, lineCap: PenLineCap.Round),
        ["kde"] = new Pen(new SolidColorBrush(Color.Parse("#3DAEE9")), 6, lineCap: PenLineCap.Round),
        ["gnome"] = new Pen(new SolidColorBrush(Color.Parse("#3584E4")), 6, lineCap: PenLineCap.Round),
        ["sketch"] = new Pen(new SolidColorBrush(Color.Parse("#283548")), 5, lineCap: PenLineCap.Round),
        ["sticker"] = new Pen(new SolidColorBrush(Color.Parse("#EC4899")), 6, lineCap: PenLineCap.Round),
        ["win7"] = new Pen(new SolidColorBrush(Color.Parse("#0284C7")), 6, lineCap: PenLineCap.Round),
        ["school"] = new Pen(new SolidColorBrush(Color.Parse("#3730A3")), 6, lineCap: PenLineCap.Round),
        ["office"] = new Pen(new SolidColorBrush(Color.Parse("#92400E")), 7, lineCap: PenLineCap.Round),
        ["bento-pearl"] = new Pen(new SolidColorBrush(Color.Parse("#6366F1")), 6, lineCap: PenLineCap.Round),
        ["bauhaus"] = new Pen(new SolidColorBrush(Color.Parse("#1D3557")), 6, lineCap: PenLineCap.Round),
        ["eink"] = new Pen(new SolidColorBrush(Color.Parse("#1C1C1C")), 7, lineCap: PenLineCap.Round),
        ["tactile"] = new Pen(new SolidColorBrush(Color.Parse("#0284C7")), 6, lineCap: PenLineCap.Round),
        ["alyx-prism"] = new Pen(new SolidColorBrush(Color.Parse("#6366F1")), 6, lineCap: PenLineCap.Round)
    };
    private static readonly IPen StickerCutPen = new Pen(Brushes.White, 12, lineCap: PenLineCap.Round);
    private static readonly IPen KdeReticlePen = new Pen(new SolidColorBrush(Color.Parse("#3DAEE9")), 1, dashStyle: DashStyle.Dash);
    private static readonly IPen SchoolLinePen = new Pen(new SolidColorBrush(Color.FromArgb(36, 99, 102, 241)), 0.7);
    private static readonly IPen SketchHatchPen = new Pen(new SolidColorBrush(Color.FromArgb(95, 40, 53, 72)), 0.9);
    private static readonly IPen OfficeStampPen = new Pen(new SolidColorBrush(Color.FromArgb(125, 146, 64, 14)), 1.3);
    private static readonly Dictionary<(Color Primary, Color Secondary, bool Prism), IBrush> PaletteIrisCache = new();
    private static readonly Dictionary<(Color Color, double Width), IPen> PalettePenCache = new();

    private static IBrush PaletteIris(Color primary, Color secondary, bool prism)
    {
        var key = (primary, secondary, prism);
        if (!PaletteIrisCache.TryGetValue(key, out var brush))
            PaletteIrisCache[key] = brush = Gradient(primary.ToString(), (prism ? Color.Parse("#6366F1") : primary).ToString(), secondary.ToString());
        return brush;
    }

    private static IPen PalettePen(Color color, double width)
    {
        var key = (color, width);
        if (!PalettePenCache.TryGetValue(key, out var pen))
            PalettePenCache[key] = pen = new Pen(new SolidColorBrush(color), width, lineCap: PenLineCap.Round);
        return pen;
    }

    private static IBrush Gradient(string start, string middle, string end) => new LinearGradientBrush
    {
        StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
        EndPoint = new RelativePoint(1, 1, RelativeUnit.Relative),
        GradientStops = new GradientStops
        {
            new GradientStop(Color.Parse(start), 0),
            new GradientStop(Color.Parse(middle), 0.52),
            new GradientStop(Color.Parse(end), 1)
        }
    };

    private static IBrush Radial(string color, byte alpha) => new RadialGradientBrush
    {
        Center = new RelativePoint(0.5, 0.5, RelativeUnit.Relative),
        GradientOrigin = new RelativePoint(0.5, 0.5, RelativeUnit.Relative),
        Radius = 0.6,
        GradientStops = new GradientStops
        {
            new GradientStop(Color.FromArgb(alpha, Color.Parse(color).R, Color.Parse(color).G, Color.Parse(color).B), 0),
            new GradientStop(Color.FromArgb(0, Color.Parse(color).R, Color.Parse(color).G, Color.Parse(color).B), 1)
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

        string style = App.ActiveVisualStyle;
        bool isCanopy = style == "canopee-ambre";
        bool isWatercolor = style == "watercolor";
        bool isKde = style == "kde";
        bool isSketch = style == "sketch";
        bool isSticker = style == "sticker";
        bool isAero = style == "win7";
        bool isSchool = style == "school";
        bool isOffice = style == "office";
        bool isBento = style == "bento-pearl";
        bool isEink = style == "eink";
        bool isTactile = style == "tactile";
        bool isPrism = style == "alyx-prism";
        bool usesPalette = isWatercolor || isSketch || isSticker || isAero || isOffice || isBento || isTactile || isPrism;
        var handlePen = usesPalette ? PalettePen(App.ActiveAccentColor, isSticker ? 6 : 7)
            : StyleHandlePens.TryGetValue(style, out var hp) ? hp : HandlePen;
        var lensPen = usesPalette ? PalettePen(App.ActiveAccentColor, isSticker ? 3.2 : 2.8)
            : StyleLensPens.TryGetValue(style, out var lp) ? lp : LensPen;
        var iris = usesPalette ? PaletteIris(App.ActiveAccentColor, App.ActiveSecondaryColor, isPrism)
            : StyleIrises.TryGetValue(style, out var ib) ? ib : IrisGradient;

        if (isCanopy)
        {
            context.DrawEllipse(CanopySageWash, null, new Point(34, 34), 34, 34);
            context.DrawEllipse(CanopySunWash, null, new Point(50, 48), 30, 30);
        }
        else if (isWatercolor || isSketch || isBento || isPrism)
        {
            context.DrawEllipse(WcBlueWash, null, new Point(35, 34), 33, 33);
            context.DrawEllipse(WcRoseWash, null, new Point(49, 47), 31, 31);
        }

        if (isSchool)
            context.DrawLine(SchoolHighlightPen, new Point(12, 43), new Point(70, 41));

        if (isSticker)
            context.DrawLine(StickerCutPen, new Point(66, 66), new Point(88, 88));
        context.DrawLine(handlePen, new Point(66, 66), new Point(88, 88));
        context.DrawEllipse(isCanopy ? CanopyLensBacking : LensBacking, isSticker ? StickerCutPen : null, new Point(42, 42), isSticker ? 38 : 33, isSticker ? 38 : 33);
        context.DrawEllipse(isAero ? AeroLensBacking : LensBacking, lensPen, new Point(42, 42), 33, 33);

        using (context.PushGeometryClip(LensCircle))
        {
            if (isCanopy)
            {
                context.DrawEllipse(CanopySageWash, null, new Point(38, 37), 26, 26);
                context.DrawEllipse(CanopySunWash, null, new Point(47, 45), 24, 24);
            }
            else if (isWatercolor || isSketch || isBento || isPrism)
            {
                context.DrawEllipse(WcBlueWash, null, new Point(38, 37), 26, 26);
                context.DrawEllipse(WcRoseWash, null, new Point(47, 45), 24, 24);
            }

            if (isSchool)
            {
                for (int i = 0; i < 5; i++) context.DrawLine(SchoolLinePen, new Point(10, 23 + i * 9), new Point(74, 23 + i * 9));
                for (int i = 0; i < 6; i++) context.DrawLine(SchoolLinePen, new Point(15 + i * 10, 10), new Point(15 + i * 10, 74));
            }
            if (isSketch)
                for (int i = 0; i < 5; i++) context.DrawLine(SketchHatchPen, new Point(13 + i * 5, 56), new Point(22 + i * 5, 65));

            if (isKde || isPrism)
            {
                context.DrawEllipse(null, KdeReticlePen, new Point(42, 42), 28, 28);
                context.DrawLine(KdeReticlePen, new Point(42, 11), new Point(42, 20));
                context.DrawLine(KdeReticlePen, new Point(42, 64), new Point(42, 73));
                context.DrawLine(KdeReticlePen, new Point(11, 42), new Point(20, 42));
                context.DrawLine(KdeReticlePen, new Point(64, 42), new Point(73, 42));
            }
            if (isOffice)
                context.DrawEllipse(null, OfficeStampPen, new Point(42, 42), 27, 27);
            if (isAero || isBento || isPrism)
                context.DrawEllipse(AeroGloss, null, new Point(34, 27), 18, 9);
        }

        if (_spinOpacity > .01)
        {
            double angle = _clock.Elapsed.TotalMilliseconds / 1200.0 * 360;
            using var rot = context.PushTransform(Matrix.CreateTranslation(-42, -42) * Matrix.CreateRotation(angle * Math.PI / 180) * Matrix.CreateTranslation(42, 42));
            using var op = context.PushOpacity(_spinOpacity);
            context.DrawGeometry(null, SpinPen, Arc(42, 42, 27.5, 0, 62.5));
        }

        using var lid = context.PushTransform(Matrix.CreateTranslation(-42, -42) * Matrix.CreateScale(1, _lid) * Matrix.CreateTranslation(42, 42));
        context.DrawGeometry(Brushes.White, AlmondPen, Almond);

        using (context.PushGeometryClip(Almond))
        using (context.PushTransform(Matrix.CreateTranslation(_cx, _cy)))
        {
            context.DrawEllipse(iris, null, new Point(42, 42), 9.5, 9.5);
            context.DrawEllipse(isEink ? Brushes.Black : PupilBrush, null, new Point(42, 42), _rx, 7.8);
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
