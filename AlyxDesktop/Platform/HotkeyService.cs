using Avalonia.Threading;
using System;
using System.Runtime.InteropServices;
using System.Threading;

namespace AlyxDesktop.Platform;

/// <summary>Raccourci global Alt+J (Windows : RegisterHotKey sur un thread dédié à la boucle de messages).</summary>
public sealed class HotkeyService : IDisposable
{
    private const int HotkeyId = 0xA1;
    private const uint ModAlt = 0x0001, ModNoRepeat = 0x4000, VkJ = 0x4A;
    private const uint WmHotkey = 0x0312, WmQuit = 0x0012;

    [StructLayout(LayoutKind.Sequential)]
    private struct MSG
    {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public int ptX, ptY;
    }

    [DllImport("user32.dll", SetLastError = true)] private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint modifiers, uint vk);
    [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")] private static extern int GetMessage(out MSG msg, IntPtr hWnd, uint min, uint max);
    [DllImport("user32.dll")] private static extern bool PostThreadMessage(uint threadId, uint msg, UIntPtr wParam, IntPtr lParam);
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();

    private uint _threadId;

    public event Action? Pressed;

    /// <summary>Enregistre Alt+J. false si non supporté (Linux) ou déjà pris par une autre application.</summary>
    public bool Start()
    {
        if (!OperatingSystem.IsWindows()) return false;
        bool ok = false;
        using var ready = new ManualResetEventSlim();
        var thread = new Thread(() =>
        {
            _threadId = GetCurrentThreadId();
            ok = RegisterHotKey(IntPtr.Zero, HotkeyId, ModAlt | ModNoRepeat, VkJ);
            ready.Set();
            if (!ok) return;
            while (GetMessage(out var msg, IntPtr.Zero, 0, 0) > 0)
            {
                if (msg.message == WmHotkey)
                    Dispatcher.UIThread.Post(() => Pressed?.Invoke());
            }
            UnregisterHotKey(IntPtr.Zero, HotkeyId);
        })
        { IsBackground = true, Name = "AlyxHotkey" };
        thread.Start();
        ready.Wait(2000);
        return ok;
    }

    public void Dispose()
    {
        if (_threadId != 0) PostThreadMessage(_threadId, WmQuit, UIntPtr.Zero, IntPtr.Zero);
    }
}
