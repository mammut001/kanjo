using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Kanjo.Core;

public interface ILanguageSettings
{
    string? GetString(string key);
}

/// <summary>
/// 本地化：直接解析 Mac 版 `ui/Sources/KanjoCore/Resources/{en,zh-Hans,fr}.lproj/Localizable.strings`。
/// 与 Swift 版同一套查找顺序：先当前语言，再回退英文，都没有就返回 key 本身。
/// 语言可以在运行时切换：<see cref="Store"/> 变化后 <see cref="CurrentLanguage"/> 立即生效。
/// </summary>
public static class L10n
{
    public static readonly string[] SupportedLanguages = ["en", "zh-Hans", "fr"];
    public const string DefaultLanguage = "en";

    private static readonly object CacheLock = new();
    private static readonly Dictionary<string, IReadOnlyDictionary<string, string>> Cache = new(StringComparer.Ordinal);

    /// <summary>语言偏好的来源（默认读应用设置）。测试可替换成隔离的临时设置。</summary>
    public static ILanguageSettings? Store { get; set; }

    /// <summary>资源根目录：构建输出里的 Resources/ 或仓库里的 ui/Sources/KanjoCore/Resources。</summary>
    public static string? ResourcesRoot { get; set; }

    public static string CurrentLanguage => EffectiveLanguage(Store?.GetString(SettingsKeys.AppLanguage));

    /// <summary>规范化语言标识符：去空白、小写、下划线换成连字符，去掉 .lproj 后缀。</summary>
    public static string NormalizeLanguage(string code)
    {
        var name = code;
        var slash = name.LastIndexOfAny(['/', '\\']);
        if (slash >= 0) name = name[(slash + 1)..];
        if (name.EndsWith(".lproj", StringComparison.OrdinalIgnoreCase))
        {
            name = name[..^".lproj".Length];
        }
        return name.Trim().ToLowerInvariant().Replace('_', '-');
    }

    /// <summary>在候选目录名或语言标识符列表中查找匹配项（忽略大小写，规范化 '-' 与 '_'）。</summary>
    public static string? MatchLproj(string language, IReadOnlyList<string> candidates)
    {
        var trimmedLang = language.Trim();
        if (trimmedLang.Length == 0) return null;
        var target = NormalizeLanguage(trimmedLang);
        if (target.Length == 0) return null;

        // 1. 完全匹配（带或不带 .lproj 后缀）
        foreach (var candidate in candidates)
        {
            if (candidate == trimmedLang + ".lproj" || candidate == trimmedLang) return candidate;
        }

        // 2. 忽略大小写匹配
        var lowercasedLang = trimmedLang.ToLowerInvariant();
        foreach (var candidate in candidates)
        {
            var lower = candidate.ToLowerInvariant();
            if (lower == lowercasedLang + ".lproj" || lower == lowercasedLang) return candidate;
        }

        // 3. 规范化 '-' 与 '_' 后的匹配
        foreach (var candidate in candidates)
        {
            if (NormalizeLanguage(candidate) == target) return candidate;
        }
        return null;
    }

    public static string? MatchLprojDirectory(string language, IReadOnlyList<string> candidates) =>
        MatchLproj(language, candidates);

    /// <summary>某一语言的 .lproj 目录，找不到时按规范化名字再找一遍。</summary>
    public static string? LprojDirectory(string language)
    {
        var trimmed = language.Trim();
        if (trimmed.Length == 0) return null;
        var root = ResolveResourcesRoot();
        if (root is null) return null;
        if (!Directory.Exists(root)) return null;
        var entries = Directory.GetDirectories(root)
            .Select(Path.GetFileName)
            .Where(n => n is not null && n.EndsWith(".lproj", StringComparison.OrdinalIgnoreCase))
            .Select(n => n!)
            .ToList();
        if (entries.Count == 0) return null;
        var matched = MatchLproj(trimmed, entries);
        return matched is null ? null : Path.Combine(root, matched);
    }

