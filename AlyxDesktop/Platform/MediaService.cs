using Avalonia.Media.Imaging;
using System;
using System.Globalization;
using System.IO;
using System.Threading.Tasks;

namespace AlyxDesktop.Platform;

public sealed record MediaState(bool HasSession, string Title, string Artist, double PositionSec, double DurationSec, bool Playing);

/// <summary>
/// Lecture multimédia en cours : contrôles média système de Windows (SMTC, WinRT) ou playerctl / MPRIS (Linux).
/// </summary>
public sealed class MediaService
{
    public static readonly MediaState None = new(false, "Aucun média", "", 0, 0, false);

    private string _artKey = "";
    public Bitmap? Artwork { get; private set; }

#if WINDOWS
    private Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager? _manager;

    private async Task<Windows.Media.Control.GlobalSystemMediaTransportControlsSession?> SessionAsync()
    {
        try
        {
            _manager ??= await Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
            return _manager.GetCurrentSession();
        }
        catch (Exception)
        {
            return null;
        }
    }
#endif

    public async Task<MediaState> GetStateAsync()
    {
#if WINDOWS
        var session = await SessionAsync();
        if (session == null) { Artwork = null; _artKey = ""; return None; }
        try
        {
            var props = await session.TryGetMediaPropertiesAsync();
            var timeline = session.GetTimelineProperties();
            bool playing = session.GetPlaybackInfo().PlaybackStatus ==
                           Windows.Media.Control.GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing;
            double pos = timeline.Position.TotalSeconds;
            // La position n'est publiée que ponctuellement par le lecteur : on l'extrapole
            if (playing && timeline.LastUpdatedTime.Year > 2000)
                pos += (DateTimeOffset.Now - timeline.LastUpdatedTime).TotalSeconds;
            double duration = (timeline.EndTime - timeline.StartTime).TotalSeconds;

            string key = props.Title + "|" + props.Artist;
            if (key != _artKey)
            {
                _artKey = key;
                Artwork = null;
                if (props.Thumbnail != null)
                {
                    try
                    {
                        using var stream = await props.Thumbnail.OpenReadAsync();
                        using var net = stream.AsStreamForRead();
                        var copy = new MemoryStream();
                        await net.CopyToAsync(copy);
                        copy.Position = 0;
                        Artwork = Bitmap.DecodeToWidth(copy, 96);
                    }
                    catch (Exception) { }
                }
            }
            return new MediaState(true, string.IsNullOrEmpty(props.Title) ? "Lecture en cours" : props.Title,
                                  props.Artist ?? "", Math.Max(0, duration > 0 ? Math.Min(pos, duration) : pos), Math.Max(0, duration), playing);
        }
        catch (Exception)
        {
            return None;
        }
#else
        var output = await Shell.RunAsync("playerctl", "metadata", "--format",
            "{{status}}\t{{title}}\t{{artist}}\t{{position}}\t{{mpris:length}}");
        if (string.IsNullOrEmpty(output)) return None;
        var p = output.Split('\t');
        if (p.Length < 5) return None;
        double.TryParse(p[3], NumberStyles.Float, CultureInfo.InvariantCulture, out var posUs);
        double.TryParse(p[4], NumberStyles.Float, CultureInfo.InvariantCulture, out var lenUs);
        return new MediaState(true, string.IsNullOrEmpty(p[1]) ? "Lecture en cours" : p[1], p[2], posUs / 1e6, lenUs / 1e6, p[0] == "Playing");
#endif
    }

    public async Task TogglePlayPauseAsync()
    {
#if WINDOWS
        var s = await SessionAsync();
        if (s != null) try { await s.TryTogglePlayPauseAsync(); } catch (Exception) { }
#else
        await Shell.RunAsync("playerctl", "play-pause");
#endif
    }

    public async Task NextAsync()
    {
#if WINDOWS
        var s = await SessionAsync();
        if (s != null) try { await s.TrySkipNextAsync(); } catch (Exception) { }
#else
        await Shell.RunAsync("playerctl", "next");
#endif
    }

    public async Task PreviousAsync()
    {
#if WINDOWS
        var s = await SessionAsync();
        if (s != null) try { await s.TrySkipPreviousAsync(); } catch (Exception) { }
#else
        await Shell.RunAsync("playerctl", "previous");
#endif
    }
}
