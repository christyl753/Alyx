using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace AlyxDesktop.Models;

public abstract class Observable : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected bool Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (Equals(field, value)) return false;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
        return true;
    }

    protected void Raise(string name) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

// ---------- Chat ----------
public abstract class ChatItem : Observable { }

public sealed class UserMessage : ChatItem
{
    public string Text { get; }
    public UserMessage(string text) => Text = text;
}

public sealed class AlyxMessage : ChatItem
{
    private string _text = "";
    public string Text { get => _text; set => Set(ref _text, value); }
    public AlyxMessage(string text = "") => _text = text;
}

public sealed class ActionMessage : ChatItem
{
    public string Text { get; }
    public ActionMessage(string text) => Text = text;
}

public sealed class ErrorMessage : ChatItem
{
    public string Text { get; }
    public ErrorMessage(string text) => Text = text;
}

/// <summary>Validation Human-in-the-Loop d'une action critique demandée par le LLM.</summary>
public sealed class PermissionRequest : ChatItem
{
    private bool _pending = true;
    private string _decision = "";
    public string Action { get; }
    public string Target { get; }
    public bool Pending { get => _pending; private set => Set(ref _pending, value); }
    public string Decision { get => _decision; private set => Set(ref _decision, value); }

    public PermissionRequest(string action, string target)
    {
        Action = action;
        Target = target;
    }

    public void Resolve(bool accepted)
    {
        Pending = false;
        Decision = accepted ? "Action autorisée" : "Action refusée";
    }
}

// ---------- Tâches ----------
public sealed class ProcessItem
{
    public int Pid { get; init; }
    public string Name { get; init; } = "";
    public double Cpu { get; init; }
    public double MemMb { get; init; }
    public bool IsAlyx { get; init; }

    public string PidText => $"PID {Pid}";
    public string CpuText => $"{Cpu:0.0}%";
    public string MemText => MemMb >= 1024 ? $"{MemMb / 1024:0.0} Go" : $"{MemMb:0} Mo";
    /// <summary>Largeur de la jauge CPU (piste de 42 px, échelle du design : cpu × 2,2 %).</summary>
    public double BarWidth => System.Math.Min(100, Cpu * 2.2) / 100 * 42;
}

// ---------- Voix ----------
public sealed class VoiceItem : Observable
{
    private bool _selected;
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public string Meta { get; init; } = "";
    public bool Selected { get => _selected; set => Set(ref _selected, value); }
}

// ---------- Modèles ----------
public sealed class ModelItem : Observable
{
    private bool _loading;
    public string Name { get; init; } = "";
    public string Provider { get; init; } = "";
    public string Size { get; init; } = "";
    public bool Loading { get => _loading; set { if (Set(ref _loading, value)) Raise(nameof(ButtonText)); } }

    public string Meta => string.IsNullOrEmpty(Size) || Size == "--" ? ProviderLabel : $"{ProviderLabel} · {Size}";
    public string ProviderLabel => Provider switch { "ollama" => "Ollama", "lmstudio" => "LM Studio", "nvidia" => "NVIDIA NIM", _ => Provider };
    public string ButtonText => Loading ? "…" : "Charger";
}

// ---------- Scanner, Garde-fou & Automatisations ----------
public sealed class ScannedFileItem : Observable
{
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public double SizeMb { get; init; }
    public string Status { get; init; } = "";
    public string ProposedPath { get; init; } = "";

    public string SizeText => $"{SizeMb:0.0} Mo";
    public string StatusText => Status switch
    {
        "organized" => "Rangé dans son dossier",
        "trashed" => "Placé dans la Corbeille",
        _ => string.IsNullOrEmpty(ProposedPath) ? Status : $"Suggéré : {ProposedPath}"
    };
}

public sealed class GuardrailBatchPlanItem : Observable
{
    private bool _selectedForBatch = true;
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public string ProposedPath { get; init; } = "";
    public string ProposedAction { get; init; } = "move"; // "trash" ou "move"

    public bool SelectedForBatch
    {
        get => _selectedForBatch;
        set => Set(ref _selectedForBatch, value);
    }

    public string ActionLabel => ProposedAction == "trash" ? "Corbeille" : "Ranger";
}

public sealed class ReversibleTrashItem : Observable
{
    public string Id { get; init; } = "";
    public string OriginalName { get; init; } = "";
    public string OriginalPath { get; init; } = "";
}

public sealed class AutomationRuleItem : Observable
{
    private bool _enabled = true;
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public string Description { get; init; } = "";
    public string TargetFolder { get; init; } = "";

    public bool Enabled
    {
        get => _enabled;
        set { if (Set(ref _enabled, value)) Raise(nameof(StatusText)); }
    }

    public string StatusText => Enabled ? "Active" : "Pause";
}

public sealed class RecentCommandItem : Observable
{
    public string Text { get; init; } = "";
}

