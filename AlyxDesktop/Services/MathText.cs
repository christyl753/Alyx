using System.Collections.Generic;
using System.Text;

namespace AlyxDesktop.Services;

public enum MathPosition { Normal, Superscript, Subscript }

/// <summary>Morceau de formule : texte + position (normal, exposant, indice).</summary>
public readonly record struct MathSegment(string Text, MathPosition Position);

/// <summary>
/// Convertit une formule LaTeX simple en texte mathématique lisible :
/// \frac{V}{d} → V/d, E_c → E + indice c, x^2 → x + exposant 2, \alpha → α, \leq → ≤, etc.
/// Couvre ce que les LLM produisent couramment ; les commandes inconnues sont affichées sans « \ ».
/// </summary>
public static class MathText
{
    private static readonly Dictionary<string, string> Symbols = new()
    {
        // Lettres grecques
        ["alpha"] = "α", ["beta"] = "β", ["gamma"] = "γ", ["delta"] = "δ", ["epsilon"] = "ε", ["varepsilon"] = "ε",
        ["zeta"] = "ζ", ["eta"] = "η", ["theta"] = "θ", ["vartheta"] = "ϑ", ["iota"] = "ι", ["kappa"] = "κ",
        ["lambda"] = "λ", ["mu"] = "μ", ["nu"] = "ν", ["xi"] = "ξ", ["pi"] = "π", ["varpi"] = "ϖ", ["rho"] = "ρ",
        ["sigma"] = "σ", ["varsigma"] = "ς", ["tau"] = "τ", ["upsilon"] = "υ", ["phi"] = "φ", ["varphi"] = "φ",
        ["chi"] = "χ", ["psi"] = "ψ", ["omega"] = "ω",
        ["Gamma"] = "Γ", ["Delta"] = "Δ", ["Theta"] = "Θ", ["Lambda"] = "Λ", ["Xi"] = "Ξ", ["Pi"] = "Π",
        ["Sigma"] = "Σ", ["Upsilon"] = "Υ", ["Phi"] = "Φ", ["Psi"] = "Ψ", ["Omega"] = "Ω",
        // Opérateurs et relations
        ["times"] = "×", ["cdot"] = "·", ["div"] = "÷", ["pm"] = "±", ["mp"] = "∓", ["ast"] = "∗",
        ["leq"] = "≤", ["le"] = "≤", ["geq"] = "≥", ["ge"] = "≥", ["neq"] = "≠", ["ne"] = "≠",
        ["approx"] = "≈", ["simeq"] = "≃", ["sim"] = "∼", ["equiv"] = "≡", ["propto"] = "∝", ["ll"] = "≪", ["gg"] = "≫",
        ["infty"] = "∞", ["partial"] = "∂", ["nabla"] = "∇", ["sum"] = "Σ", ["prod"] = "Π", ["int"] = "∫",
        ["iint"] = "∬", ["oint"] = "∮", ["lim"] = "lim", ["log"] = "log", ["ln"] = "ln", ["exp"] = "exp",
        ["sin"] = "sin", ["cos"] = "cos", ["tan"] = "tan", ["max"] = "max", ["min"] = "min", ["det"] = "det",
        ["in"] = "∈", ["notin"] = "∉", ["subset"] = "⊂", ["subseteq"] = "⊆", ["cup"] = "∪", ["cap"] = "∩",
        ["forall"] = "∀", ["exists"] = "∃", ["emptyset"] = "∅", ["neg"] = "¬", ["land"] = "∧", ["lor"] = "∨",
        ["to"] = "→", ["rightarrow"] = "→", ["leftarrow"] = "←", ["leftrightarrow"] = "↔", ["Rightarrow"] = "⇒",
        ["Leftarrow"] = "⇐", ["Leftrightarrow"] = "⇔", ["implies"] = "⇒", ["iff"] = "⇔", ["mapsto"] = "↦",
        ["uparrow"] = "↑", ["downarrow"] = "↓", ["circ"] = "∘", ["degree"] = "°", ["angle"] = "∠", ["perp"] = "⊥",
        ["parallel"] = "∥", ["ldots"] = "…", ["cdots"] = "⋯", ["dots"] = "…", ["prime"] = "′", ["hbar"] = "ℏ",
        ["ell"] = "ℓ", ["Re"] = "ℜ", ["Im"] = "ℑ", ["langle"] = "⟨", ["rangle"] = "⟩", ["lvert"] = "|", ["rvert"] = "|",
        ["vert"] = "|", ["Vert"] = "‖", ["mid"] = "|", ["backslash"] = "\\", ["%"] = "%",
        // Espacements
        ["quad"] = "  ", ["qquad"] = "    ", ["space"] = " ", ["enspace"] = " ",
    };

