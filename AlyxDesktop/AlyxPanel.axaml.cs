using AlyxDesktop.Controls;
using AlyxDesktop.Models;
using AlyxDesktop.Platform;
using AlyxDesktop.Services;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace AlyxDesktop;

/// <summary>Panneau d'Alyx : en-tête, stats, onglets (Chat, Système, Tâches, Modèles, Réglages) et barre média.</summary>
public partial class AlyxPanel : UserControl
{
    private static readonly CultureInfo Fr = CultureInfo.GetCultureInfo("fr-FR");

    private BackendClient? _backend;
    private WidgetSettings _settings = new();
    private readonly MediaService _media = new();

    private readonly ObservableCollection<ChatItem> _messages = new();
    private readonly ObservableCollection<ProcessItem> _processes = new();
    private readonly ObservableCollection<ModelItem> _models = new();
    private readonly ObservableCollection<VoiceItem> _voices = new();
    private readonly ObservableCollection<VoiceItem> _microphones = new();
    private bool _syncingVoice, _speakAll, _stickToBottom = true;
    private string _language = "fr";
    private IDisposable? _rateDebounce;

    // Streaming : tokens regroupés, une mise à jour UI par frame
    private AlyxMessage? _streaming;
    private readonly StringBuilder _pendingTokens = new();
    private bool _flushScheduled;

    private bool _connected, _generating, _menuActive, _inputFocused;
    private string _tab = "chat";
    private string _currentModel = "";
    private string? _loadingModel;
    private double? _tps;
    private readonly Dictionary<string, string> _modelProviders = new();
    private Dictionary<string, (double Vram, int? Ctx)> _loaded = new();
    private double _vramTotal;
    private Dictionary<QuickToggle, ToggleState> _toggles = new();
    private string? _ssid;
    private bool _syncingSliders;
    private IDisposable? _volumeDebounce, _brightnessDebounce;

    private readonly DispatcherTimer _clockTimer;
    private readonly DispatcherTimer _pollTimer;
    private int _pollTicks;

    /// <summary>Valeurs affichées par les bulles du menu radial.</summary>
    public double CpuPercent { get; private set; }
    public int ProcessTotal { get; private set; }
    public MediaState Media { get; private set; } = MediaService.None;
    public string CurrentModel => _currentModel;
    public EyeMode EyeMode { get; private set; } = EyeMode.Idle;

    public event Action? CloseRequested;
    public event Action? StateChanged;

    public AlyxPanel()
    {
        InitializeComponent();
        MessageList.ItemsSource = _messages;
        ProcessList.ItemsSource = _processes;
        ModelList.ItemsSource = _models;
        VoiceList.ItemsSource = _voices;
        MicList.ItemsSource = _microphones;
        RateSlider.PropertyChanged += (_, e) => { if (e.Property == RangeBase.ValueProperty) OnRateChanged(); };
        // Défilement collant : reste en bas tant que l'utilisateur n'a pas remonté le fil
        ChatScroll.ScrollChanged += (_, e) =>
        {
            if (e.ExtentDelta.Y != 0 && _stickToBottom) ChatScroll.ScrollToEnd();
            else if (e.OffsetDelta.Y != 0)
                _stickToBottom = ChatScroll.Offset.Y >= ChatScroll.Extent.Height - ChatScroll.Viewport.Height - 24;
        };

        _messages.Add(new AlyxMessage("Bonjour, je suis Alyx. Je tourne entièrement sur ce PC. Pose-moi une question, ou demande-moi ce qui se passe sur ta machine."));

        // Entrée envoie, Maj+Entrée ajoute une ligne : intercepté avant le TextBox
        Input.AddHandler(KeyDownEvent, OnInputKeyDown, RoutingStrategies.Tunnel);
        Input.GotFocus += (_, _) => { _inputFocused = true; RefreshComposer(); };
        Input.LostFocus += (_, _) => { _inputFocused = false; RefreshComposer(); };
        Input.PropertyChanged += (_, e) => { if (e.Property == TextBox.TextProperty) RefreshComposer(); };

        VolumeSlider.PropertyChanged += (_, e) => { if (e.Property == RangeBase.ValueProperty) OnVolumeChanged(); };
        BrightnessSlider.PropertyChanged += (_, e) => { if (e.Property == RangeBase.ValueProperty) OnBrightnessChanged(); };

        _clockTimer = new DispatcherTimer(TimeSpan.FromSeconds(1), DispatcherPriority.Background, (_, _) => UpdateClock());
        _pollTimer = new DispatcherTimer(TimeSpan.FromSeconds(1), DispatcherPriority.Background, async (_, _) => await PollAsync());
        UpdateClock();
        _clockTimer.Start();
        BuildTiles();
        RefreshComposer();
    }

