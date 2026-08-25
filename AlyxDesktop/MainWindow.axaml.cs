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
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AlyxDesktop;

public partial class MainWindow : Window
{
    // Handler avec ConnectCallback : désactive l'algorithme de Nagle (Socket.NoDelay)
    // sur la connexion WebSocket locale, ClientWebSocketOptions ne l'exposant pas
    // directement. Réduit la latence perçue GUI <-> agent (Windows et Linux).
    private static readonly HttpMessageInvoker s_wsInvoker = new HttpMessageInvoker(new SocketsHttpHandler
    {
        ConnectCallback = async (context, cancellationToken) =>
        {
            var socket = new Socket(SocketType.Stream, ProtocolType.Tcp) { NoDelay = true };
            try
            {
                await socket.ConnectAsync(context.DnsEndPoint, cancellationToken);
                return new NetworkStream(socket, ownsSocket: true);
            }
            catch
            {
                socket.Dispose();
                throw;
            }
        }
    });

    private ClientWebSocket _webSocket = new ClientWebSocket();
    private bool _isVocalActive = false;
    private bool _isProcessing = false;
    private string _currentModel = "Chargement...";
    private TextBlock? _currentStreamingBlock = null;

    // --- Mode vocal continu ---
    // Nombre d'échecs RÉELS consécutifs (micro absent/occupé, service STT indisponible)
    // avant coupure automatique du mode vocal. Un silence normal (personne ne parle)
    // ne compte PAS comme un échec : sinon une pause de conversation couperait le micro.
    // Miroir de stt.max_consecutive_failures dans config.yaml (pas de dépendance YAML
    // côté C# pour un seul entier — les deux valeurs doivent rester alignées si modifiées).
    private const int MaxEchecsVocalConsecutifs = 3;
    private int _echecsVocalConsecutifs = 0;

    public MainWindow()
    {
        InitializeComponent();
        AddMessage("Alyx", "Système initialisé. Bonjour, je suis Alyx. Quel concept allons-nous prototyper aujourd'hui ?", true);
        _ = ConnectWebSocketAsync();
    }