    private static readonly Dictionary<char, string> Blackboard = new()
    {
        ['R'] = "ℝ", ['N'] = "ℕ", ['Z'] = "ℤ", ['Q'] = "ℚ", ['C'] = "ℂ",
    };

    // Commandes dont on garde simplement le contenu de l'argument
    private static readonly HashSet<string> Wrappers = new()
    {
        "text", "textrm", "textit", "textbf", "mathrm", "mathit", "mathbf", "mathsf", "mathtt", "mathcal",
        "operatorname", "boldsymbol", "vec", "overline", "underline", "hat", "bar", "tilde", "dot", "ddot", "mbox", "displaystyle",
    };

    private const string Plain = "0123456789+-−=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVWβγδθφχ";
    private const string Sup = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂᵝᵞᵟᶿᵠᵡ";
    private static readonly Dictionary<char, char> SubMap = new()
    {
        ['0'] = '₀', ['1'] = '₁', ['2'] = '₂', ['3'] = '₃', ['4'] = '₄', ['5'] = '₅', ['6'] = '₆', ['7'] = '₇', ['8'] = '₈', ['9'] = '₉',
        ['+'] = '₊', ['-'] = '₋', ['−'] = '₋', ['='] = '₌', ['('] = '₍', [')'] = '₎',
        ['a'] = 'ₐ', ['e'] = 'ₑ', ['h'] = 'ₕ', ['i'] = 'ᵢ', ['j'] = 'ⱼ', ['k'] = 'ₖ', ['l'] = 'ₗ', ['m'] = 'ₘ', ['n'] = 'ₙ',
        ['o'] = 'ₒ', ['p'] = 'ₚ', ['r'] = 'ᵣ', ['s'] = 'ₛ', ['t'] = 'ₜ', ['u'] = 'ᵤ', ['v'] = 'ᵥ', ['x'] = 'ₓ',
        ['β'] = 'ᵦ', ['γ'] = 'ᵧ', ['ρ'] = 'ᵨ', ['φ'] = 'ᵩ', ['χ'] = 'ᵪ',
    };

    /// <summary>Exposant / indice en caractères Unicode si tous les caractères ont un équivalent (²,  ₙ…).</summary>
    public static bool TryUnicodeScript(string text, bool superscript, out string result)
    {
        var sb = new StringBuilder(text.Length);
        foreach (char ch in text)
        {
            if (superscript)
            {
                int idx = Plain.IndexOf(ch);
                if (idx < 0) { result = ""; return false; }
                sb.Append(Sup[idx]);
            }
            else
            {
                if (!SubMap.TryGetValue(ch, out var s)) { result = ""; return false; }
                sb.Append(s);
            }
        }
        result = sb.ToString();
        return text.Length > 0;
    }

    public static List<MathSegment> Convert(string tex)
    {
        var output = new List<MathSegment>();
        int i = 0;
        ParseSequence(tex, ref i, MathPosition.Normal, output, stopAtBrace: false);
        return Merge(output);
    }

    private static List<MathSegment> Merge(List<MathSegment> segments)
    {
        var merged = new List<MathSegment>();
        foreach (var s in segments)
        {
            if (s.Text.Length == 0) continue;
            // « ^\circ » → symbole degré sur la ligne de base
            var seg = s.Position == MathPosition.Superscript && s.Text == "∘" ? new MathSegment("°", MathPosition.Normal) : s;
            if (merged.Count > 0 && merged[^1].Position == seg.Position)
                merged[^1] = new MathSegment(merged[^1].Text + seg.Text, seg.Position);
            else
                merged.Add(seg);
        }
        return merged;
    }

    private static void ParseSequence(string tex, ref int i, MathPosition pos, List<MathSegment> output, bool stopAtBrace)
    {
        while (i < tex.Length)
        {
            char c = tex[i];
            if (c == '}' && stopAtBrace) { i++; return; }
            switch (c)
            {
                case '{':
                    i++;
                    ParseSequence(tex, ref i, pos, output, stopAtBrace: true);
                    break;
                case '}':
                    i++;
                    break;
                case '^':
                case '_':
                    i++;
                    // Exposant d'exposant : on reste au même niveau (l'affichage ne gère qu'un niveau)
                    var target = pos != MathPosition.Normal ? pos : c == '^' ? MathPosition.Superscript : MathPosition.Subscript;
                    ParseArgument(tex, ref i, target, output);
                    break;
                case '\\':
                    ParseCommand(tex, ref i, pos, output);
                    break;
                case '~':
                    output.Add(new(" ", pos));
                    i++;
                    break;
                case '&':
                    output.Add(new("  ", pos));
                    i++;
                    break;
                case '\'':
                    output.Add(new("′", pos));
                    i++;
                    break;
                case '-':
                    output.Add(new("−", pos));
                    i++;
                    break;
                default:
                    output.Add(new(c.ToString(), pos));
                    i++;
                    break;
            }
        }
    }