    public void Init(BackendClient backend, WidgetSettings settings)
    {
        _backend = backend;
        _settings = settings;
        HeaderEye.FollowCursor = settings.EyeFollowsCursor;
        FollowTrack.Classes.Set("on", settings.EyeFollowsCursor);
        StartupTrack.Classes.Set("on", StartupService.IsEnabled());
        StartupLabel.Text = OperatingSystem.IsWindows() ? "Démarrer avec Windows" : "Démarrer avec la session";
        if (!OperatingSystem.IsWindows()) ShortcutText.Text = "Non disponible";
        backend.MessageReceived += OnBackendMessage;
        backend.ConnectionChanged += OnConnectionChanged;
    }

    // ================= Cycle de vie du menu =================

    /// <summary>Le menu (radial ou panneau) est visible : métriques et sondages actifs.</summary>
    public async void SetMenuActive(bool active)
    {
        if (_menuActive == active) return;
        _menuActive = active;
        if (active)
        {
            _pollTimer.Start();
            await Send(new { type = "subscribe_metrics", on = true });
            await Send(new { type = "get_processes", limit = 40 });
            _ = PollMediaAsync();
        }
        else
        {
            _pollTimer.Stop();
            await Send(new { type = "subscribe_metrics", on = false });
        }
    }

    public void SetFollowCursor(bool follow) => HeaderEye.FollowCursor = follow;

    public void SelectTab(string tab)
    {
        _tab = tab;
        foreach (var b in TabBar.Children.OfType<Button>())
            b.Classes.Set("active", (string?)b.Tag == tab);
        ChatView.IsVisible = tab == "chat";
        SystemView.IsVisible = tab == "system";
        TasksView.IsVisible = tab == "tasks";
        ModelsView.IsVisible = tab == "models";
        SettingsView.IsVisible = tab == "settings";

        switch (tab)
        {
            case "chat":
                Dispatcher.UIThread.Post(() => Input.Focus(), DispatcherPriority.Background);
                break;
            case "tasks":
                _ = Send(new { type = "get_processes", limit = 40 });
                break;
            case "models":
                _ = Send(new { type = "get_models", refresh = false });
                break;
            case "settings":
                _ = RefreshSettingsAsync();
                _ = Send(new { type = "get_voice_settings" });
                break;
        }
    }

    private Task Send(object payload) => _backend?.SendAsync(payload) ?? Task.CompletedTask;

    private async Task PollAsync()
    {
        _pollTicks++;
        await PollMediaAsync();
        if (_tab == "tasks" && _pollTicks % 2 == 0)
            await Send(new { type = "get_processes", limit = 40 });
    }

    // ================= Messages du backend =================

    private void OnConnectionChanged(bool connected)
    {
        _connected = connected;
        if (connected)
        {
            _ = Send(new { type = "get_models", refresh = false });
            if (_menuActive) _ = Send(new { type = "subscribe_metrics", on = true });
        }
        else
        {
            FlushTokens();
            _streaming = null;
            SetGenerating(false);
        }
        UpdateModelStatus();
    }

    private void OnBackendMessage(string type, JsonElement root)
    {
        if (type != "token") FlushTokens();
        switch (type)
        {
            case "token":
                _pendingTokens.Append(Str(root, "content"));
                if (!_flushScheduled)
                {
                    _flushScheduled = true;
                    Dispatcher.UIThread.Post(FlushTokens, DispatcherPriority.Background);
                }
                break;
            case "transcript":
                ThinkingText.Text = "Alyx réfléchit";
                _messages.Add(new UserMessage(Str(root, "content")));
                ScrollChatToEnd();
                break;
            case "system_action":
                _streaming = null;
                _messages.Add(new ActionMessage("› " + Str(root, "content")));
                ScrollChatToEnd();
                break;
            case "action_required":
                _streaming = null;
                _messages.Add(new PermissionRequest(Str(root, "action"), Str(root, "cible")));
                SetGenerating(false);
                ScrollChatToEnd();
                break;
            case "done":
                _streaming = null;
                if (root.TryGetProperty("tps", out var tps) && tps.ValueKind == JsonValueKind.Number) _tps = tps.GetDouble();
                SetGenerating(false);
                UpdateModelStatus();
                break;
            case "error":
                _streaming = null;
                _messages.Add(new ErrorMessage(Str(root, "message")));
                SetGenerating(false);
                ScrollChatToEnd();
                break;
            case "models_list":
                ApplyModels(root);
                break;
            case "model_selected":
                _currentModel = Str(root, "model");
                RebuildModelList();
                break;
            case "model_loading":
                _loadingModel = Str(root, "model");
                UpdateModelStatus();
                break;
            case "model_loaded":
                _loadingModel = null;
                _messages.Add(new AlyxMessage($"{Str(root, "model")} est chargé en mémoire. Je suis prête."));
                UpdateModelStatus();
                break;
            case "model_unloaded":
                _messages.Add(new ActionMessage($"› {Str(root, "model")} déchargé de la mémoire"));
                break;
            case "model_error":
                _loadingModel = null;
                _messages.Add(new ErrorMessage(Str(root, "message")));
                foreach (var m in _models) m.Loading = false;
                UpdateModelStatus();
                break;
            case "metrics":
                ApplyMetrics(root);
                break;
            case "processes":
                ApplyProcesses(root);
                break;
            case "voice_settings":
                ApplyVoiceSettings(root);
                break;
            case "microphones":
                ApplyMicrophones(root);
                break;
            case "microphone_test":
                ApplyMicrophoneTest(root);
                break;
            case "process_killed":
                ProcCount.Text = Str(root, "message");
                _ = Send(new { type = "get_processes", limit = 40 });
                break;
        }
    }

