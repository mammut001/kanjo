using Xunit;

namespace Kanjo.Core.Tests;

public sealed class LocalizationTests : KanjoTestCase
{
    /// <summary>确保 en 中的每一个 key 在 zh-Hans 和 fr 中都存在。</summary>
    [Fact]
    public void TestAllKeysPresentInAllLanguages()
    {
        var en = L10n.AllStrings("en");
        Assert.NotNull(en);
        Assert.False(en!.Count == 0, "English strings dictionary should not be empty");

        foreach (var lang in new[] { "zh-Hans", "fr" })
        {
            var other = L10n.AllStrings(lang);
            Assert.NotNull(other);
            var missing = en.Keys.Where(k => !other!.ContainsKey(k)).OrderBy(k => k, StringComparer.Ordinal).ToList();
            Assert.True(missing.Count == 0, $"{lang} is missing keys: {string.Join(", ", missing)}");
        }
    }

    /// <summary>扫描 Mac 版 UI 源码里所有 L10n.tr 的字面量 key，确保它们均在 en.lproj 中存在。</summary>
    [Fact]
    public void TestAllSourceKeysPresentInEnglishStrings()
    {
        var repo = DefaultPaths.RepoRoot;
        Assert.NotNull(repo);
        var en = L10n.AllStrings("en");
        Assert.NotNull(en);

        var sources = Directory.Exists(Path.Combine(repo!, "ui", "Sources"))
            ? Path.Combine(repo!, "ui", "Sources")
            : Path.Combine(repo!, "Sources");
        Assert.True(Directory.Exists(sources), sources);

        var regex = new System.Text.RegularExpressions.Regex("L10n\\.tr\\(\\s*\"([^\"]+)\"");
        var used = new HashSet<string>(StringComparer.Ordinal);
        foreach (var file in Directory.EnumerateFiles(sources, "*.swift", SearchOption.AllDirectories))
        {
            var content = File.ReadAllText(file);
            foreach (System.Text.RegularExpressions.Match m in regex.Matches(content))
            {
                used.Add(m.Groups[1].Value);
            }
        }

        Assert.NotEmpty(used);
        var missing = used.Where(k => !en!.ContainsKey(k)).OrderBy(k => k, StringComparer.Ordinal).ToList();
        Assert.True(missing.Count == 0, $"Keys used in ui/Sources missing in en.lproj: {string.Join(", ", missing)}");
    }

    /// <summary>验证对若干常用 key 解析 zh-Hans 和 fr 时返回的内容与英文不同（且不是原始 key）。</summary>
    [Fact]
    public void TestResolvingKeysDifferFromEnglish()
    {
        string[] sampleKeys =
        [
            "common.done", "settings.title", "overview.total_cost", "disk.clean_help", "menu.quit",
        ];
        foreach (var key in sampleKeys)
        {
            var en = L10n.TrL("en", key);
            var zh = L10n.TrL("zh-Hans", key);
            var fr = L10n.TrL("fr", key);

            Assert.NotEqual(en, zh);
            Assert.NotEqual(en, fr);
            Assert.NotEqual(key, zh);
            Assert.NotEqual(key, fr);
        }
    }

    [Fact]
    public void TestEffectiveLanguage()
    {
        Assert.Equal("en", L10n.EffectiveLanguage("en"));
        Assert.Equal("zh-Hans", L10n.EffectiveLanguage("zh-Hans"));
        Assert.Equal("fr", L10n.EffectiveLanguage("fr"));

        // "system", null 或未识别语言应回退到支持的系统语言
        Assert.Contains(L10n.EffectiveLanguage("system"), L10n.SupportedLanguages);
        Assert.Contains(L10n.EffectiveLanguage(null), L10n.SupportedLanguages);
        Assert.Contains(L10n.EffectiveLanguage("unsupported-lang"), L10n.SupportedLanguages);

        // 变体拼写
        Assert.Equal("zh-Hans", L10n.EffectiveLanguage("zh-hans"));
        Assert.Equal("zh-Hans", L10n.EffectiveLanguage("zh_Hans"));
    }

    [Fact]
    public void TestMissingKeyFallback()
    {
        const string missingKey = "nonexistent.key.that.does.not.exist";
        Assert.Equal(missingKey, L10n.TrL("en", missingKey));
        Assert.Equal(missingKey, L10n.TrL("zh-Hans", missingKey));
        Assert.Equal(missingKey, L10n.TrL("fr", missingKey));
    }

    [Fact]
    public void TestParameterizedTranslation()
    {
        Assert.Equal("Show all 5 items", L10n.TrL("en", "common.show_all", 5, "items"));
    }

