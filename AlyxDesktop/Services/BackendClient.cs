using Avalonia.Threading;
using System;
using System.Diagnostics;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AlyxDesktop.Services;

/// <summary>Connexion WebSocket au backend Python (api.py), reconnexion automatique.</summary>
public sealed class BackendClient
{
    private readonly Uri _uri;
    private ClientWebSocket _socket = new();
    // ClientWebSocket n'autorise qu'un seul SendAsync à la fois
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private bool _running;

    /// <summary>Message reçu (type, racine JSON), toujours levé sur le thread UI.</summary>
    public event Action<string, JsonElement>? MessageReceived;
    /// <summary>true = connecté, false = déconnecté. Levé sur le thread UI.</summary>
    public event Action<bool>? ConnectionChanged;

    public bool IsConnected => _socket.State == WebSocketState.Open;

    public BackendClient(int port = 8765) => _uri = new Uri($"ws://127.0.0.1:{port}");

    public void Start()
    {
        if (_running) return;
        _running = true;
        _ = Task.Run(RunAsync);
    }

    private async Task RunAsync()
    {
        while (_running)
        {
            try
            {
                _socket.Dispose();
                _socket = new ClientWebSocket();
                await _socket.ConnectAsync(_uri, CancellationToken.None);
                Dispatcher.UIThread.Post(() => ConnectionChanged?.Invoke(true));
                await ReceiveLoopAsync(_socket);
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"WebSocket: {ex.Message}");
            }
            Dispatcher.UIThread.Post(() => ConnectionChanged?.Invoke(false));
            if (_running) await Task.Delay(2000);
        }
    }

    private async Task ReceiveLoopAsync(ClientWebSocket socket)
    {
        var buffer = new byte[16384];
        var sb = new StringBuilder();
        while (socket.State == WebSocketState.Open)
        {
            var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), CancellationToken.None);
            if (result.MessageType == WebSocketMessageType.Close) break;
            sb.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
            if (!result.EndOfMessage) continue;

            string json = sb.ToString();
            sb.Clear();
            try
            {
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement.Clone();
                string type = root.TryGetProperty("type", out var t) ? t.GetString() ?? "" : "";
                Dispatcher.UIThread.Post(() => MessageReceived?.Invoke(type, root));
            }
            catch (JsonException ex)
            {
                Debug.WriteLine($"JSON invalide: {ex.Message}");
            }
        }
    }

    public async Task SendAsync(object payload)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload));
        await _sendLock.WaitAsync();
        try
        {
            if (_socket.State == WebSocketState.Open)
                await _socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, CancellationToken.None);
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Erreur d'envoi WebSocket: {ex.Message}");
        }
        finally
        {
            _sendLock.Release();
        }
    }

    /// <summary>Envoi bloquant borné (fermeture de l'application).</summary>
    public void SendBlocking(object payload, TimeSpan timeout)
    {
        _running = false;
        Task.Run(() => SendAsync(payload)).Wait(timeout);
    }
}