    private static string Str(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

    private static double? Num(JsonElement e, string name) =>
        e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null;

    private static JsonElement? Obj(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Object ? v : null;

    // ================= Chat =================

    private void FlushTokens()
    {
        _flushScheduled = false;
        if (_pendingTokens.Length == 0) return;
        if (_streaming == null)
        {
            _streaming = new AlyxMessage();
            _messages.Add(_streaming);
            ThinkingRow.IsVisible = false;
        }
        _streaming.Text += _pendingTokens.ToString();
        _pendingTokens.Clear();
        ScrollChatToEnd();
    }

    private void ScrollChatToEnd()
    {
        if (_stickToBottom) Dispatcher.UIThread.Post(() => ChatScroll.ScrollToEnd(), DispatcherPriority.Background);
    }

    private void SetGenerating(bool generating)
    {
        _generating = generating;
        ThinkingRow.IsVisible = generating && _streaming == null;
        SendGlyph.IsVisible = !generating;
        StopGlyph.IsVisible = generating;
        ToolTip.SetTip(SendButton, generating ? "Arrêter (kill switch)" : "Envoyer");
        Avalonia.Automation.AutomationProperties.SetName(SendButton, generating ? "Arrêter" : "Envoyer");
        MicButton.IsEnabled = !generating;
        RefreshComposer();
        if (generating) ScrollChatToEnd();
    }

    private void RefreshComposer()
    {
        bool hasText = !string.IsNullOrWhiteSpace(Input.Text);
        Composer.BorderBrush = App.Res<IBrush>(_inputFocused ? "AccentFocus" : "Hair8");
        SendButton.Background = App.Res<IBrush>(_generating || hasText ? "Accent" : "Fill12");
        Suggestions.IsVisible = _messages.Count <= 2 && !_generating;

        var mode = _generating ? EyeMode.Thinking : (_inputFocused && hasText) ? EyeMode.Listening : EyeMode.Idle;
        if (mode != EyeMode)
        {
            EyeMode = mode;
            HeaderEye.Mode = mode;
            StateChanged?.Invoke();
        }
    }

    public async Task SendMessageAsync(string? text = null, bool vocal = false)
    {
        if (_generating) return;
        text = (text ?? Input.Text ?? "").Trim();
        if (text.Length == 0 && !vocal) return;
        if (!_connected)
        {
            _messages.Add(new ErrorMessage("Le moteur d'Alyx n'est pas joignable. Lance-le avec alyx.bat (ou Lancer_Alyx.vbs)."));
            ScrollChatToEnd();
            return;
        }
        if (text.Length > 0)
        {
            _stickToBottom = true;
            _messages.Add(new UserMessage(text));
            Input.Text = "";
        }
        ThinkingText.Text = vocal && text.Length == 0 ? "Alyx écoute… parle maintenant" : "Alyx réfléchit";
        SetGenerating(true);
        await Send(new { type = "chat", prompt = text, vocal });
    }

    private async void OnInputKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && !e.KeyModifiers.HasFlag(KeyModifiers.Shift))
        {
            e.Handled = true;
            await SendMessageAsync();
        }
    }

    private async void OnSendClick(object? sender, RoutedEventArgs e)
    {
        if (_generating)
        {
            await Send(new { type = "cancel" });
            return;
        }
        await SendMessageAsync();
    }

    private async void OnMicClick(object? sender, RoutedEventArgs e) => await SendMessageAsync(vocal: true);

    private async void OnSuggestionClick(object? sender, RoutedEventArgs e)
    {
        if (sender is Button { Content: string q }) await SendMessageAsync(q);
    }

    private async void OnPermissionAccept(object? sender, RoutedEventArgs e) => await ResolvePermission(sender, true);
    private async void OnPermissionReject(object? sender, RoutedEventArgs e) => await ResolvePermission(sender, false);

    private async Task ResolvePermission(object? sender, bool accepted)
    {
        if (_generating || (sender as Control)?.DataContext is not PermissionRequest req || !req.Pending) return;
        req.Resolve(accepted);
        SetGenerating(true);
        await Send(new { type = accepted ? "permission_granted" : "permission_denied" });
    }

    private void OnCloseClick(object? sender, RoutedEventArgs e) => CloseRequested?.Invoke();

