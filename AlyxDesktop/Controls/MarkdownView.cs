using AlyxDesktop.Services;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;

namespace AlyxDesktop.Controls;

/// <summary>
/// Affiche du Markdown (sortie du LLM) de façon lisible : titres, gras/italique, listes, code, citations,
/// tableaux, séparateurs et formules LaTeX ($…$, $$…$$, \(…\), \[…\]) converties en notation mathématique.
/// Pendant le streaming, le rendu est limité à ~12 fois par seconde.
/// </summary>
public sealed class MarkdownView : StackPanel
{
    public static readonly StyledProperty<string?> MarkdownProperty =
        AvaloniaProperty.Register<MarkdownView, string?>(nameof(Markdown));

    public string? Markdown { get => GetValue(MarkdownProperty); set => SetValue(MarkdownProperty, value); }

    private const double BodySize = 14;
    private static readonly FontFamily MathFont = new("Cambria Math, STIX Two Math, Latin Modern Math, DejaVu Serif, serif");

    private readonly Stopwatch _sinceRender = Stopwatch.StartNew();
    private bool _renderPending;

    public MarkdownView()
    {
        Spacing = 8;
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property != MarkdownProperty) return;
        if (_sinceRender.ElapsedMilliseconds >= 80 || Children.Count == 0)
        {
            Render();
        }
        else if (!_renderPending)
        {
            _renderPending = true;
            DispatcherTimer.RunOnce(() => { _renderPending = false; Render(); }, TimeSpan.FromMilliseconds(80));
        }
    }

    private void Render()
    {
        _sinceRender.Restart();
        Children.Clear();
        foreach (var block in BuildBlocks(Markdown ?? "", 0))
            Children.Add(block);
    }

    // ===================== Blocs =====================

    private static readonly Regex Heading = new(@"^(#{1,6})\s+(.*?)\s*#*\s*$");
    private static readonly Regex Rule = new(@"^\s{0,3}([-*_])(\s*\1){2,}\s*$");
    private static readonly Regex ListItem = new(@"^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$");
    private static readonly Regex TableSeparator = new(@"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$");

    private List<Control> BuildBlocks(string text, int depth)
    {
        var blocks = new List<Control>();
        var lines = text.Replace("\r", "").Split('\n');
        var paragraph = new List<string>();

        void FlushParagraph()
        {
            if (paragraph.Count == 0) return;
            blocks.Add(TextBlockFor(string.Join("\n", paragraph), BodySize));
            paragraph.Clear();
        }

        int i = 0;
        while (i < lines.Length)
        {
            string line = lines[i];
            string trimmed = line.Trim();

            // Bloc de code ```
            if (trimmed.StartsWith("```"))
            {
                FlushParagraph();
                string lang = trimmed[3..].Trim();
                var code = new List<string>();
                i++;
                while (i < lines.Length && !lines[i].Trim().StartsWith("```")) code.Add(lines[i++]);
                i++; // fermeture (absente pendant le streaming : le bloc reste ouvert)
                blocks.Add(CodeBlock(string.Join("\n", code), lang));
                continue;
            }

            // Formule centrée $$…$$ ou \[…\]
            string? closing = trimmed.StartsWith("$$") ? "$$" : trimmed.StartsWith(@"\[") ? @"\]" : null;
            if (closing != null)
            {
                FlushParagraph();
                string body = trimmed[2..];
                int end = body.IndexOf(closing, StringComparison.Ordinal);
                if (end < 0)
                {
                    var parts = new List<string> { body };
                    i++;
                    while (i < lines.Length)
                    {
                        int e = lines[i].IndexOf(closing, StringComparison.Ordinal);
                        if (e >= 0) { parts.Add(lines[i][..e]); break; }
                        parts.Add(lines[i++]);
                    }
                    body = string.Join(" ", parts);
                }
                else
                {
                    body = body[..end];
                }
                i++;
                blocks.Add(MathBlock(body));
                continue;
            }

            if (trimmed.Length == 0)
            {
                FlushParagraph();
                i++;
                continue;
            }

            var heading = Heading.Match(trimmed);
            if (heading.Success)
            {
                FlushParagraph();
                blocks.Add(HeadingBlock(heading.Groups[2].Value, heading.Groups[1].Value.Length));
                i++;
                continue;
            }

            if (Rule.IsMatch(line))
            {
                FlushParagraph();
                blocks.Add(new Border { Height = 1, Background = App.Res<IBrush>("Hair10"), Margin = new Thickness(0, 4) });
                i++;
                continue;
            }

            // Citation
            if (trimmed.StartsWith('>'))
            {
                FlushParagraph();
                var quote = new StringBuilder();
                while (i < lines.Length && lines[i].TrimStart().StartsWith('>'))
                {
                    string q = lines[i].TrimStart()[1..];
                    quote.AppendLine(q.StartsWith(' ') ? q[1..] : q);
                    i++;
                }
                var inner = new StackPanel { Spacing = 6 };
                foreach (var b in BuildBlocks(quote.ToString(), depth + 1)) inner.Children.Add(b);
                blocks.Add(new Border
                {
                    BorderBrush = App.Res<IBrush>("Accent"),
                    BorderThickness = new Thickness(2, 0, 0, 0),
                    Padding = new Thickness(10, 2, 0, 2),
                    Child = inner,
                    Opacity = .85,
                });
                continue;
            }

            // Tableau | a | b |
            if (trimmed.StartsWith('|') && i + 1 < lines.Length && TableSeparator.IsMatch(lines[i + 1]))
            {
                FlushParagraph();
                var rows = new List<string[]> { SplitRow(trimmed) };
                i += 2;
                while (i < lines.Length && lines[i].Trim().StartsWith('|')) rows.Add(SplitRow(lines[i++].Trim()));
                blocks.Add(TableBlock(rows));
                continue;
            }

            // Liste (à puces ou numérotée), imbrication par indentation
            var item = ListItem.Match(line);
            if (item.Success)
            {
                FlushParagraph();
                var list = new StackPanel { Spacing = 4 };
                while (i < lines.Length)
                {
                    var m = ListItem.Match(lines[i]);
                    if (!m.Success) break;
                    int level = Math.Min(3, m.Groups[1].Value.Replace("\t", "    ").Length / 2);
                    var content = new StringBuilder(m.Groups[3].Value);
                    i++;
                    // Lignes de continuation indentées
                    while (i < lines.Length && lines[i].Length > 0 && char.IsWhiteSpace(lines[i][0])
                           && lines[i].Trim().Length > 0 && !ListItem.IsMatch(lines[i]))
                        content.Append('\n').Append(lines[i++].Trim());
                    list.Children.Add(ListItemBlock(m.Groups[2].Value, content.ToString(), level));
                }
                blocks.Add(list);
                continue;
            }

            paragraph.Add(line.TrimEnd());
            i++;
        }
        FlushParagraph();
        return blocks;
    }

    private static string[] SplitRow(string row)
    {
        row = row.Trim();
        if (row.StartsWith('|')) row = row[1..];
        if (row.EndsWith('|')) row = row[..^1];
        return row.Split('|');
    }

    private Control HeadingBlock(string text, int level)
    {
        double size = level switch { 1 => 20, 2 => 17, 3 => 15.5, _ => 14 };
        var tb = TextBlockFor(text, size, FontWeight.SemiBold);
        tb.Margin = new Thickness(0, level <= 2 ? 6 : 2, 0, 0);
        tb.Foreground = App.Res<IBrush>("Ink");
        return tb;
    }

    private Control ListItemBlock(string marker, string content, int level)
    {
        bool ordered = char.IsDigit(marker[0]);
        string bullet = ordered ? marker.TrimEnd(')', '.') + "." : level switch { 0 => "•", 1 => "◦", _ => "▪" };
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Margin = new Thickness(level * 16, 0, 0, 0) };
        grid.Children.Add(new TextBlock
        {
            Text = bullet,
            FontSize = BodySize,
            LineHeight = BodySize * 1.6,
            MinWidth = ordered ? 20 : 14,
            Foreground = App.Res<IBrush>(ordered ? "AccentText" : "Muted"),
            FontFamily = ordered ? App.Res<FontFamily>("MonoFont") : FontFamily.Default,
        });
        var body = TextBlockFor(content, BodySize);
        Grid.SetColumn(body, 1);
        grid.Children.Add(body);
        return grid;
    }

    private static Control CodeBlock(string code, string lang)
    {
        var stack = new StackPanel { Spacing = 4 };
        if (lang.Length > 0)
            stack.Children.Add(new TextBlock { Text = lang.ToUpperInvariant(), FontFamily = App.Res<FontFamily>("MonoFont"), FontSize = 9.5, LetterSpacing = 0.8, Foreground = App.Res<IBrush>("Faint") });
        stack.Children.Add(new SelectableTextBlock
        {
            Text = code,
            FontFamily = App.Res<FontFamily>("MonoFont"),
            FontSize = 12,
            LineHeight = 18,
            TextWrapping = TextWrapping.Wrap,
            Foreground = App.Res<IBrush>("Ink"),
        });
        return new Border
        {
            Background = App.Res<IBrush>("Fill04"),
            BorderBrush = App.Res<IBrush>("Hair7"),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(12, 9),
            Child = stack,
        };
    }

    private static Control MathBlock(string tex)
    {
        var tb = new SelectableTextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            TextAlignment = TextAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Foreground = App.Res<IBrush>("Ink"),
            Margin = new Thickness(0, 2),
        };
        AddMath(tb.Inlines!, tex, 16.5, inline: false);
        return new Border
        {
            Background = App.Res<IBrush>("AccentTint05"),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(10, 8),
            Child = tb,
        };
    }

    private Control TableBlock(List<string[]> rows)
    {
        int cols = 0;
        foreach (var r in rows) cols = Math.Max(cols, r.Length);
        var grid = new Grid();
        for (int c = 0; c < cols; c++) grid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        for (int r = 0; r < rows.Count; r++)
        {
            grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            for (int c = 0; c < cols; c++)
            {
                string cell = c < rows[r].Length ? rows[r][c].Trim() : "";
                var tb = TextBlockFor(cell, 12.5, r == 0 ? FontWeight.SemiBold : FontWeight.Normal);
                var border = new Border
                {
                    Padding = new Thickness(8, 5),
                    BorderBrush = App.Res<IBrush>("Hair7"),
                    BorderThickness = new Thickness(0, 0, 0, 1),
                    Background = r == 0 ? App.Res<IBrush>("Fill04") : Brushes.Transparent,
                    Child = tb,
                };
                Grid.SetRow(border, r);
                Grid.SetColumn(border, c);
                grid.Children.Add(border);
            }
        }
        return new Border
        {
            BorderBrush = App.Res<IBrush>("Hair9"),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            ClipToBounds = true,
            Child = grid,
        };
    }

    private SelectableTextBlock TextBlockFor(string text, double size, FontWeight weight = FontWeight.Normal)
    {
        var tb = new SelectableTextBlock
        {
            FontSize = size,
            FontWeight = weight,
            LineHeight = size * 1.6,
            TextWrapping = TextWrapping.Wrap,
            Foreground = App.Res<IBrush>("TextBody"),
        };
        AddInlines(tb.Inlines!, text, size);
        return tb;
    }

    // ===================== Texte en ligne =====================

    private static void AddInlines(InlineCollection into, string s, double size)
    {
        var buffer = new StringBuilder();
        void Flush()
        {
            if (buffer.Length == 0) return;
            into.Add(new Run(buffer.ToString()));
            buffer.Clear();
        }

        int i = 0;
        while (i < s.Length)
        {
            char c = s[i];

            if (c == '\n')
            {
                Flush();
                into.Add(new LineBreak());
                i++;
                continue;
            }

            // Formule en ligne \( … \)
            if (c == '\\' && i + 1 < s.Length && s[i + 1] == '(')
            {
                int end = s.IndexOf(@"\)", i + 2, StringComparison.Ordinal);
                if (end > 0) { Flush(); AddMath(into, s[(i + 2)..end], size); i = end + 2; continue; }
            }
            // Échappement Markdown : \* \_ \$ \# …
            if (c == '\\' && i + 1 < s.Length && "\\`*_{}[]()#+-.!$|~>".IndexOf(s[i + 1]) >= 0)
            {
                buffer.Append(s[i + 1]);
                i += 2;
                continue;
            }

            // Code en ligne
            if (c == '`')
            {
                int end = s.IndexOf('`', i + 1);
                if (end > i)
                {
                    Flush();
                    into.Add(new Run(s[(i + 1)..end])
                    {
                        FontFamily = App.Res<FontFamily>("MonoFont"),
                        FontSize = size * .88,
                        Background = App.Res<IBrush>("Fill07"),
                        Foreground = App.Res<IBrush>("Ink"),
                    });
                    i = end + 1;
                    continue;
                }
            }

            // Formules $$…$$ (dans un paragraphe) et $…$
            if (c == '$')
            {
                bool dbl = i + 1 < s.Length && s[i + 1] == '$';
                string delim = dbl ? "$$" : "$";
                int start = i + delim.Length;
                int end = s.IndexOf(delim, start, StringComparison.Ordinal);
                // $ simple : pas d'espace juste après l'ouverture ni avant la fermeture (évite « 5 $ et 10 $ »)
                bool valid = end > start && (dbl || (!char.IsWhiteSpace(s[start]) && !char.IsWhiteSpace(s[end - 1])
                                                      && (end + 1 >= s.Length || !char.IsDigit(s[end + 1]))));
                if (valid)
                {
                    Flush();
                    AddMath(into, s[start..end], size);
                    i = end + delim.Length;
                    continue;
                }
            }

            // Gras ** / __, barré ~~
            if ((c == '*' || c == '_' || c == '~') && i + 1 < s.Length && s[i + 1] == c && (c != '_' || IsBoundary(s, i - 1)))
            {
                string delim = new(c, 2);
                int end = s.IndexOf(delim, i + 2, StringComparison.Ordinal);
                if (end > i + 2 && (c != '_' || IsBoundary(s, end + 2)))
                {
                    Flush();
                    Span span = c == '~' ? new Span { TextDecorations = TextDecorations.Strikethrough } : new Bold();
                    if (c != '~') span.Foreground = App.Res<IBrush>("Ink");
                    AddInlines(span.Inlines, s[(i + 2)..end], size);
                    into.Add(span);
                    i = end + 2;
                    continue;
                }
            }

            // Italique * / _
            if ((c == '*' || c == '_') && i + 1 < s.Length && !char.IsWhiteSpace(s[i + 1]) && (c != '_' || IsBoundary(s, i - 1)))
            {
                int end = FindClosingEmphasis(s, i + 1, c);
                if (end > i + 1)
                {
                    Flush();
                    var italic = new Italic();
                    AddInlines(italic.Inlines, s[(i + 1)..end], size);
                    into.Add(italic);
                    i = end + 1;
                    continue;
                }
            }

            // Lien [texte](url) : affiché comme texte souligné (pas de navigation : Alyx reste hors ligne)
            if (c == '[')
            {
                int close = s.IndexOf("](", i + 1, StringComparison.Ordinal);
                int end = close > 0 ? s.IndexOf(')', close + 2) : -1;
                if (close > i && end > close)
                {
                    Flush();
                    var link = new Span { TextDecorations = TextDecorations.Underline, Foreground = App.Res<IBrush>("AccentText") };
                    AddInlines(link.Inlines, s[(i + 1)..close], size);
                    into.Add(link);
                    i = end + 1;
                    continue;
                }
            }

            buffer.Append(c);
            i++;
        }
        Flush();
    }

    private static bool IsBoundary(string s, int index) => index < 0 || index >= s.Length || !char.IsLetterOrDigit(s[index]);

    private static int FindClosingEmphasis(string s, int from, char delim)
    {
        for (int j = from; j < s.Length; j++)
        {
            if (s[j] == '\n') return -1;
            if (s[j] == delim && !char.IsWhiteSpace(s[j - 1]) && (j + 1 >= s.Length || s[j + 1] != delim)
                && (delim != '_' || IsBoundary(s, j + 1)))
                return j;
        }
        return -1;
    }

    /// <summary>Formule : texte mathématique avec de vrais exposants et indices.</summary>
    private static void AddMath(InlineCollection into, string tex, double size, bool inline = true)
    {
        var ink = App.Res<IBrush>("Ink");
        foreach (var seg in MathText.Convert(tex.Trim()))
        {
            bool sup = seg.Position == MathPosition.Superscript;
            if (seg.Position == MathPosition.Normal)
            {
                // En ligne : espaces insécables, la formule ne se coupe pas en fin de ligne
                string text = inline ? seg.Text.Replace(' ', ' ') : seg.Text;
                into.Add(new Run(text) { FontFamily = MathFont, FontSize = size * 1.05, Foreground = ink });
            }
            else if (MathText.TryUnicodeScript(seg.Text, sup, out var unicode))
            {
                // Caractères ² ₙ… : décalage vertical natif, et le texte reste copiable
                into.Add(new Run(unicode) { FontFamily = MathFont, FontSize = size * 1.05, Foreground = ink });
            }
            else
            {
                // Pas d'équivalent Unicode : petit texte décalé à la main
                // (BaselineAlignment n'est pas appliqué par Avalonia 11.0)
                into.Add(new InlineUIContainer(new TextBlock
                {
                    Text = seg.Text,
                    FontFamily = MathFont,
                    FontSize = size * .72,
                    Foreground = ink,
                    // Le conteneur est aligné sur le haut de la ligne : indice décalé vers le bas, exposant presque pas
                    RenderTransform = new TranslateTransform(0, sup ? -size * .05 : size * .6),
                }));
            }
        }
    }
}
