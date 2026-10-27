using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace AlyxDesktop.Platform;

public enum QuickToggle { Wifi, Bluetooth, Focus, NightLight, Airplane, BatterySaver }

/// <summary>État d'une tuile : On = activé ; Controllable = basculable directement (sinon ouvre les paramètres).</summary>
public record ToggleState(bool On, bool Controllable, bool Known);

/// <summary>
/// Réglages rapides. Windows : radios Wi-Fi/Bluetooth via WinRT ; Concentration, Éclairage nocturne et
/// Économiseur n'ont pas d'API publique de bascule, on ouvre la page des Paramètres correspondante.
/// Linux : nmcli, rfkill, gsettings (GNOME), powerprofilesctl.
/// </summary>
public static class QuickSettingsService
{
#if WINDOWS
    private static bool _accessRequested;

    private static async Task<IReadOnlyList<Windows.Devices.Radios.Radio>> RadiosAsync()
    {
        if (!_accessRequested)
        {
            _accessRequested = true;
            try { await Windows.Devices.Radios.Radio.RequestAccessAsync(); } catch (Exception) { }
        }
        try { return (await Windows.Devices.Radios.Radio.GetRadiosAsync()).ToList(); }
        catch (Exception) { return Array.Empty<Windows.Devices.Radios.Radio>(); }
    }

    private static bool IsOn(IEnumerable<Windows.Devices.Radios.Radio> radios, Windows.Devices.Radios.RadioKind kind) =>
        radios.Any(r => r.Kind == kind && r.State == Windows.Devices.Radios.RadioState.On);
#endif

    public static async Task<Dictionary<QuickToggle, ToggleState>> GetStatesAsync()
    {
        var states = new Dictionary<QuickToggle, ToggleState>();
#if WINDOWS
        var radios = await RadiosAsync();
        bool hasWifi = radios.Any(r => r.Kind == Windows.Devices.Radios.RadioKind.WiFi);
        bool hasBt = radios.Any(r => r.Kind == Windows.Devices.Radios.RadioKind.Bluetooth);
        bool wifi = IsOn(radios, Windows.Devices.Radios.RadioKind.WiFi);
        bool bt = IsOn(radios, Windows.Devices.Radios.RadioKind.Bluetooth);
        states[QuickToggle.Wifi] = new(wifi, hasWifi, hasWifi);
        states[QuickToggle.Bluetooth] = new(bt, hasBt, hasBt);
        states[QuickToggle.Airplane] = new(radios.Count > 0 && radios.All(r => r.State != Windows.Devices.Radios.RadioState.On), radios.Count > 0, radios.Count > 0);
        bool saver = false;
        try { saver = Windows.System.Power.PowerManager.EnergySaverStatus == Windows.System.Power.EnergySaverStatus.On; } catch (Exception) { }
        states[QuickToggle.BatterySaver] = new(saver, false, true);
        states[QuickToggle.Focus] = new(false, false, false);
        states[QuickToggle.NightLight] = new(false, false, false);
#else
        var wifi = await Shell.RunAsync("nmcli", "radio", "wifi");
        states[QuickToggle.Wifi] = new(wifi == "enabled", wifi != null, wifi != null);
        var bt = await Shell.RunAsync("rfkill", "list", "bluetooth");
        bool btKnown = !string.IsNullOrEmpty(bt);
        bool btOn = btKnown && !bt!.Contains("Soft blocked: yes");
        states[QuickToggle.Bluetooth] = new(btOn, btKnown, btKnown);
        states[QuickToggle.Airplane] = new(wifi == "disabled" && (!btKnown || !btOn), wifi != null, wifi != null);
        var night = await Shell.RunAsync("gsettings", "get", "org.gnome.settings-daemon.plugins.color", "night-light-enabled");
        states[QuickToggle.NightLight] = new(night == "true", night != null, night != null);
        var banners = await Shell.RunAsync("gsettings", "get", "org.gnome.desktop.notifications", "show-banners");
        states[QuickToggle.Focus] = new(banners == "false", banners != null, banners != null);
        var profile = await Shell.RunAsync("powerprofilesctl", "get");
        states[QuickToggle.BatterySaver] = new(profile == "power-saver", profile != null, profile != null);
#endif
        return states;
    }

    /// <summary>Bascule la tuile, ou ouvre la page de paramètres si elle n'est pas pilotable.</summary>
    public static async Task ToggleAsync(QuickToggle toggle, ToggleState current)
    {
        bool target = !current.On;
#if WINDOWS
        switch (toggle)
        {
            case QuickToggle.Wifi:
            case QuickToggle.Bluetooth:
            case QuickToggle.Airplane:
                var radios = await RadiosAsync();
                foreach (var r in radios)
                {
                    bool concerned = toggle == QuickToggle.Airplane
                        || (toggle == QuickToggle.Wifi && r.Kind == Windows.Devices.Radios.RadioKind.WiFi)
                        || (toggle == QuickToggle.Bluetooth && r.Kind == Windows.Devices.Radios.RadioKind.Bluetooth);
                    if (!concerned) continue;
                    // Mode avion activé = toutes les radios éteintes
                    bool on = toggle == QuickToggle.Airplane ? !target : target;
                    try { await r.SetStateAsync(on ? Windows.Devices.Radios.RadioState.On : Windows.Devices.Radios.RadioState.Off); }
                    catch (Exception) { }
                }
                break;
            case QuickToggle.Focus: Shell.OpenUri("ms-settings:quiethours"); break;
            case QuickToggle.NightLight: Shell.OpenUri("ms-settings:nightlight"); break;
            case QuickToggle.BatterySaver: Shell.OpenUri("ms-settings:batterysaver"); break;
        }
#else
        switch (toggle)
        {
            case QuickToggle.Wifi: await Shell.RunAsync("nmcli", "radio", "wifi", target ? "on" : "off"); break;
            case QuickToggle.Bluetooth: await Shell.RunAsync("rfkill", target ? "unblock" : "block", "bluetooth"); break;
            case QuickToggle.Airplane: await Shell.RunAsync("rfkill", target ? "block" : "unblock", "all"); break;
            case QuickToggle.NightLight:
                await Shell.RunAsync("gsettings", "set", "org.gnome.settings-daemon.plugins.color", "night-light-enabled", target ? "true" : "false"); break;
            case QuickToggle.Focus:
                await Shell.RunAsync("gsettings", "set", "org.gnome.desktop.notifications", "show-banners", target ? "false" : "true"); break;
            case QuickToggle.BatterySaver: await Shell.RunAsync("powerprofilesctl", "set", target ? "power-saver" : "balanced"); break;
        }
#endif
    }
}