    private void OnTabClick(object? sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string tab }) SelectTab(tab);
    }

    // ================= En-tête =================

    private void UpdateClock()
    {
        var now = DateTime.Now;
        ClockText.Text = now.ToString("HH:mm", Fr);
        DateText.Text = now.ToString("dddd d MMMM", Fr);
    }

    private string ProviderLabel(string model) => _modelProviders.TryGetValue(model, out var p) ? p switch
    {
        "ollama" => "Ollama",
        "lmstudio" => "LM Studio",
        "nvidia" => "NVIDIA NIM",
        _ => p
    } : "local";

    private void UpdateModelStatus()
    {
        string dot, line;
        if (!_connected) { dot = "Faint"; line = "Moteur Alyx déconnecté"; }
        else if (_loadingModel != null) { dot = "Accent"; line = $"Chargement de {_loadingModel}…"; }
        else if (string.IsNullOrEmpty(_currentModel) || _currentModel == "Aucun modèle") { dot = "Faint"; line = "Aucun modèle disponible"; }
        else { dot = "Success"; line = $"{_currentModel} · {ProviderLabel(_currentModel)} · local"; }
        ModelDot.Fill = App.Res<IBrush>(dot);
        ModelLine.Text = line;
        RuntimeLine.Text = _connected && dot == "Success"
            ? $"Local · {ProviderLabel(_currentModel)}{(_tps is { } t ? $" · {t:0} tok/s" : "")}"
            : line;
        UpdateLoadedCard();
        StateChanged?.Invoke();
    }

    // ================= Métriques =================

    private void ApplyMetrics(JsonElement root)
    {
        bool generating = root.TryGetProperty("generating", out var g) && g.ValueKind == JsonValueKind.True;
        if (Obj(root, "cpu") is { } cpu)
        {
            CpuPercent = Num(cpu, "percent") ?? 0;
            StripCpu.Text = CpuValue.Text = $"{CpuPercent:0}%";
            CpuBars.Push(CpuPercent);
            var parts = new List<string>();
            if (Num(cpu, "cores") is { } cores) parts.Add($"{cores:0} cœurs");
            if (Num(cpu, "freq_ghz") is { } f) parts.Add($"{f.ToString("0.0", Fr)} GHz");
            CpuSub.Text = string.Join(" · ", parts);
        }
        if (Obj(root, "ram") is { } ram)
        {
            double p = Num(ram, "percent") ?? 0;
            StripRam.Text = RamValue.Text = $"{p:0}%";
            RamBars.Push(p);
            RamSub.Text = $"{(Num(ram, "used_gb") ?? 0).ToString("0.0", Fr)} / {(Num(ram, "total_gb") ?? 0).ToString("0.0", Fr)} Go utilisés";
        }
        if (Obj(root, "gpu") is { } gpu)
        {
            double p = Num(gpu, "percent") ?? 0;
            _vramTotal = Num(gpu, "vram_total_gb") ?? 0;
            StripGpu.Text = GpuValue.Text = $"{p:0}%";
            StripGpu.Foreground = App.Res<IBrush>(generating ? "AccentText" : "Ink");
            GpuBars.Push(p);
            string temp = Num(gpu, "temp") is { } t ? $" · {t:0}°C" : "";
            GpuSub.Text = $"VRAM {(Num(gpu, "vram_used_gb") ?? 0).ToString("0.0", Fr)} / {_vramTotal.ToString("0.0", Fr)} Go{temp}";
        }
        else
        {
            StripGpu.Text = GpuValue.Text = "—";
        }
        if (Obj(root, "net") is { } net)
        {
            double down = Num(net, "down_mbs") ?? 0, up = Num(net, "up_mbs") ?? 0;
            _ssid = Str(net, "ssid");
            StripNet.Text = $"↓ {down.ToString("0.0", Fr)} Mo/s";
            NetDown.Text = $"{down.ToString("0.0", Fr)} Mo/s";
            NetUp.Text = $"{up.ToString("0.00", Fr)} Mo/s";
            NetName.Text = string.IsNullOrEmpty(_ssid) ? "Réseau filaire" : $"Wi‑Fi · {_ssid}";
            string ip = Str(net, "ip");
            NetSub.Text = string.IsNullOrEmpty(ip) ? "Hors ligne" : $"IP {ip}";
        }
        if (Obj(root, "battery") is { } bat)
        {
            double p = Num(bat, "percent") ?? 0;
            bool plugged = bat.TryGetProperty("plugged", out var pl) && pl.ValueKind == JsonValueKind.True;
            StripBat.Text = BatValue.Text = $"{p:0}%";
            var color = App.Res<IBrush>(p < 20 && !plugged ? "Danger" : "Ink");
            StripBat.Foreground = color;
            double track = (BatFill.Parent as Control)?.Bounds.Width is > 0 and var w ? w : 340;
            BatFill.Width = track * p / 100;
            if (plugged) BatSub.Text = p >= 100 ? "Secteur · chargée" : "Secteur · en charge";
            else if (Num(bat, "secs_left") is { } s) BatSub.Text = $"{(int)(s / 3600)} h {(int)(s % 3600 / 60)} min restantes · sur batterie";
            else BatSub.Text = "Sur batterie";
        }
        else
        {
            StripBat.Text = BatValue.Text = "—";
            BatSub.Text = "Pas de batterie (poste fixe)";
        }
        UpdateLoadedCard();
        StateChanged?.Invoke();
    }

    // ================= Tâches =================

    private void ApplyProcesses(JsonElement root)
    {
        ProcessTotal = (int)(Num(root, "total") ?? 0);
        var items = root.TryGetProperty("items", out var arr) && arr.ValueKind == JsonValueKind.Array
            ? arr.EnumerateArray().Select(p => new ProcessItem
            {
                Pid = (int)(Num(p, "pid") ?? 0),
                Name = Str(p, "name"),
                Cpu = Num(p, "cpu") ?? 0,
                MemMb = Num(p, "mem_mb") ?? 0,
                IsAlyx = p.TryGetProperty("alyx", out var a) && a.ValueKind == JsonValueKind.True,
            }).ToList()
            : new List<ProcessItem>();
        _processes.Clear();
        foreach (var i in items) _processes.Add(i);
        ProcCount.Text = $"{ProcessTotal} processus · {items.Count} affichés";
        StateChanged?.Invoke();
    }

    private async void OnKillClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Control)?.DataContext is ProcessItem p)
            await Send(new { type = "kill_process", pid = p.Pid });
    }

    // ================= Modèles =================

    private void ApplyModels(JsonElement root)
    {
        _currentModel = Str(root, "current_model");
        _modelProviders.Clear();
        var all = new List<ModelItem>();
        if (Obj(root, "providers") is { } providers)
        {
            foreach (var provider in providers.EnumerateObject())
            foreach (var m in provider.Value.EnumerateArray())
            {
                string name = Str(m, "name");
                _modelProviders[name] = provider.Name;
                all.Add(new ModelItem { Name = name, Provider = provider.Name, Size = Str(m, "size") });
            }
        }
        _loaded = new();
        if (Obj(root, "loaded") is { } loaded)
            foreach (var l in loaded.EnumerateObject())
                _loaded[l.Name] = (Num(l.Value, "vram_gb") ?? 0, Num(l.Value, "ctx") is { } c ? (int)c : null);
        _allModels = all;
        RebuildModelList();
        UpdateModelStatus();
    }

    private List<ModelItem> _allModels = new();

    private void RebuildModelList()
    {
        _models.Clear();
        foreach (var m in _allModels.Where(m => m.Name != _currentModel))
        {
            m.Loading = m.Name == _loadingModel;
            _models.Add(m);
        }
        NoModels.IsVisible = _models.Count == 0;
        UpdateModelStatus();
    }

    private void UpdateLoadedCard()
    {
        bool has = !string.IsNullOrEmpty(_currentModel) && _currentModel != "Aucun modèle";
        LoadedCard.IsVisible = has;
        if (!has) return;
        bool inMemory = _loaded.TryGetValue(_currentModel, out var info);
        string provider = _modelProviders.GetValueOrDefault(_currentModel, "");
        string size = _allModels.FirstOrDefault(m => m.Name == _currentModel)?.Size ?? "";
        LoadedLabel.Text = _loadingModel == _currentModel ? "CHARGEMENT…" : inMemory ? "EN MÉMOIRE" : "SÉLECTIONNÉ";
        LoadedName.Text = _currentModel;
        LoadedMeta.Text = string.Join(" · ", new[] { ProviderLabel(_currentModel), size == "--" ? "" : size, "local" }.Where(s => s.Length > 0));
        LoadedTps.Text = _tps is { } t ? $"{t:0} tok/s" : "—";
        LoadedCtx.Text = inMemory && info.Ctx is { } ctx ? (ctx >= 1024 ? $"{ctx / 1024}k" : ctx.ToString()) : "—";
        LoadedVram.Text = inMemory && info.Vram > 0
            ? (_vramTotal > 0 ? $"{info.Vram.ToString("0.0", Fr)} / {_vramTotal:0} Go" : $"{info.Vram.ToString("0.0", Fr)} Go")
            : "—";
        double track = VramTrack.Bounds.Width > 0 ? VramTrack.Bounds.Width : 334;
        VramFill.Width = inMemory && _vramTotal > 0 ? track * Math.Min(1, info.Vram / _vramTotal) : 0;
        UnloadButton.IsVisible = provider == "ollama" && inMemory;
    }

    private async void OnLoadModelClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Control)?.DataContext is not ModelItem m) return;
        m.Loading = true;
        _loadingModel = m.Name;
        _tps = null;
        await Send(new { type = "load_model", model = m.Name });
    }

    private async void OnUnloadClick(object? sender, RoutedEventArgs e) =>
        await Send(new { type = "unload_model", model = _currentModel });

    private async void OnRefreshModelsClick(object? sender, RoutedEventArgs e) =>
        await Send(new { type = "get_models", refresh = true });

    // ================= Réglages =================

    private static readonly (QuickToggle Kind, string Label)[] TileDefs =
    {
        (QuickToggle.Wifi, "Wi‑Fi"), (QuickToggle.Bluetooth, "Bluetooth"), (QuickToggle.Focus, "Concentration"),
        (QuickToggle.NightLight, "Éclairage nocturne"), (QuickToggle.Airplane, "Mode avion"), (QuickToggle.BatterySaver, "Économiseur"),
    };

    private void BuildTiles()
    {
        TileGrid.Children.Clear();
        foreach (var (kind, label) in TileDefs)
        {
            var sub = new TextBlock { Classes = { "ts" }, Text = "…", TextTrimming = TextTrimming.CharacterEllipsis };
            var tile = new Button
            {
                Classes = { "flat", "tile" },
                Margin = new Thickness(0, 0, 8, 8),
                Tag = kind,
                Content = new StackPanel
                {
                    Spacing = 3,
                    HorizontalAlignment = HorizontalAlignment.Left,
                    Children = { new TextBlock { Classes = { "tl" }, Text = label, TextTrimming = TextTrimming.CharacterEllipsis }, sub }
                }
            };
            Avalonia.Automation.AutomationProperties.SetName(tile, label);
            tile.Click += OnTileClick;
            TileGrid.Children.Add(tile);
        }
    }

    private void RefreshTiles()
    {
        foreach (var tile in TileGrid.Children.OfType<Button>())
        {
            var kind = (QuickToggle)tile.Tag!;
            var state = _toggles.GetValueOrDefault(kind, new ToggleState(false, false, false));
            tile.Classes.Set("on", state.On);
            var sub = (TextBlock)((StackPanel)tile.Content!).Children[1];
            sub.Text = !state.Known && !state.Controllable ? "Paramètres"
                : kind == QuickToggle.Wifi && state.On && !string.IsNullOrEmpty(_ssid) ? _ssid
                : state.On ? "Activé" : "Désactivé";
        }
    }

    private async Task RefreshSettingsAsync()
    {
        _toggles = await QuickSettingsService.GetStatesAsync();
        RefreshTiles();
        var volume = await AudioService.GetVolumeAsync();
        var brightness = await BrightnessService.GetAsync();
        _syncingSliders = true;
        VolumeSlider.IsEnabled = volume.HasValue;
        VolumeSlider.Value = volume ?? 0;
        VolumeText.Text = volume?.ToString() ?? "—";
        BrightnessSlider.IsEnabled = brightness.HasValue;
        BrightnessSlider.Value = brightness ?? 0;
        BrightnessText.Text = brightness?.ToString() ?? "—";
        ToolTip.SetTip(BrightnessSlider, brightness.HasValue ? null : "Non pris en charge par cet écran");
        _syncingSliders = false;
    }

    private async void OnTileClick(object? sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: QuickToggle kind }) return;
        var state = _toggles.GetValueOrDefault(kind, new ToggleState(false, false, false));
        if (state.Controllable)
        {
            // Retour visuel immédiat, puis relecture de l'état réel
            _toggles[kind] = state with { On = !state.On };
            RefreshTiles();
        }
        await QuickSettingsService.ToggleAsync(kind, state);
        await Task.Delay(700);
        _toggles = await QuickSettingsService.GetStatesAsync();
        RefreshTiles();
    }

    private void OnVolumeChanged()
    {
        int v = (int)Math.Round(VolumeSlider.Value);
        VolumeText.Text = v.ToString();
        if (_syncingSliders) return;
        _volumeDebounce?.Dispose();
        _volumeDebounce = DispatcherTimer.RunOnce(() => _ = AudioService.SetVolumeAsync(v), TimeSpan.FromMilliseconds(60));
    }

    private void OnBrightnessChanged()
    {
        int v = (int)Math.Round(BrightnessSlider.Value);
        BrightnessText.Text = v.ToString();
        if (_syncingSliders) return;
        _brightnessDebounce?.Dispose();
        _brightnessDebounce = DispatcherTimer.RunOnce(() => _ = BrightnessService.SetAsync(v), TimeSpan.FromMilliseconds(150));
    }

    public event Action<bool>? FollowCursorChanged;

    private void OnFollowPrefClick(object? sender, RoutedEventArgs e)
    {
        _settings.EyeFollowsCursor = !_settings.EyeFollowsCursor;
        _settings.Save();
        FollowTrack.Classes.Set("on", _settings.EyeFollowsCursor);
        HeaderEye.FollowCursor = _settings.EyeFollowsCursor;
        FollowCursorChanged?.Invoke(_settings.EyeFollowsCursor);
    }

    private void OnStartupPrefClick(object? sender, RoutedEventArgs e)
    {
        bool target = !StartupService.IsEnabled();
        if (!StartupService.SetEnabled(target))
            _messages.Add(new ErrorMessage("Impossible de modifier le démarrage automatique."));
        StartupTrack.Classes.Set("on", StartupService.IsEnabled());
    }

    // ================= Voix et langue =================

    private void ApplyVoiceSettings(JsonElement root)
    {
        _syncingVoice = true;
        var prefs = Obj(root, "prefs");
        string voiceId = prefs is { } p0 ? Str(p0, "voice_id") : "";
        _language = prefs is { } p1 && Str(p1, "language") is { Length: > 0 } lang ? lang : "fr";
        _speakAll = prefs is { } p2 && p2.TryGetProperty("speak_all", out var sa) && sa.ValueKind == JsonValueKind.True;
        SpeakAllTrack.Classes.Set("on", _speakAll);
        RateSlider.Value = prefs is { } p3 ? Num(p3, "rate") ?? 0 : 0;
        RateText.Text = RateLabel(RateSlider.Value);

        // Langues
        string languageLabel = _language;
        LanguageChips.Children.Clear();
        if (root.TryGetProperty("languages", out var langs) && langs.ValueKind == JsonValueKind.Array)
        {
            foreach (var l in langs.EnumerateArray())
            {
                string code = Str(l, "code"), label = Str(l, "label");
                if (code == _language) languageLabel = label;
                var chip = new Button { Classes = { "flat", "chip", "hover-accent" }, Content = label, Tag = code, Margin = new Thickness(0, 0, 6, 6) };
                chip.Classes.Set("on", code == _language);
                Avalonia.Automation.AutomationProperties.SetName(chip, $"Langue : {label}");
                chip.Click += OnLanguageClick;
                LanguageChips.Children.Add(chip);
            }
        }

        // Voix : celles de la langue choisie d'abord
        _voices.Clear();
        if (root.TryGetProperty("voices", out var voices) && voices.ValueKind == JsonValueKind.Array)
        {
            var items = voices.EnumerateArray().Select(v => new
            {
                Item = new VoiceItem
                {
                    Id = Str(v, "id"),
                    Name = Str(v, "name"),
                    Meta = string.Join(" · ", new[] { Str(v, "lang_label"), Str(v, "engine") }.Where(s => s.Length > 0)),
                    Selected = Str(v, "id") == voiceId,
                },
                Match = Str(v, "lang").StartsWith(_language, StringComparison.OrdinalIgnoreCase),
            }).OrderByDescending(x => x.Match);
            foreach (var x in items) _voices.Add(x.Item);
        }

        bool hasLanguageVoice = root.TryGetProperty("has_language_voice", out var h) && h.ValueKind == JsonValueKind.True;
        NoLanguageVoice.IsVisible = !hasLanguageVoice;
        NoLanguageVoiceText.Text = OperatingSystem.IsWindows()
            ? $"Aucune voix « {languageLabel} » n'est installée : Alyx lira les réponses avec une voix d'une autre langue. "
              + "Ajoutez-en une dans Paramètres Windows › Heure et langue › Voix (Julie, Paul ou Hortense pour le français), puis rouvrez cet onglet."
            : $"Aucune voix « {languageLabel} » n'est installée. Installez espeak-ng et sa langue (ex. : sudo dnf install espeak-ng).";
        InstallVoicesButton.IsVisible = OperatingSystem.IsWindows();
        _syncingVoice = false;
    }

    private static string RateLabel(double rate) => $"×{Math.Pow(3, rate / 10).ToString("0.0", Fr)}";

    private async void OnLanguageClick(object? sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string code } && code != _language)
            await Send(new { type = "set_voice_settings", language = code });
    }

    private async void OnVoiceClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Control)?.DataContext is not VoiceItem voice) return;
        foreach (var v in _voices) v.Selected = v == voice;
        await Send(new { type = "set_voice_settings", voice_id = voice.Id });
        await Send(new { type = "test_voice" });
    }

    private void OnRateChanged()
    {
        RateText.Text = RateLabel(RateSlider.Value);
        if (_syncingVoice) return;
        int rate = (int)Math.Round(RateSlider.Value);
        _rateDebounce?.Dispose();
        _rateDebounce = DispatcherTimer.RunOnce(() => _ = Send(new { type = "set_voice_settings", rate }), TimeSpan.FromMilliseconds(250));
    }

    private async void OnSpeakAllClick(object? sender, RoutedEventArgs e)
    {
        _speakAll = !_speakAll;
        SpeakAllTrack.Classes.Set("on", _speakAll);
        await Send(new { type = "set_voice_settings", speak_all = _speakAll });
    }

    private async void OnTestVoiceClick(object? sender, RoutedEventArgs e) => await Send(new { type = "test_voice" });

    private void OnInstallVoicesClick(object? sender, RoutedEventArgs e) => Shell.OpenUri("ms-settings:speech");

    // ================= Micro =================

    private void ApplyMicrophones(JsonElement root)
    {
        string selected = Str(root, "selected");
        string defaultName = "";
        _microphones.Clear();
        var devices = root.TryGetProperty("devices", out var d) && d.ValueKind == JsonValueKind.Array
            ? d.EnumerateArray().ToList() : new List<JsonElement>();
        foreach (var dev in devices)
            if (dev.TryGetProperty("default", out var isDef) && isDef.ValueKind == JsonValueKind.True) defaultName = Str(dev, "name");
        bool known = devices.Any(dev => Str(dev, "name") == selected);

        // "" = micro par défaut du système (suit les changements faits dans Windows)
        _microphones.Add(new VoiceItem
        {
            Id = "",
            Name = "Micro par défaut du système",
            Meta = defaultName.Length > 0 ? defaultName : "aucun micro détecté",
            Selected = selected.Length == 0 || !known,
        });
        foreach (var dev in devices)
        {
            string name = Str(dev, "name");
            _microphones.Add(new VoiceItem { Id = name, Name = name, Meta = name == defaultName ? "défaut Windows" : "", Selected = known && name == selected });
        }

        string stt = Str(root, "stt");
        MicHintText.Text = stt switch
        {
            "injoignable" => "Le service de reconnaissance vocale ne répond pas : relance Alyx (alyx.bat).",
            "modele" => "La reconnaissance vocale (faster-whisper) n'est pas installée ou n'a pas pu se charger : relance install.bat.",
            "chargement" => "Le modèle de reconnaissance vocale se charge (première utilisation : téléchargement d'environ 140 Mo)…",
            _ => devices.Count == 0 ? "Aucun micro détecté : branche un micro ou un casque, puis rouvre cet onglet." : "",
        };
        MicHint.IsVisible = MicHintText.Text.Length > 0;
    }

    private async void OnMicrophoneClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Control)?.DataContext is not VoiceItem mic) return;
        foreach (var m in _microphones) m.Selected = m == mic;
        MicTestText.IsVisible = MicLevel.IsVisible = false;
        await Send(new { type = "set_microphone", name = mic.Id });
    }

    private async void OnTestMicrophoneClick(object? sender, RoutedEventArgs e)
    {
        MicTestButton.IsEnabled = false;
        MicLevel.IsVisible = false;
        MicTestText.IsVisible = true;
        MicTestText.Foreground = App.Res<IBrush>("Ink2");
        MicTestText.Text = "Parle pendant 2 secondes…";
        await Send(new { type = "test_microphone" });
    }

    private void ApplyMicrophoneTest(JsonElement root)
    {
        MicTestButton.IsEnabled = true;
        double level = Num(root, "level") ?? 0;
        string error = Str(root, "error");
        MicTestText.IsVisible = true;
        MicLevel.IsVisible = error.Length == 0;
        // Échelle logarithmique : une voix normale (crête ~0,1–0,5) remplit la jauge aux trois quarts
        MicLevelFill.Width = MicLevel.Width * Math.Clamp((Math.Log10(Math.Max(level, 1e-4)) + 4) / 4, 0, 1);
        MicTestText.Foreground = App.Res<IBrush>(error.Length == 0 ? "Ink2" : "Danger");
        MicTestText.Text = error.Length == 0
            ? (level < 0.02 ? $"« {Str(root, "device")} » capte du son, mais faiblement : parle plus près du micro." : $"« {Str(root, "device")} » fonctionne.")
            : Str(root, "message");
    }

    // ================= Média =================

    public async Task PollMediaAsync()
    {
        var state = await _media.GetStateAsync();
        Media = state;
        TrackTitle.Text = state.Title;
        TrackArtist.Text = state.Artist;
        PlayGlyph.IsVisible = !state.Playing;
        PauseGlyph.IsVisible = state.Playing;
        ArtImage.Source = _media.Artwork;
        ArtPlaceholder.IsVisible = _media.Artwork == null;
        double track = TrackBar.Bounds.Width > 0 ? TrackBar.Bounds.Width : 200;
        TrackFill.Width = state.DurationSec > 0 ? track * Math.Clamp(state.PositionSec / state.DurationSec, 0, 1) : 0;
        StateChanged?.Invoke();
    }

    public async Task TogglePlayAsync()
    {
        await _media.TogglePlayPauseAsync();
        await Task.Delay(250);
        await PollMediaAsync();
    }

    private async void OnPlayClick(object? sender, RoutedEventArgs e) => await TogglePlayAsync();

    private async void OnNextClick(object? sender, RoutedEventArgs e)
    {
        await _media.NextAsync();
        await Task.Delay(400);
        await PollMediaAsync();
    }

    private async void OnPrevClick(object? sender, RoutedEventArgs e)
    {
        await _media.PreviousAsync();
        await Task.Delay(400);
        await PollMediaAsync();
    }
}
