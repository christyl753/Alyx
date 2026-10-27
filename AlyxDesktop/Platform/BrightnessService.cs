using System;
using System.Threading.Tasks;

namespace AlyxDesktop.Platform;

/// <summary>Luminosité de l'écran intégré : WMI (Windows) ou brightnessctl (Linux). null = non pris en charge.</summary>
public static class BrightnessService
{
    public static async Task<int?> GetAsync()
    {
#if WINDOWS
        return await Task.Run<int?>(() =>
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(@"root\WMI", "SELECT CurrentBrightness FROM WmiMonitorBrightness");
                foreach (System.Management.ManagementObject o in searcher.Get())
                    return Convert.ToInt32(o["CurrentBrightness"]);
            }
            catch (Exception)
            {
                // Écran externe ou pilote sans WMI : non pris en charge
            }
            return null;
        });
#else
        var output = await Shell.RunAsync("brightnessctl", "-m"); // "intel_backlight,backlight,400,40%,1000"
        var parts = output?.Split(',');
        return parts is { Length: >= 4 } && int.TryParse(parts[3].TrimEnd('%'), out var p) ? p : null;
#endif
    }

    public static async Task SetAsync(int percent)
    {
        percent = Math.Clamp(percent, 0, 100);
#if WINDOWS
        await Task.Run(() =>
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(@"root\WMI", "SELECT * FROM WmiMonitorBrightnessMethods");
                foreach (System.Management.ManagementObject o in searcher.Get())
                    o.InvokeMethod("WmiSetBrightness", new object[] { (uint)1, (byte)percent });
            }
            catch (Exception)
            {
                // Non pris en charge
            }
        });
#else
        await Shell.RunAsync("brightnessctl", "set", $"{percent}%");
#endif
    }
}
