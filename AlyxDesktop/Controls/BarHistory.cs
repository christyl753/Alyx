using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using System;
using System.Collections.Generic;

namespace AlyxDesktop.Controls;

/// <summary>Historique en barres (36 valeurs, 1 Hz) : les barres anciennes sont plus transparentes.</summary>
public sealed class BarHistory : Control
{
    public const int Capacity = 36;

    public static readonly StyledProperty<IBrush?> BarBrushProperty =
        AvaloniaProperty.Register<BarHistory, IBrush?>(nameof(BarBrush), Brushes.Black);

    public IBrush? BarBrush { get => GetValue(BarBrushProperty); set => SetValue(BarBrushProperty, value); }

    private readonly Queue<double> _values = new();

    /// <summary>Ajoute une valeur en pourcentage (0-100).</summary>
    public void Push(double percent)
    {
        _values.Enqueue(Math.Clamp(percent, 0, 100));
        while (_values.Count > Capacity) _values.Dequeue();
        InvalidateVisual();
    }

    public override void Render(DrawingContext context)
    {
        if (BarBrush == null || Bounds.Width <= 0) return;
        const double gap = 2;
        double w = (Bounds.Width - gap * (Capacity - 1)) / Capacity;
        // Les mesures les plus récentes sont à droite ; les emplacements encore vides ne sont pas dessinés
        int i = Capacity - _values.Count;
        foreach (var v in _values)
        {
            double h = Math.Max(Bounds.Height * .04, v / 100 * Bounds.Height);
            using (context.PushOpacity(.25 + .75 * i / Capacity))
                context.DrawRectangle(BarBrush, null, new Rect(i * (w + gap), Bounds.Height - h, w, h), 1, 1);
            i++;
        }
    }
}