    /// <summary>Argument d'une commande ou d'un ^/_ : groupe {…}, commande \x ou caractère seul.</summary>
    private static void ParseArgument(string tex, ref int i, MathPosition pos, List<MathSegment> output)
    {
        while (i < tex.Length && tex[i] == ' ') i++;
        if (i >= tex.Length) return;
        if (tex[i] == '{')
        {
            i++;
            ParseSequence(tex, ref i, pos, output, stopAtBrace: true);
        }
        else if (tex[i] == '\\')
        {
            ParseCommand(tex, ref i, pos, output);
        }
        else
        {
            output.Add(new(tex[i] == '-' ? "−" : tex[i].ToString(), pos));
            i++;
        }
    }

    private static string ArgumentText(string tex, ref int i)
    {
        var tmp = new List<MathSegment>();
        ParseArgument(tex, ref i, MathPosition.Normal, tmp);
        var sb = new StringBuilder();
        foreach (var s in tmp) sb.Append(s.Text);
        return sb.ToString();
    }

    private static List<MathSegment> ArgumentSegments(string tex, ref int i, MathPosition pos)
    {
        var tmp = new List<MathSegment>();
        ParseArgument(tex, ref i, pos, tmp);
        return tmp;
    }

    private static bool IsSimple(List<MathSegment> segs)
    {
        int len = 0;
        foreach (var s in segs)
        {
            foreach (char ch in s.Text)
                if (!char.IsLetterOrDigit(ch) && ch != '.' && ch != ',') return false;
            len += s.Text.Length;
        }
        return len > 0 && len <= 12;
    }

    private static void ParseCommand(string tex, ref int i, MathPosition pos, List<MathSegment> output)
    {
        i++; // '\'
        if (i >= tex.Length) return;
        char first = tex[i];
        if (!char.IsLetter(first))
        {
            i++;
            output.Add(new(first switch
            {
                ',' or ':' or ';' or '>' => " ",
                '!' => "",
                '\\' => "\n",
                _ => first.ToString(), // \{ \} \% \$ \_ \& \#
            }, pos));
            return;
        }
        int start = i;
        while (i < tex.Length && char.IsLetter(tex[i])) i++;
        string name = tex[start..i];

        switch (name)
        {
            case "frac":
            case "dfrac":
            case "tfrac":
            {
                var num = ArgumentSegments(tex, ref i, pos);
                var den = ArgumentSegments(tex, ref i, pos);
                bool simple = IsSimple(num) && IsSimple(den);
                if (!simple) output.Add(new("(", pos));
                output.AddRange(num);
                output.Add(new(simple ? "/" : ")/(", pos));
                output.AddRange(den);
                if (!simple) output.Add(new(")", pos));
                return;
            }
            case "sqrt":
            {
                string? index = null;
                if (i < tex.Length && tex[i] == '[')
                {
                    int end = tex.IndexOf(']', i);
                    if (end > i) { index = tex[(i + 1)..end]; i = end + 1; }
                }
                if (index != null) output.Add(new(index, MathPosition.Superscript));
                var arg = ArgumentSegments(tex, ref i, pos);
                bool simple = IsSimple(arg);
                output.Add(new(simple ? "√" : "√(", pos));
                output.AddRange(arg);
                if (!simple) output.Add(new(")", pos));
                return;
            }
            case "mathbb":
            {
                string arg = ArgumentText(tex, ref i);
                output.Add(new(arg.Length == 1 && Blackboard.TryGetValue(arg[0], out var bb) ? bb : arg, pos));
                return;
            }
            case "left":
            case "right":
            case "big":
            case "Big":
            case "bigg":
            case "Bigg":
                // Le délimiteur qui suit (\left( ou \left\{) est rendu tel quel ; « . » = invisible
                if (i < tex.Length && tex[i] == '.') i++;
                return;
            case "begin":
            case "end":
                ArgumentText(tex, ref i); // \begin{aligned} : environnement ignoré
                return;
        }

        if (Wrappers.Contains(name))
        {
            output.AddRange(ArgumentSegments(tex, ref i, pos));
            return;
        }
        output.Add(new(Symbols.TryGetValue(name, out var sym) ? sym : name, pos));
        // Opérateurs nommés : une espace pour séparer de l'argument (\sin x)
        if (sym != null && sym.Length > 1 && char.IsLetter(sym[0])) output.Add(new(" ", pos));
    }
}
