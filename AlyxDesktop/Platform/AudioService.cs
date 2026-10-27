using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

namespace AlyxDesktop.Platform;

/// <summary>Volume principal : Core Audio (Windows) ou wpctl / pactl (Linux). Valeurs 0-100.</summary>
public static class AudioService
{
#if WINDOWS
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class MMDeviceEnumerator { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator
    {
        int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
        int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice
    {
        int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object iface);
    }

    [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioEndpointVolume
    {
        int RegisterControlChangeNotify(IntPtr notify);
        int UnregisterControlChangeNotify(IntPtr notify);
        int GetChannelCount(out uint count);
        int SetMasterVolumeLevel(float levelDb, ref Guid context);
        int SetMasterVolumeLevelScalar(float level, ref Guid context);
        int GetMasterVolumeLevel(out float levelDb);
        int GetMasterVolumeLevelScalar(out float level);
    }

    private static IAudioEndpointVolume? Endpoint()
    {
        try
        {
            var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumerator();
            if (enumerator.GetDefaultAudioEndpoint(0 /* eRender */, 1 /* eMultimedia */, out var device) != 0) return null;
            var iid = typeof(IAudioEndpointVolume).GUID;
            if (device.Activate(ref iid, 1 /* CLSCTX_INPROC_SERVER */, IntPtr.Zero, out var obj) != 0) return null;
            return (IAudioEndpointVolume)obj;
        }
        catch (COMException)
        {
            return null;
        }
    }
#endif

    public static async Task<int?> GetVolumeAsync()
    {
#if WINDOWS
        return await Task.Run<int?>(() =>
        {
            var ep = Endpoint();
            return ep != null && ep.GetMasterVolumeLevelScalar(out float v) == 0 ? (int)Math.Round(v * 100) : null;
        });
#else
        var wp = await Shell.RunAsync("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"); // "Volume: 0.62"
        if (wp != null && double.TryParse(wp.Replace("Volume:", "").Split(' ', StringSplitOptions.RemoveEmptyEntries)[0],
                NumberStyles.Float, CultureInfo.InvariantCulture, out var v))
            return (int)Math.Round(v * 100);
        var pa = await Shell.RunAsync("pactl", "get-sink-volume", "@DEFAULT_SINK@"); // "... / 62% / ..."
        if (pa != null)
        {
            int i = pa.IndexOf('%');
            if (i > 0)
            {
                int j = i - 1;
                while (j >= 0 && char.IsDigit(pa[j])) j--;
                if (int.TryParse(pa[(j + 1)..i], out var p)) return p;
            }
        }
        return null;
#endif
    }

    public static async Task SetVolumeAsync(int percent)
    {
        percent = Math.Clamp(percent, 0, 100);
#if WINDOWS
        await Task.Run(() =>
        {
            var guid = Guid.Empty;
            Endpoint()?.SetMasterVolumeLevelScalar(percent / 100f, ref guid);
        });
#else
        if (await Shell.RunAsync("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", (percent / 100.0).ToString("0.00", CultureInfo.InvariantCulture)) == null)
            await Shell.RunAsync("pactl", "set-sink-volume", "@DEFAULT_SINK@", $"{percent}%");
#endif
    }
}