    /// <summary>读取某一语言 .strings 文件中的所有键值（供测试验证完整性）。</summary>
    public static IReadOnlyDictionary<string, string>? AllStrings(string language)
    {
        var dir = LprojDirectory(language);
        if (dir is null) return null;
        var file = Path.Combine(dir, "Localizable.strings");
        if (!File.Exists(file)) return null;
        return ParseStringsFile(File.ReadAllText(file, Encoding.UTF8));
    }

    /// <summary>
    /// 解析 .strings 文件（OpenStep 风格 plist）：`"key" = "value";`，支持 // 与 /* */ 注释、转义、末尾缺分号。
    /// </summary>
    public static Dictionary<string, string> ParseStringsFile(string content)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        var i = 0;
        while (i < content.Length)
        {
            SkipTrivia(content, ref i);
            if (i >= content.Length) break;
            if (content[i] != '"') break;
            var key = ReadQuoted(content, ref i);
            SkipTrivia(content, ref i);
            if (i >= content.Length || content[i] != '=') break;
            i++;
            SkipTrivia(content, ref i);
            if (i >= content.Length || content[i] != '"') break;
            var value = ReadQuoted(content, ref i);
            SkipTrivia(content, ref i);
            if (i < content.Length && content[i] == ';') i++;
            result[key] = value;
        }
        return result;
    }

    private static void SkipTrivia(string s, ref int i)
    {
        while (i < s.Length)
        {
            var c = s[i];
            if (char.IsWhiteSpace(c) || c == '\uFEFF')
            {
                i++;
                continue;
            }
            if (c == '/' && i + 1 < s.Length && s[i + 1] == '/')
            {
                while (i < s.Length && s[i] != '\n') i++;
                continue;
            }
            if (c == '/' && i + 1 < s.Length && s[i + 1] == '*')
            {
                i += 2;
                while (i + 1 < s.Length && !(s[i] == '*' && s[i + 1] == '/')) i++;
                i = Math.Min(i + 2, s.Length);
                continue;
            }
            break;
        }
    }

    private static string ReadQuoted(string s, ref int i)
    {
        // 调用方保证 s[i] == '"'
        i++;
        var sb = new StringBuilder();
        while (i < s.Length)
        {
            var c = s[i];
            if (c == '\\' && i + 1 < s.Length)
            {
                var n = s[i + 1];
                i += 2;
                switch (n)
                {
                    case 'n': sb.Append('\n'); break;
                    case 't': sb.Append('\t'); break;
                    case 'r': sb.Append('\r'); break;
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '\'': sb.Append('\''); break;
                    case 'u':
                        if (i + 4 <= s.Length &&
                            int.TryParse(s.AsSpan(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var code))
                        {
                            sb.Append((char)code);
                            i += 4;
                        }
                        break;
                    default: sb.Append(n); break;
                }
                continue;
            }
            if (c == '"')
            {
                i++;
                break;
            }
            sb.Append(c);
            i++;
        }
        return sb.ToString();
    }

    /// <summary>根据用户设置项（或系统语言回退）计算出的有效语言代码。</summary>
    public static string EffectiveLanguage(string? preference)
    {
        if (!string.IsNullOrEmpty(preference) && preference != AppLanguage.System.RawValue())
        {
            var exact = SupportedLanguages.FirstOrDefault(l => l == preference);
            if (exact is not null) return exact;
            var normalized = NormalizeLanguage(preference);
            var matched = SupportedLanguages.FirstOrDefault(l => NormalizeLanguage(l) == normalized);
            if (matched is not null) return matched;
        }
        return SystemLanguage;
    }

    /// <summary>匹配系统语言到我们支持的语言，未命中时回退到默认语言 "en"。</summary>
    public static string SystemLanguage
    {
        get
        {
            var name = CultureInfo.CurrentUICulture.Name;
            if (name.StartsWith("zh", StringComparison.OrdinalIgnoreCase)) return "zh-Hans";
            if (name.StartsWith("fr", StringComparison.OrdinalIgnoreCase)) return "fr";
            return DefaultLanguage;
        }
    }

    /// <summary>翻译指定 key（按当前选中语言）；失败时回退到 en，若仍未命中则返回 key 本身。</summary>
    public static string Tr(string key, params object?[] args)
    {
        var format = TrLanguage(key, null);
        if (args.Length == 0) return format;
        return Format(format, args);
    }

    /// <summary>翻译指定 key，并显式指定语言（避免与「key + 参数」的重载混淆）。</summary>
    public static string TrL(string? language, string key, params object?[] args)
    {
        var format = TrLanguage(key, language);
        if (args.Length == 0) return format;
        return Format(format, args);
    }

    private static string TrLanguage(string key, string? language)
    {
        var lang = language ?? CurrentLanguage;
        if (StringsFor(lang).TryGetValue(key, out var value)) return value;
        if (lang != DefaultLanguage && StringsFor(DefaultLanguage).TryGetValue(key, out var en)) return en;
        return key;
    }

    /// <summary>按 .strings 的 printf 风格占位符格式化。</summary>
    public static string Format(string format, object?[] args)
    {
        if (args.Length == 0) return format;
        try
        {
            return string.Format(CultureInfo.InvariantCulture, ToNetFormat(format), args);
        }
        catch (FormatException)
        {
            return format;
        }
    }

    // 只认契约里实际出现的转换符；flags 不含空格，这样 "100% done" 里的裸 % 不会被当成占位符，
    // 而 "%dh %dm" 只吃掉 %d、把后缀 h / m 留在结果里。
    private static readonly Regex FormatSpecifier =
        new(@"%(?:(\d+)\$)?[-+0#]*\d*(?:\.\d+)?(lld|ld|d|i|u|f|g|s|@|%)", RegexOptions.Compiled);

    /// <summary>把 printf 风格的占位符换成 .NET 的 <c>{n}</c>（不含参数的 % 保留原样）。</summary>
    public static string ToNetFormat(string format)
    {
        var index = 0;
        return FormatSpecifier.Replace(format, m =>
        {
            // 组 2 是转换符本身（组 1 是可选的 `n$` 显式序号）：`%%` 是字面百分号，
            // 不占参数位、也不会被换成一个 `{n}`（否则 "… %d%%" 这种「42%」就永远格式化不出来）。
            if (m.Groups[2].Value == "%") return "%";
            if (m.Groups[1].Success && int.TryParse(m.Groups[1].Value, out var explicitIndex))
            {
                return "{" + (explicitIndex - 1).ToString(CultureInfo.InvariantCulture) + "}";
            }
            var n = index++;
            return "{" + n.ToString(CultureInfo.InvariantCulture) + "}";
        });
    }

    private static IReadOnlyDictionary<string, string> StringsFor(string language)
    {
        lock (CacheLock)
        {
            if (Cache.TryGetValue(language, out var cached)) return cached;
        }
        var loaded = AllStrings(language) ?? new Dictionary<string, string>(StringComparer.Ordinal);
        lock (CacheLock)
        {
            Cache[language] = loaded;
        }
        return loaded;
    }

    /// <summary>语言切换后清掉缓存（资源文件不会变，但目录可能在开发时出现）。</summary>
    public static void ResetCache()
    {
        lock (CacheLock) Cache.Clear();
    }

    public static string? ResolveResourcesRoot()
    {
        if (ResourcesRoot is { } explicitRoot) return explicitRoot;
        var candidates = new List<string>();
        var baseDir = AppContext.BaseDirectory;
        candidates.Add(Path.Combine(baseDir, "Resources"));
        if (DefaultPaths.RepoRoot is { } repoRoot)
        {
            candidates.Add(Path.Combine(repoRoot, "ui", "Sources", "KanjoCore", "Resources"));
        }
        foreach (var dir in candidates)
        {
            if (Directory.Exists(Path.Combine(dir, "en.lproj")))
            {
                ResourcesRoot = dir;
                return dir;
            }
        }
        return null;
    }
}

/// <summary>便捷全局翻译函数。</summary>
public static class L
{
    public static string T(string key, params object?[] args) => L10n.Tr(key, args);
}
