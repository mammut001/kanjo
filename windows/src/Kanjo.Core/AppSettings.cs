using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Kanjo.Core;

/// <summary>
/// 应用设置存储：`%APPDATA%\Kanjo\settings.json`，键名与 Mac 版 <see cref="SettingsKeys"/> 一致。
/// `--defaults-suite &lt;name&gt;` / `KANJO_DEFAULTS_SUITE` 会改用同目录下的 `settings-&lt;name&gt;.json`（测试隔离用）。
/// 目录可注入，测试永远不碰用户真实设置。
/// </summary>
public sealed class AppSettings : ILanguageSettings
{
    public const string PreviewSuiteName = "kanjo-preview";

    private readonly object _lock = new();
    private Dictionary<string, JsonNode?> _values = new(StringComparer.Ordinal);
    private readonly string? _path;

    public string? FilePath => _path;

    /// <summary>不落盘的存储（测试 / 纯内存用）。</summary>
    public static AppSettings InMemory() => new(null, new Dictionary<string, JsonNode?>(StringComparer.Ordinal));

    public AppSettings(string? path)
    {
        _path = path;
        Load();
    }

    internal AppSettings(string? path, Dictionary<string, JsonNode?> seed)
    {
        _path = path;
        _values = seed;
    }

    /// <summary>
    /// 默认设置目录：Windows 是 `%APPDATA%\Kanjo`（见 <see cref="AppPaths.SettingsDirectoryName"/>）；
    /// 其它平台用 XDG 配置目录下的 `kanjo`（小写），和以前一样，免得开发机上已有的设置被孤立。
    /// </summary>
    public static string DefaultDirectory()
    {
        var appData = Environment.GetEnvironmentVariable("APPDATA");
        if (!string.IsNullOrEmpty(appData)) return Path.Combine(appData, AppPaths.SettingsDirectoryName);
        var xdg = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
        if (!string.IsNullOrEmpty(xdg)) return Path.Combine(xdg, "kanjo");
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config", "kanjo");
    }

    public static string FileNameForSuite(string? suite) =>
        string.IsNullOrEmpty(suite) ? "settings.json" : $"settings-{suite}.json";

    public static string FilePathFor(string directory, string? suite) =>
        Path.Combine(directory, FileNameForSuite(suite));

    /// <summary>按参数 / 环境变量算出应该用哪个 suite；和 Mac 版顺序一致。</summary>
    public static string? SuiteName(IReadOnlyList<string> arguments, IReadOnlyDictionary<string, string> environment)
    {
        for (var i = 0; i < arguments.Count; i++)
        {
            var arg = arguments[i];
            if (arg == "--defaults-suite")
            {
                if (i + 1 < arguments.Count)
                {
                    var val = arguments[i + 1].Trim();
                    if (val.Length > 0) return val;
                }
            }
            else if (arg.StartsWith("--defaults-suite=", StringComparison.Ordinal))
            {
                var val = arg["--defaults-suite=".Length..].Trim();
                if (val.Length > 0) return val;
            }
        }
        if (environment.TryGetValue("KANJO_DEFAULTS_SUITE", out var env) && env.Trim() is { Length: > 0 } trimmed)
        {
            return trimmed;
        }
        if (arguments.Contains("--window") ||
            arguments.Contains("--snapshot") ||
            arguments.Any(a => a.StartsWith("--snapshot=", StringComparison.Ordinal)))
        {
            return PreviewSuiteName;
        }
        return null;
    }

    /// <summary>按参数 / 环境变量 / 目录创建存储。目录留空时用 <see cref="DefaultDirectory"/>。</summary>
    public static AppSettings ForLaunch(
        IReadOnlyList<string>? arguments = null,
        IReadOnlyDictionary<string, string>? environment = null,
        string? directory = null)
    {
        var args = arguments ?? Environment.GetCommandLineArgs();
        var env = environment ?? ReadEnvironment();
        var suite = SuiteName(args, env);
        var dir = directory ?? DefaultDirectory();
        return new AppSettings(FilePathFor(dir, suite));
    }

    public static Dictionary<string, string> ReadEnvironment()
    {
        var dict = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (System.Collections.DictionaryEntry e in Environment.GetEnvironmentVariables())
        {
            if (e.Key is string k && e.Value is string v) dict[k] = v;
        }
        return dict;
    }