    private async Task ConnectWebSocketAsync()
    {
        while (true)
        {
            try
            {
                if (_webSocket.State != WebSocketState.Open)
                {
                    _webSocket = new ClientWebSocket();
                    await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() => StatusText.Text = "Statut: Connexion...");
                    await _webSocket.ConnectAsync(new Uri("ws://127.0.0.1:8765"), s_wsInvoker, CancellationToken.None);
                    
                    await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() => StatusText.Text = "Statut: Connecté");
                    
                    // Demande des modèles après connexion
                    await SendWebSocketMessage(new { type = "get_models", refresh = false });
                    
                    _ = ReceiveLoopAsync();
                }
                break;
            }
            catch (Exception)
            {
                await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() => StatusText.Text = "Statut: Déconnecté (Re-essai...)");
                await Task.Delay(3000);
            }
        }
    }

    private async Task SendWebSocketMessage(object payload)
    {
        if (_webSocket.State == WebSocketState.Open)
        {
            string json = JsonSerializer.Serialize(payload);
            byte[] bytes = Encoding.UTF8.GetBytes(json);
            await _webSocket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, CancellationToken.None);
        }
    }

    private async Task ReceiveLoopAsync()
    {
        var buffer = new byte[8192];
        var sb = new StringBuilder();

        try
        {
            while (_webSocket.State == WebSocketState.Open)
            {
                var result = await _webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), CancellationToken.None);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    await _webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None);
                    break;
                }

                sb.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                if (result.EndOfMessage)
                {
                    string message = sb.ToString();
                    sb.Clear();
                    _ = HandleServerMessageAsync(message);
                }
            }
        }
        catch (Exception)
        {
            // Disconnected
        }

        await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() => 
        {
            StatusText.Text = "Statut: Déconnecté";
            _ = ConnectWebSocketAsync(); // Reconnect
        });
    }

    private async Task HandleServerMessageAsync(string messageJson)
    {
        try
        {
            using var doc = JsonDocument.Parse(messageJson);
            var root = doc.RootElement;
            string type = root.TryGetProperty("type", out var typeEl) ? typeEl.GetString() ?? "" : "";

            await Avalonia.Threading.Dispatcher.UIThread.InvokeAsync(() =>
            {
                switch (type)
                {
                    case "models_list":
                        _currentModel = root.GetProperty("current_model").GetString() ?? "Aucun modèle";
                        var items = new List<string>();
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
                        
                        ModelSelector.ItemsSource = items;
                        for (int i = 0; i < items.Count; i++)
                        {
                            if (items[i].Contains(_currentModel))
                            {
                                ModelSelector.SelectedIndex = i;
                                break;
                            }
                        }
                        ModelText.Text = $"Modèle: {_currentModel}";
                        break;
                        
                    case "model_selected":
                        _currentModel = root.GetProperty("model").GetString() ?? "";
                        ModelText.Text = $"Modèle: {_currentModel}";
                        AddMessage("Système", $"Modèle changé vers '{_currentModel}'", true, true);
                        break;

                    case "mobile_info": {
                        bool allowLan = root.TryGetProperty("allow_lan", out var allowLanEl) && allowLanEl.GetBoolean();
                        string? lanIp = root.TryGetProperty("lan_ip", out var lanIpEl) ? lanIpEl.GetString() : null;
                        int mobilePort = root.TryGetProperty("mobile_port", out var mpEl) ? mpEl.GetInt32() : 0;
                        string token = root.TryGetProperty("token", out var tokEl) ? (tokEl.GetString() ?? "") : "";
                        AddMobileInfoMessage(allowLan, lanIp, mobilePort, token);
                        break;
                    }

                    case "pairing_token_regenerated": {
                        string nouveauToken = root.GetProperty("token").GetString() ?? "";
                        AddMessage("Système",
                            $"Nouveau code de jumelage généré : {nouveauToken}\nLes téléphones déjà connectés devront ressaisir ce nouveau code.",
                            true, true);
                        break;
                    }

                    case "system_action":
                        string content = root.GetProperty("content").GetString() ?? "";
                        AddMessage("Système", content, true, true);
                        break;

                    case "listening":
                        // Distinct de l'indicateur "réflexion" : l'utilisateur sait qu'il doit
                        // parler maintenant, pas attendre une réponse.
                        ShowTypingIndicator("Écoute...", "Je vous écoute, parlez maintenant...", "🎙️");
                        StopBtn.IsVisible = true;
                        break;

                    case "token":
                        if (_currentStreamingBlock == null)
                        {
                            _currentStreamingBlock = AddStreamingMessage("Alyx");
                            HideTypingIndicator(); // L'IA commence à parler
                        }
                        _currentStreamingBlock.Text += root.GetProperty("content").GetString();
                        ChatScrollViewer.ScrollToEnd();
                        break;

                    case "done":
                        _currentStreamingBlock = null;
                        _isProcessing = false;
                        SendBtn.Content = "GÉNÉRER ▸";
                        SendBtn.IsEnabled = true;
                        StopBtn.IsVisible = false;
                        HideTypingIndicator();
                        // Un tour complet a réussi (réponse obtenue) : le compteur d'échecs
                        // repart de zéro, sinon un échec isolé ancien finirait par couper le
                        // mode vocal après plusieurs tours pourtant sains.
                        _echecsVocalConsecutifs = 0;
                        ContinuerEcouteSiVocalActif();
                        break;

                    case "error":
                        string errorMsg = root.GetProperty("message").GetString() ?? "Erreur";
                        string? raisonErreur = root.TryGetProperty("reason", out var raisonEl) ? raisonEl.GetString() : null;
                        bool estSilenceNormal = raisonErreur == "silence";

                        // Un silence (personne n'a parlé) est normal dans une conversation à
                        // bâtons rompus : l'afficher comme une "Erreur" en rouge à chaque pause
                        // serait à la fois faux et anxiogène. On le passe sous silence côté UI.
                        if (!estSilenceNormal)
                        {
                            AddMessage("Erreur", errorMsg, true, true);
                        }

                        _isProcessing = false;
                        SendBtn.Content = "GÉNÉRER ▸";
                        SendBtn.IsEnabled = true;
                        StopBtn.IsVisible = false;
                        HideTypingIndicator();

                        bool echecVocalReel = raisonErreur == "erreur_micro" || raisonErreur == "modele_indisponible";
                        if (_isVocalActive && echecVocalReel)
                        {
                            _echecsVocalConsecutifs++;
                            if (_echecsVocalConsecutifs >= MaxEchecsVocalConsecutifs)
                            {
                                _echecsVocalConsecutifs = 0;
                                _isVocalActive = false;
                                VocalBtn.Content = "🎤 Off";
                                VocalBtn.Foreground = new SolidColorBrush(Color.Parse("#475569"));
                                VocalBtn.BorderBrush = new SolidColorBrush(Color.Parse("#94a3b8"));
                                // Le point central : le bouton reflète TOUJOURS l'état réel. Avant ce
                                // correctif, le mode vocal s'arrêtait de fonctionner silencieusement en
                                // gardant l'apparence "🎤 On" — l'utilisateur parlait dans le vide sans
                                // le savoir. Ici, l'arrêt automatique est explicite et expliqué.
                                AddMessage("Système",
                                    $"Mode vocal désactivé automatiquement après {MaxEchecsVocalConsecutifs} échecs d'écoute consécutifs (micro ou service vocal indisponible). Vérifiez votre micro puis réactivez-le.",
                                    true, true);
                                break;
                            }
                        }
                        else if (!estSilenceNormal)
                        {
                            // Erreur non liée au vocal (ex: aucun modèle sélectionné) : ne pas
                            // relancer une boucle d'écoute qui échouerait à l'identique indéfiniment.
                            break;
                        }

                        ContinuerEcouteSiVocalActif();
                        break;
                        
                    case "action_required":
                        string action = root.GetProperty("action").GetString() ?? "";
                        string cible = root.GetProperty("cible").GetString() ?? "";
                        var toolCall = root.GetProperty("tool_call").Clone();
                        AddActionRequiredMessage(action, cible, toolCall);
                        break;
                }
            });
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Error parsing JSON: {ex.Message}");
        }
    }


    // ========== Animated Typing Indicator ==========
    private StackPanel? _typingContainer = null;
    private CancellationTokenSource? _animationCts = null;

    private void ShowTypingIndicator(string label = "Calcul en cours...", string message = "Alyx réfléchit...", string icon = "✏")
    {
        // Réutilisé pour l'indicateur d'écoute vocale (icône/texte différents) afin que
        // "l'IA réfléchit" et "le micro écoute" restent visuellement distincts : sans
        // ça, l'utilisateur ne sait pas s'il doit parler ou attendre une réponse.
        if (_typingContainer != null) return;

        _typingContainer = new StackPanel
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            MaxWidth = 420,
            Margin = new Thickness(0, 0, 0, 10),
            Spacing = 5
        };

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
            Text = label,
            FontFamily = new FontFamily("Monospace"),
            FontSize = 11,
            Foreground = new SolidColorBrush(Color.Parse("#E55934"))
        });

        var outerBox = new Border
        {
            BorderBrush = new SolidColorBrush(Color.Parse("#1A1A1A")),
            BorderThickness = new Thickness(1.5),
            Background = new SolidColorBrush(Color.Parse("#F4F4F2")),
            Padding = new Thickness(15, 12),
            MinWidth = 300
        };

        var content = new StackPanel { Spacing = 10 };

        var topRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
        topRow.Children.Add(new TextBlock
        {
            Text = icon,
            FontSize = 18,
            VerticalAlignment = VerticalAlignment.Center
        });
        topRow.Children.Add(new TextBlock
        {
            Text = message,
            FontSize = 14,
            Foreground = new SolidColorBrush(Color.Parse("#475569")),
            FontStyle = FontStyle.Italic,
            VerticalAlignment = VerticalAlignment.Center
        });
        content.Children.Add(topRow);

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
        ChatScrollViewer.ScrollToEnd();

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
    
    private TextBlock AddStreamingMessage(string sender)
    {
        var (container, textBlock) = CreateMessageContainer(sender, true, false);
        ChatPanel.Children.Add(container);
        ChatScrollViewer.ScrollToEnd();
        return textBlock;
    }
    
    private void AddMessage(string sender, string text, bool isSystem, bool isAction = false)
    {
        var (container, textBlock) = CreateMessageContainer(sender, isSystem, isAction);
        textBlock.Text = text;
        ChatPanel.Children.Add(container);
        ChatScrollViewer.ScrollToEnd();
    }
    
    private void AddActionRequiredMessage(string action, string cible, JsonElement toolCall)
    {
        var container = new Grid
        {
            Margin = new Thickness(0, 0, 0, 10),
            HorizontalAlignment = HorizontalAlignment.Left,
            MaxWidth = 650
        };

        var metadataPanel = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 10,
            Margin = new Thickness(0, 0, 0, 5),
            HorizontalAlignment = HorizontalAlignment.Left
        };
        metadataPanel.Children.Add(new TextBlock
        {
            Text = "SYS.ACTION_REQUIRED",
            FontWeight = FontWeight.Bold,
            FontFamily = new FontFamily("Monospace"),
            FontSize = 11,
            Foreground = new SolidColorBrush(Color.Parse("#E55934"))
        });

        var mainBox = new Border
        {
            BorderBrush = new SolidColorBrush(Color.Parse("#E55934")),
            BorderThickness = new Thickness(1.5),
            Padding = new Thickness(20),
            Background = new SolidColorBrush(Color.Parse("#FAFAF8"))
        };

        var content = new StackPanel { Spacing = 10 };
        content.Children.Add(new TextBlock
        {
            Text = $"Action destructive détectée : {action}",
            FontWeight = FontWeight.Bold,
            Foreground = new SolidColorBrush(Color.Parse("#1A1A1A"))
        });
        content.Children.Add(new TextBlock
        {
            Text = $"Cible : {cible}\nAlyx attend votre validation (Human-in-the-Loop) avant de procéder.",
            TextWrapping = TextWrapping.Wrap
        });
        
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, Margin = new Thickness(0, 10, 0, 0) };
        var btnAccept = new Button { Content = "Autoriser", Background = new SolidColorBrush(Color.Parse("#1A1A1A")), Foreground = Brushes.White, Padding = new Thickness(15,8) };
        var btnReject = new Button { Content = "Refuser", Background = new SolidColorBrush(Color.Parse("#D0D0CE")), Padding = new Thickness(15,8) };
        
        string toolCallJson = toolCall.GetRawText();
        
        btnAccept.Click += async (s, e) => {
            buttons.IsEnabled = false;
            await SendWebSocketMessage(new { type = "permission_granted", tool_call = JsonSerializer.Deserialize<object>(toolCallJson) });
            AddMessage("Vous", "J'autorise l'action.", false);
        };
        
        btnReject.Click += async (s, e) => {
            buttons.IsEnabled = false;
            await SendWebSocketMessage(new { type = "permission_denied", tool_call = JsonSerializer.Deserialize<object>(toolCallJson) });
            AddMessage("Vous", "Je refuse cette action.", false);
        };
        
        buttons.Children.Add(btnAccept);
        buttons.Children.Add(btnReject);
        content.Children.Add(buttons);
        
        mainBox.Child = content;
        
        var finalStack = new StackPanel { Spacing = 5 };
        finalStack.Children.Add(metadataPanel);
        finalStack.Children.Add(mainBox);
        container.Children.Add(finalStack);
        
        ChatPanel.Children.Add(container);
        ChatScrollViewer.ScrollToEnd();
        
        _isProcessing = false;
        SendBtn.Content = "GÉNÉRER ▸";
        SendBtn.IsEnabled = true;
        HideTypingIndicator();
    }

    private void AddMobileInfoMessage(bool allowLan, string? lanIp, int mobilePort, string token)
    {
        var container = new StackPanel
        {
            Margin = new Thickness(0, 0, 0, 10),
            HorizontalAlignment = HorizontalAlignment.Left,
            MaxWidth = 650,
            Spacing = 5
        };

        var metaPanel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
        metaPanel.Children.Add(new TextBlock
        {
            Text = "SYS.MOBILE",
            FontWeight = FontWeight.Bold,
            FontFamily = new FontFamily("Monospace"),
            FontSize = 11,
            Foreground = new SolidColorBrush(Color.Parse("#1A1A1A"))
        });
        container.Children.Add(metaPanel);

        var mainBox = new Border
        {
            BorderBrush = new SolidColorBrush(Color.Parse("#1A1A1A")),
            BorderThickness = new Thickness(1.5),
            Padding = new Thickness(20),
            Background = new SolidColorBrush(Color.Parse("#FAFAF8"))
        };

        var content = new StackPanel { Spacing = 10 };

        if (!allowLan)
        {
            content.Children.Add(new TextBlock
            {
                Text = "L'accès réseau au compagnon mobile est désactivé (allow_lan: false dans config.yaml). Activez-le puis redémarrez Alyx pour connecter un téléphone.",
                TextWrapping = TextWrapping.Wrap
            });
        }
        else if (string.IsNullOrEmpty(lanIp))
        {
            content.Children.Add(new TextBlock
            {
                Text = "Aucune interface réseau locale détectée (Wi-Fi/Ethernet). Connectez le PC au réseau local pour utiliser le compagnon mobile.",
                TextWrapping = TextWrapping.Wrap
            });
        }
        else
        {
            content.Children.Add(new TextBlock
            {
                Text = "Sur le téléphone (même réseau Wi-Fi), ouvrez le compagnon mobile puis saisissez :",
                TextWrapping = TextWrapping.Wrap
            });

            var champ = new Func<string, string, StackPanel>((label, valeur) =>
            {
                var ligne = new StackPanel { Spacing = 2 };
                ligne.Children.Add(new TextBlock { Text = label, FontSize = 10, FontWeight = FontWeight.Bold, Foreground = new SolidColorBrush(Color.Parse("#64748b")) });
                var box = new TextBox
                {
                    Text = valeur,
                    IsReadOnly = true,
                    FontFamily = new FontFamily("Monospace"),
                    FontSize = 13,
                    Background = Brushes.White,
                    BorderBrush = new SolidColorBrush(Color.Parse("#1A1A1A")),
                    BorderThickness = new Thickness(1)
                };
                ligne.Children.Add(box);
                return ligne;
            });

            content.Children.Add(champ("ADRESSE (IP:PORT)", $"{lanIp}:{mobilePort}"));
            content.Children.Add(champ("CODE DE JUMELAGE", token));

            var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, Margin = new Thickness(0, 5, 0, 0) };
            var btnRegen = new Button
            {
                Content = "🔄 Régénérer le code",
                Background = new SolidColorBrush(Color.Parse("#D0D0CE")),
                Padding = new Thickness(15, 8)
            };
            btnRegen.Click += async (s, e) =>
            {
                btnRegen.IsEnabled = false;
                await SendWebSocketMessage(new { type = "regenerate_pairing_token" });
            };
            buttons.Children.Add(btnRegen);
            content.Children.Add(buttons);
        }

        mainBox.Child = content;
        container.Children.Add(mainBox);

        ChatPanel.Children.Add(container);
        ChatScrollViewer.ScrollToEnd();
    }

    private (Grid, TextBlock) CreateMessageContainer(string sender, bool isSystem, bool isAction)
    {
        bool isUser = !isSystem;
        string metaLabel = isUser ? "USER.INPUT" : (isAction ? "SYS.ACTION" : "ALYX.SYS");

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
        
        return (container, textBlock);
    }


    // ========== Events Handlers ==========
    private async void OnModelChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (ModelSelector.SelectedItem is not string selected) return;

        string modelName = selected;
        int bracketEnd = modelName.IndexOf(']');
        if (bracketEnd >= 0)
            modelName = modelName[(bracketEnd + 2)..]; // skip "] "
        int parenStart = modelName.IndexOf(" (");
        if (parenStart >= 0)
            modelName = modelName[..parenStart];
        modelName = modelName.Trim();

        if (modelName == _currentModel) return;

        await SendWebSocketMessage(new { type = "select_model", model = modelName });
    }

    private async void OnRefreshModelsClick(object? sender, RoutedEventArgs e)
    {
        AddMessage("Système", "Actualisation des modèles disponibles...", true, true);
        await SendWebSocketMessage(new { type = "get_models", refresh = true });
    }

    private async void OnMobileInfoClick(object? sender, RoutedEventArgs e)
    {
        await SendWebSocketMessage(new { type = "get_mobile_info" });
    }

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        _ = SendWebSocketMessage(new { type = "shutdown" });
    }

    private async void OnSendClick(object? sender, RoutedEventArgs e)
    {
        await SendChatAsync();
    }

    private async void OnInputKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            await SendChatAsync();
        }
    }

    private async void OnVocalClick(object? sender, RoutedEventArgs e)
    {
        _isVocalActive = !_isVocalActive;
        // Toute bascule manuelle repart d'un compteur propre : un échec ancien ne doit
        // pas s'additionner à des échecs futurs après que l'utilisateur soit intervenu.
        _echecsVocalConsecutifs = 0;
        VocalBtn.Content = _isVocalActive ? "🎤 On" : "🎤 Off";
        VocalBtn.Foreground = new SolidColorBrush(Color.Parse(_isVocalActive ? "#E55934" : "#475569"));
        VocalBtn.BorderBrush = new SolidColorBrush(Color.Parse(_isVocalActive ? "#E55934" : "#94a3b8"));

        if (_isVocalActive)
        {
            AddMessage("Système", "Mode vocal activé (continu). Je vous écoute...", true, true);
            _ = SendChatAsync();
        }
        else
        {
            AddMessage("Système", "Mode vocal désactivé.", true, true);
            if (_isProcessing)
            {
                // Coupe une écoute/génération en cours : sans ça, le clic "Off" ne fait
                // qu'empêcher le PROCHAIN tour, celui en cours continue silencieusement.
                await SendWebSocketMessage(new { type = "cancel" });
            }
        }
    }

    private async void OnStopClick(object? sender, RoutedEventArgs e)
    {
        await SendWebSocketMessage(new { type = "cancel" });
    }

    /// <summary>
    /// Relance automatiquement l'écoute si le mode vocal continu est toujours actif.
    /// Sans ce rebouclage, un seul tour de parole désactivait de fait le micro tout en
    /// laissant le bouton affiché "🎤 On" — c'était ça, le vrai "auto-mute".
    /// </summary>
    private void ContinuerEcouteSiVocalActif()
    {
        if (_isVocalActive && !_isProcessing)
        {
            _ = SendChatAsync();
        }
    }

    private void OnClearChatClick(object? sender, RoutedEventArgs e)
    {
        ChatPanel.Children.Clear();
        AddMessage("Alyx", "Conversation réinitialisée. Comment puis-je vous aider ?", true);
    }

    // ========== Send Logic ==========
    private async Task SendChatAsync()
    {
        if (_isProcessing) return;

        string text = InputBox.Text?.Trim() ?? "";
        bool declencheEcouteVocale = string.IsNullOrEmpty(text) && _isVocalActive;
        if (string.IsNullOrEmpty(text) && !_isVocalActive) return;

        if (!string.IsNullOrEmpty(text))
        {
            AddMessage("Vous", text, false);
            InputBox.Text = "";
        }

        _isProcessing = true;
        SendBtn.Content = "...";
        SendBtn.IsEnabled = false;
        StopBtn.IsVisible = true;

        // Si on part écouter le micro, on laisse le message serveur "listening" afficher
        // l'indicateur dédié (icône micro) plutôt que le "Alyx réfléchit..." générique.
        if (!declencheEcouteVocale)
        {
            ShowTypingIndicator();
        }

        await SendWebSocketMessage(new
        {
            type = "chat",
            prompt = text,
            vocal = _isVocalActive
        });
    }
}