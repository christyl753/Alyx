using Avalonia;
using Avalonia.Animation;
using Avalonia.Animation.Easings;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Layout;
using Avalonia.Styling;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AlyxDesktop;

public partial class MainWindow : Window
{
    private readonly HttpClient _httpClient = new HttpClient
    {
        Timeout = TimeSpan.FromSeconds(120)
    };
    private bool _isVocalActive = false;
    private bool _isProcessing = false;
    private bool _isLoadingModels = false;
    private string _currentModel = "gemma4";

    public MainWindow()
    {
        InitializeComponent();
        AddMessage("Alyx", "Système initialisé. Bonjour, je suis Alyx. Quel concept allons-nous prototyper aujourd'hui ?", true);
        // Load models on startup
        _ = LoadModelsAsync();
    }

    // ========== Animated Typing Indicator ==========
    private StackPanel? _typingContainer = null;
    private CancellationTokenSource? _animationCts = null;

    private void ShowTypingIndicator()
    {
        _typingContainer = new StackPanel
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            MaxWidth = 420,
            Margin = new Thickness(0, 0, 0, 10),
            Spacing = 5
        };

        // Meta label
        var metaPanel = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 10,
            Margin = new Thickness(0, 0, 0, 5)
        };
        metaPanel.Children.Add(new TextBlock
        {
            Text = "ALYX.SYS",
            FontWeight = FontWeight.Bold,
            FontFamily = new FontFamily("Monospace"),
            FontSize = 11,
            Foreground = new SolidColorBrush(Color.Parse("#1A1A1A"))
        });
        metaPanel.Children.Add(new TextBlock
        {
            Text = "Calcul en cours...",
            FontFamily = new FontFamily("Monospace"),
            FontSize = 11,
            Foreground = new SolidColorBrush(Color.Parse("#E55934"))
        });

        // Main animated box
        var outerBox = new Border
        {
            BorderBrush = new SolidColorBrush(Color.Parse("#1A1A1A")),
            BorderThickness = new Thickness(1.5),
            Background = new SolidColorBrush(Color.Parse("#F4F4F2")),
            Padding = new Thickness(15, 12),
            MinWidth = 300
        };

        var content = new StackPanel { Spacing = 10 };

        // Pencil icon + "Alyx réfléchit" text
        var topRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
        topRow.Children.Add(new TextBlock
        {
            Text = "✏",
            FontSize = 18,
            VerticalAlignment = VerticalAlignment.Center
        });
        topRow.Children.Add(new TextBlock
        {
            Text = "Alyx réfléchit...",
            FontSize = 14,
            Foreground = new SolidColorBrush(Color.Parse("#475569")),
            FontStyle = FontStyle.Italic,
            VerticalAlignment = VerticalAlignment.Center
        });
        content.Children.Add(topRow);

        // Animated hatched progress bar
        var accentHatch = this.FindResource("AccentHatchBrush") as IBrush;

        var progressTrack = new Border
        {
            Height = 10,
            BorderBrush = new SolidColorBrush(Color.Parse("#1A1A1A")),
            BorderThickness = new Thickness(1),
            ClipToBounds = true
        };

        var progressFill = new Border
        {
            Background = accentHatch ?? new SolidColorBrush(Color.Parse("#E55934")),
            HorizontalAlignment = HorizontalAlignment.Left,
            Width = 0
        };
        progressTrack.Child = progressFill;
        content.Children.Add(progressTrack);

        outerBox.Child = content;

        _typingContainer.Children.Add(metaPanel);
        _typingContainer.Children.Add(outerBox);

        ChatPanel.Children.Add(_typingContainer);
        Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() => ChatScrollViewer.ScrollToEnd());

        // Start progress animation
        _animationCts = new CancellationTokenSource();
        _ = AnimateProgressBar(progressFill, progressTrack, _animationCts.Token);
    }

    private async Task AnimateProgressBar(Border fill, Border track, CancellationToken ct)
    {
        try
        {
            double maxWidth = 280;
            double step = 4;
            double currentWidth = 0;
            bool growing = true;

            while (!ct.IsCancellationRequested)
            {
                await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() =>
                {
                    fill.Width = currentWidth;
                });

                if (growing)
                {
                    currentWidth += step;
                    if (currentWidth >= maxWidth) growing = false;
                }
                else
                {
                    currentWidth -= step;
                    if (currentWidth <= 0) growing = true;
                }

                await Task.Delay(30, ct);
            }
        }
        catch (OperationCanceledException) { }
    }

    private void HideTypingIndicator()
    {
        _animationCts?.Cancel();
        _animationCts = null;
        if (_typingContainer != null)
        {
            ChatPanel.Children.Remove(_typingContainer);
            _typingContainer = null;
        }
    }

    // ========== Message Rendering ==========
    private void AddMessage(string sender, string text, bool isSystem, bool isAction = false)
    {
        bool isUser = !isSystem;

        string metaLabel;
        if (isUser)
            metaLabel = "USER.INPUT";
        else if (isAction)
            metaLabel = "SYS.ACTION";
        else
            metaLabel = "ALYX.SYS";

        var container = new Grid
        {
            Margin = new Thickness(0, 0, 0, 10),
            HorizontalAlignment = isUser ? HorizontalAlignment.Right : HorizontalAlignment.Left,
            MaxWidth = 650
        };

        var metadataPanel = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 10,
            Margin = new Thickness(0, 0, 0, 5),
            HorizontalAlignment = isUser ? HorizontalAlignment.Right : HorizontalAlignment.Left
        };

        metadataPanel.Children.Add(new TextBlock
        {
            Text = metaLabel,
            FontWeight = FontWeight.Bold,
            FontFamily = new FontFamily("Monospace"),
            FontSize = 11,
            Foreground = new SolidColorBrush(Color.Parse(isAction ? "#E55934" : "#1A1A1A"))
        });
        metadataPanel.Children.Add(new TextBlock
        {
            Text = $"[{DateTime.Now:HH:mm}]",
            Foreground = new SolidColorBrush(Color.Parse("#94a3b8")),
            FontFamily = new FontFamily("Monospace"),
            FontSize = 11
        });

        var messageContentGrid = new Grid();

        if (isUser)
        {
            messageContentGrid.Children.Add(new Border
            {
                Background = new SolidColorBrush(Color.Parse("#D0D0CE")),
                Margin = new Thickness(-6, 6, 6, -6)
            });
        }
        else if (!isAction)
        {
            var hatchBrush = this.FindResource("HatchBrush") as IBrush;
            messageContentGrid.Children.Add(new Border
            {
                Background = hatchBrush ?? new SolidColorBrush(Color.Parse("#cccccc")),
                Margin = new Thickness(6, 6, -6, -6)
            });
        }

        var mainBox = new Border
        {
            BorderBrush = new SolidColorBrush(Color.Parse("#1A1A1A")),
            BorderThickness = new Thickness(1.5),
            Padding = new Thickness(20),
            Background = new SolidColorBrush(Color.Parse(isUser ? "#1A1A1A" : "#F4F4F2"))
        };

        if (isAction)
        {
            mainBox.BorderBrush = new SolidColorBrush(Color.Parse("#94a3b8"));
            mainBox.Background = new SolidColorBrush(Color.Parse("#FAFAF8"));
        }

        var textBlock = new TextBlock
        {
            Text = text,
            Foreground = new SolidColorBrush(Color.Parse(isUser ? "#F4F4F2" : "#1A1A1A")),
            TextWrapping = TextWrapping.Wrap,
            FontSize = 15,
            LineHeight = 22
        };

        mainBox.Child = textBlock;
        messageContentGrid.Children.Add(mainBox);

        if (isSystem && !isAction)
        {
            var tape = new Border
            {
                Width = 32,
                Height = 16,
                Background = new SolidColorBrush(Color.Parse("#33E55934")),
                BorderBrush = new SolidColorBrush(Color.Parse("#E55934")),
                BorderThickness = new Thickness(1),
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(15, -8, 0, 0),
                RenderTransform = new RotateTransform(-2)
            };
            messageContentGrid.Children.Add(tape);
        }

        var finalStack = new StackPanel { Spacing = 5 };
        finalStack.Children.Add(metadataPanel);
        finalStack.Children.Add(messageContentGrid);

        container.Children.Add(finalStack);
        ChatPanel.Children.Add(container);

        Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() => ChatScrollViewer.ScrollToEnd());
    }

    // ========== Model Management ==========
    private async Task LoadModelsAsync()
    {
        if (_isLoadingModels) return;
        _isLoadingModels = true;

        try
        {
            var response = await _httpClient.GetAsync("http://localhost:5000/api/models");
            if (response.IsSuccessStatusCode)
            {
                string body = await response.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(body);
                var root = doc.RootElement;

                var items = new List<string>();

                if (root.TryGetProperty("current_model", out var currentEl))
                {
                    _currentModel = currentEl.GetString() ?? "gemma4";
                }

                if (root.TryGetProperty("providers", out var providers))
                {
                    foreach (var provider in providers.EnumerateObject())
                    {
                        string providerName = provider.Name.ToUpper();
                        foreach (var model in provider.Value.EnumerateArray())
                        {
                            string name = model.GetProperty("name").GetString() ?? "unknown";
                            string size = model.GetProperty("size").GetString() ?? "";
                            string display = size != "--" && size != ""
                                ? $"[{providerName}] {name} ({size})"
                                : $"[{providerName}] {name}";
                            items.Add(display);
                        }
                    }
                }

                await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() =>
                {
                    ModelSelector.ItemsSource = items;

                    // Select current model
                    for (int i = 0; i < items.Count; i++)
                    {
                        if (items[i].Contains(_currentModel))
                        {
                            ModelSelector.SelectedIndex = i;
                            break;
                        }
                    }

                    ModelText.Text = $"Modèle: {_currentModel}";
                    StatusText.Text = "Statut: Connecté";
                });
            }
        }
        catch
        {
            await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() =>
            {
                ModelSelector.ItemsSource = new List<string> { $"[LOCAL] {_currentModel}" };
                ModelSelector.SelectedIndex = 0;
                StatusText.Text = "Statut: API non connectée";
            });
        }
        finally
        {
            _isLoadingModels = false;
        }
    }

    private async void OnModelChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (ModelSelector.SelectedItem is not string selected || _isLoadingModels) return;

        // Extract model name from display string "[PROVIDER] model_name (size)"
        string modelName = selected;
        int bracketEnd = modelName.IndexOf(']');
        if (bracketEnd >= 0)
            modelName = modelName[(bracketEnd + 2)..]; // skip "] "
        int parenStart = modelName.IndexOf(" (");
        if (parenStart >= 0)
            modelName = modelName[..parenStart];
        modelName = modelName.Trim();

        if (modelName == _currentModel) return;

        try
        {
            var payload = new { model = modelName };
            string json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("http://localhost:5000/api/models/select", content);
            if (response.IsSuccessStatusCode)
            {
                _currentModel = modelName;
                ModelText.Text = $"Modèle: {_currentModel}";
                AddMessage("Système", $"Modèle changé vers '{_currentModel}'", true, true);
            }
        }
        catch { }
    }

    private async void OnRefreshModelsClick(object? sender, RoutedEventArgs e)
    {
        AddMessage("Système", "Actualisation des modèles disponibles...", true, true);
        await LoadModelsAsync();
    }

    // ========== Event Handlers ==========
    private async void OnSendClick(object? sender, RoutedEventArgs e)
    {
        await SendMessageAsync();
    }

    private async void OnInputKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            await SendMessageAsync();
        }
    }

    private void OnVocalClick(object? sender, RoutedEventArgs e)
    {
        _isVocalActive = !_isVocalActive;
        VocalBtn.Content = _isVocalActive ? "🎤 On" : "🎤 Off";
        VocalBtn.Foreground = new SolidColorBrush(Color.Parse(_isVocalActive ? "#E55934" : "#475569"));
        VocalBtn.BorderBrush = new SolidColorBrush(Color.Parse(_isVocalActive ? "#E55934" : "#94a3b8"));

        if (_isVocalActive)
        {
            AddMessage("Système", "Mode vocal activé. Je vous écoute...", true, true);
            _ = SendMessageAsync();
        }
        else
        {
            AddMessage("Système", "Mode vocal désactivé.", true, true);
        }
    }

    private void OnClearChatClick(object? sender, RoutedEventArgs e)
    {
        ChatPanel.Children.Clear();
        AddMessage("Alyx", "Conversation réinitialisée. Comment puis-je vous aider ?", true);
    }

    // ========== Networking ==========
    private async Task SendMessageAsync(string? overrideText = null)
    {
        if (_isProcessing) return;

        string text = overrideText ?? InputBox.Text?.Trim() ?? "";
        if (string.IsNullOrEmpty(text) && !_isVocalActive) return;

        if (!string.IsNullOrEmpty(text))
        {
            AddMessage("Vous", text, false);
            InputBox.Text = "";
        }

        _isProcessing = true;
        SendBtn.Content = "...";
        SendBtn.IsEnabled = false;

        ShowTypingIndicator();

        var stopwatch = Stopwatch.StartNew();

        try
        {
            var payload = new
            {
                message = text,
                vocal = _isVocalActive
            };

            string json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("http://localhost:5000/api/chat", content);
            response.EnsureSuccessStatusCode();

            stopwatch.Stop();

            string responseBody = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(responseBody);
            var root = doc.RootElement;

            if (root.TryGetProperty("actions", out var actionsEl) && actionsEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var action in actionsEl.EnumerateArray())
                {
                    AddMessage("Système", action.GetString() ?? "", true, true);
                }
            }

            if (root.TryGetProperty("message", out var msgEl))
            {
                string msgText = msgEl.GetString() ?? "";
                if (!string.IsNullOrWhiteSpace(msgText))
                {
                    AddMessage("Alyx", msgText, true);
                }
            }

            LatencyText.Text = $"Latence: {stopwatch.ElapsedMilliseconds}ms";
            StatusText.Text = "Statut: Connecté";
        }
        catch (TaskCanceledException)
        {
            AddMessage("Erreur", "La requête a expiré (timeout 120s). Vérifiez que l'API et Ollama sont fonctionnels.", true, true);
            StatusText.Text = "Statut: Timeout";
        }
        catch (HttpRequestException)
        {
            AddMessage("Erreur", "Connexion à l'API Python échouée. Vérifiez que le serveur est lancé sur le port 5000.", true, true);
            StatusText.Text = "Statut: Déconnecté";
        }
        catch (Exception ex)
        {
            AddMessage("Erreur", $"Erreur inattendue : {ex.Message}", true, true);
            StatusText.Text = "Statut: Erreur";
        }
        finally
        {
            HideTypingIndicator();

            _isProcessing = false;
            SendBtn.Content = "GÉNÉRER ▸";
            SendBtn.IsEnabled = true;

            InputBox.Focus();

            if (_isVocalActive && string.IsNullOrEmpty(text))
            {
                await Task.Delay(1000);
                _ = SendMessageAsync();
            }
        }
    }
}