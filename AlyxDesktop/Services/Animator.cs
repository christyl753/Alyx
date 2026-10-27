using Avalonia.Animation.Easings;
using Avalonia.Controls;
using System;
using System.Collections.Generic;
using System.Diagnostics;

namespace AlyxDesktop.Services;

/// <summary>Équivalent de cubic-bezier() CSS, dépassement (y &gt; 1) compris pour l'effet ressort.</summary>
public sealed class CubicBezierEasing : Easing
{
    private readonly double _x1, _y1, _x2, _y2;

    public CubicBezierEasing(double x1, double y1, double x2, double y2)
    {
        _x1 = x1; _y1 = y1; _x2 = x2; _y2 = y2;
    }

    // Courbes du design system
    public static readonly CubicBezierEasing Panel = new(.75, 0, .2, 1);
    public static readonly CubicBezierEasing Spring = new(.3, 1.4, .5, 1);
    public static readonly CubicBezierEasing OrbSpring = new(.3, 1.3, .5, 1);
    public static readonly CubicBezierEasing Standard = new(.25, .1, .25, 1); // « ease » CSS
    public static readonly CubicBezierEasing Linear = new(0, 0, 1, 1);

    private static double Bezier(double t, double p1, double p2)
    {
        double u = 1 - t;
        return 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t;
    }

    public override double Ease(double progress)
    {
        if (progress <= 0) return 0;
        if (progress >= 1) return 1;
        // Résout x(t) = progress (Newton puis dichotomie de secours)
        double t = progress;
        for (int i = 0; i < 8; i++)
        {
            double x = Bezier(t, _x1, _x2) - progress;
            double u = 1 - t;
            double dx = 3 * u * u * _x1 + 6 * u * t * (_x2 - _x1) + 3 * t * t * (1 - _x2);
            if (Math.Abs(x) < 1e-6) return Bezier(t, _y1, _y2);
            if (Math.Abs(dx) < 1e-6) break;
            t -= x / dx;
        }
        double lo = 0, hi = 1;
        t = progress;
        for (int i = 0; i < 30; i++)
        {
            double x = Bezier(t, _x1, _x2);
            if (Math.Abs(x - progress) < 1e-6) break;
            if (x < progress) lo = t; else hi = t;
            t = (lo + hi) / 2;
        }
        return Bezier(t, _y1, _y2);
    }
}

/// <summary>
/// Interpolations de valeurs pilotées image par image (RequestAnimationFrame).
/// Chaque clé garde sa valeur courante : relancer une animation en cours repart de là où elle en est,
/// comme une transition CSS.
/// </summary>
public sealed class Animator
{
    private sealed class Anim
    {
        public double From, To, Duration, Delay;
        public Easing Easing = CubicBezierEasing.Linear;
        public Action<double> Setter = _ => { };
        public Action? Done;
        public double Start;
    }

    private readonly TopLevel _top;
    private readonly Dictionary<string, Anim> _anims = new();
    private readonly Dictionary<string, double> _values = new();
    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private bool _frameRequested;

    public Animator(TopLevel top) => _top = top;

    public double Get(string key, double fallback = 0) => _values.TryGetValue(key, out var v) ? v : fallback;

    /// <summary>Fixe une valeur immédiatement (annule l'animation de cette clé).</summary>
    public void Set(string key, double value, Action<double> setter)
    {
        _anims.Remove(key);
        _values[key] = value;
        setter(value);
    }

    public void Animate(string key, double to, double durationMs, Easing easing, Action<double> setter,
                        double delayMs = 0, double? from = null, Action? done = null)
    {
        double start = from ?? Get(key, to);
        _anims[key] = new Anim
        {
            From = start, To = to, Duration = Math.Max(1, durationMs), Delay = delayMs,
            Easing = easing, Setter = setter, Done = done, Start = _clock.Elapsed.TotalMilliseconds
        };
        RequestFrame();
    }

    public bool IsAnimating => _anims.Count > 0;

    private void RequestFrame()
    {
        if (_frameRequested) return;
        _frameRequested = true;
        _top.RequestAnimationFrame(_ => Frame());
    }

    private void Frame()
    {
        _frameRequested = false;
        double now = _clock.Elapsed.TotalMilliseconds;
        List<Action>? done = null;
        foreach (var (key, a) in new List<KeyValuePair<string, Anim>>(_anims))
        {
            double elapsed = now - a.Start - a.Delay;
            if (elapsed < 0) continue;
            double p = Math.Min(1, elapsed / a.Duration);
            double v = a.From + (a.To - a.From) * a.Easing.Ease(p);
            _values[key] = v;
            a.Setter(v);
            if (p >= 1)
            {
                _anims.Remove(key);
                if (a.Done != null) (done ??= new()).Add(a.Done);
            }
        }
        if (done != null) foreach (var d in done) d();
        if (_anims.Count > 0) RequestFrame();
    }
}