    [Fact]
    public void TestLprojMatcher()
    {
        // 1. 标准目录名
        var standard = new[] { "en.lproj", "zh-Hans.lproj", "fr.lproj" };
        Assert.Equal("zh-Hans.lproj", L10n.MatchLproj("zh-Hans", standard));
        Assert.Equal("en.lproj", L10n.MatchLproj("en", standard));
        Assert.Equal("fr.lproj", L10n.MatchLproj("fr", standard));

        // 2. 小写目录名 (zh-hans.lproj)
        var lower = new[] { "en.lproj", "zh-hans.lproj", "fr.lproj" };
        Assert.Equal("zh-hans.lproj", L10n.MatchLproj("zh-Hans", lower));
        Assert.Equal("zh-hans.lproj", L10n.MatchLproj("zh-hans", lower));
        Assert.Equal("zh-hans.lproj", L10n.MatchLproj("zh_Hans", lower));

        // 3. 下划线目录名 (zh_Hans.lproj / zh_hans.lproj)
        var underscore = new[] { "en.lproj", "zh_Hans.lproj", "fr.lproj" };
        Assert.Equal("zh_Hans.lproj", L10n.MatchLproj("zh-Hans", underscore));
        Assert.Equal("zh_Hans.lproj", L10n.MatchLproj("zh-hans", underscore));
        Assert.Equal("zh_Hans.lproj", L10n.MatchLproj("zh_Hans", underscore));

        var underscoreLower = new[] { "en.lproj", "zh_hans.lproj", "fr.lproj" };
        Assert.Equal("zh_hans.lproj", L10n.MatchLproj("zh-Hans", underscoreLower));

        // 4. 大写目录名 (ZH-HANS.LPROJ / ZH_HANS.LPROJ)
        var upper = new[] { "EN.LPROJ", "ZH-HANS.LPROJ", "FR.LPROJ" };
        Assert.Equal("ZH-HANS.LPROJ", L10n.MatchLproj("zh-Hans", upper));
        Assert.Equal("ZH-HANS.LPROJ", L10n.MatchLproj("zh_Hans", upper));

        // 5. 不带 .lproj 后缀的语言代码列表（如 Bundle.localizations）
        var raw = new[] { "en", "zh-hans", "fr" };
        Assert.Equal("zh-hans", L10n.MatchLproj("zh-Hans", raw));
        Assert.Equal("zh-hans", L10n.MatchLproj("zh_Hans", raw));

        // 6. 别名 MatchLprojDirectory 同样可用
        Assert.Equal("zh-hans.lproj", L10n.MatchLprojDirectory("zh-Hans", lower));

        // 7. 不匹配与边界情况
        Assert.Null(L10n.MatchLproj("ja", standard));
        Assert.Null(L10n.MatchLproj("zh-Hant", standard));
        Assert.Null(L10n.MatchLproj("zh-Hans", Array.Empty<string>()));
        Assert.Null(L10n.MatchLproj("", standard));
        Assert.Null(L10n.MatchLproj("   ", standard));
    }

    [Fact]
    public void TestLanguageVariantsStringsLoading()
    {
        foreach (var variant in new[] { "zh-Hans", "zh-hans", "zh_Hans" })
        {
            var strings = L10n.AllStrings(variant);
            Assert.NotNull(strings);
            Assert.True(strings!.Count > 0, $"Strings dictionary for {variant} should not be empty");
            Assert.NotNull(L10n.LprojDirectory(variant));
            Assert.Equal("完成", L10n.TrL(variant, "common.done"));
        }
    }

    [Fact]
    public void TestStringsParserHandlesCommentsAndEscapes()
    {
        const string content = """
            /* 块注释 "with quotes" */
            // 行注释
            "a.key" = "hello";
            "b.key" = "line\nbreak \"quoted\"";
            "c.key" = "tab\there";
            "d.key" = "no trailing semicolon"
            """;
        var parsed = L10n.ParseStringsFile(content);
        Assert.Equal("hello", parsed["a.key"]);
        Assert.Equal("line\nbreak \"quoted\"", parsed["b.key"]);
        Assert.Equal("tab\there", parsed["c.key"]);
        Assert.Equal("no trailing semicolon", parsed["d.key"]);
    }

    [Fact]
    public void TestNetFormatConversion()
    {
        Assert.Equal("Show all {0} {1}", L10n.ToNetFormat("Show all %d %@"));
        Assert.Equal("{0} · {1}", L10n.ToNetFormat("%@ · %@"));
        Assert.Equal("100% done", L10n.ToNetFormat("100% done"));
        Assert.Equal("{1} then {0}", L10n.ToNetFormat("%2$@ then %1$@"));
    }

    [Fact]
    public void TestLiveLanguageSwitch()
    {
        SetLanguage("en");
        Assert.Equal("Done", L10n.Tr("common.done"));
        SetLanguage("zh-Hans");
        Assert.Equal("完成", L10n.Tr("common.done"));
        SetLanguage("fr");
        Assert.Equal("Terminé", L10n.Tr("common.done"));
    }
}