    private void Load()
    {
        if (_path is null || !File.Exists(_path)) return;
        try
        {
            var text = File.ReadAllText(_path);
            if (JsonNode.Parse(text) is JsonObject obj)
            {
                var values = new Dictionary<string, JsonNode?>(StringComparer.Ordinal);
                foreach (var (key, value) in obj)
                {
                    values[key] = value?.DeepClone();
                }
                _values = values;
            }
        }
        catch (Exception)
        {
            // 读不出来的设置文件按空处理：CLI / UI 仍能用默认值工作。
        }
    }

    private void Save()
    {
        if (_path is null) return;
        try
        {
            var dir = Path.GetDirectoryName(_path);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            var obj = new JsonObject();
            string[] keys;
            lock (_lock) keys = _values.Keys.ToArray();
            foreach (var key in keys)
            {
                JsonNode? value;
                lock (_lock) value = _values.TryGetValue(key, out var v) ? v : null;
                obj[key] = value?.DeepClone();
            }
            File.WriteAllText(_path, obj.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        }
        catch (Exception)
        {
            // 设置不可写不影响内存中的值。
        }
    }

    // MARK: - 读取

    public JsonNode? Raw(string key)
    {
        lock (_lock)
        {
            return _values.TryGetValue(key, out var value) ? value?.DeepClone() : null;
        }
    }

    public bool Has(string key)
    {
        lock (_lock)
        {
            return _values.ContainsKey(key);
        }
    }

    public string? GetString(string key)
    {
        lock (_lock)
        {
            if (!_values.TryGetValue(key, out var node) || node is null) return null;
            return node is JsonValue v && v.TryGetValue<string>(out var s) ? s : node.ToJsonString();
        }
    }

    public int? GetInt(string key)
    {
        lock (_lock)
        {
            if (!_values.TryGetValue(key, out var node) || node is null) return null;
            if (node is not JsonValue v) return null;
            if (v.TryGetValue<int>(out var i)) return i;
            if (v.TryGetValue<long>(out var l) && l is >= int.MinValue and <= int.MaxValue) return (int)l;
            if (v.TryGetValue<double>(out var d) && Math.Abs(d - Math.Round(d)) < 1e-9) return (int)Math.Round(d);
            if (v.TryGetValue<string>(out var s) &&
                int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed)) return parsed;
            return null;
        }
    }

    public double? GetDouble(string key)
    {
        lock (_lock)
        {
            if (!_values.TryGetValue(key, out var node) || node is null) return null;
            if (node is not JsonValue v) return null;
            if (v.TryGetValue<double>(out var d)) return d;
            if (v.TryGetValue<string>(out var s) &&
                double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed)) return parsed;
            return null;
        }
    }

    public bool GetBool(string key)
    {
        lock (_lock)
        {
            if (!_values.TryGetValue(key, out var node) || node is null) return false;
            if (node is not JsonValue v) return false;
            if (v.TryGetValue<bool>(out var b)) return b;
            if (v.TryGetValue<int>(out var i)) return i != 0;
            if (v.TryGetValue<string>(out var s)) return s is "true" or "1" or "yes";
            return false;
        }
    }

    /// <summary>带默认值的字符串读取。</summary>
    public string Str(string key, string fallback) => GetString(key) ?? fallback;

    public int Int(string key, int fallback) => GetInt(key) ?? fallback;

    public double Dbl(string key, double fallback) => GetDouble(key) ?? fallback;

    public bool Bool(string key, bool fallback) => Has(key) ? GetBool(key) : fallback;

    // MARK: - 写入

    public void Set(string key, string? value)
    {
        lock (_lock)
        {
            if (value is null) _values.Remove(key);
            else _values[key] = JsonValue.Create(value);
        }
        Save();
    }

    public void Set(string key, int value) => SetNode(key, JsonValue.Create(value));

    public void Set(string key, long value) => SetNode(key, JsonValue.Create(value));

    public void Set(string key, double value) => SetNode(key, JsonValue.Create(value));

    public void Set(string key, bool value) => SetNode(key, JsonValue.Create(value));

    private void SetNode(string key, JsonNode? node)
    {
        lock (_lock)
        {
            _values[key] = node;
        }
        Save();
    }

    public void Remove(string key)
    {
        lock (_lock)
        {
            _values.Remove(key);
        }
        Save();
    }

    /// <summary>写入时间戳（macOS 版存成 Date；JSON 里存 ISO 8601 字符串）。</summary>
    public void SetDate(string key, DateTimeOffset value) =>
        Set(key, value.UtcDateTime.ToString("o", CultureInfo.InvariantCulture));

    public DateTimeOffset? GetDate(string key) => ReportDates.ParseTimestamp(GetString(key));
}
