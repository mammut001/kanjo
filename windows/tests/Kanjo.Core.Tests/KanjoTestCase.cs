using System.Globalization;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 测试基类：默认把语言强制为英文并指向隔离的内存设置，保证断言英文文案的测试在任何系统语言下都确定。
/// 每个测试自己造 <see cref="AppSettings"/>，绝不读写用户真实设置。
/// </summary>
public abstract class KanjoTestCase : IDisposable
{
    protected KanjoTestCase()
    {
        Settings = AppSettings.InMemory();
        Settings.Set(SettingsKeys.AppLanguage, "en");
        L10n.Store = Settings;
        L10n.ResetCache();
    }

    protected AppSettings Settings { get; }

    protected static string FixturePath => DefaultPaths.SampleFixture;

    protected static UsageReport LoadFixture() => ReportDecoder.Decode(File.ReadAllBytes(FixturePath));

    protected static DiskReport LoadDiskFixture()
    {
        var root = DefaultPaths.RepoRoot ?? throw new InvalidOperationException("repo root unavailable");
        return DiskDecoder.Decode(File.ReadAllBytes(Path.Combine(root, "ui", "fixtures", "disk-sample.json")));
    }

    /// <summary>临时目录（每个测试独立，绝不碰用户真实目录）。</summary>
    protected static string TempDir([System.Runtime.CompilerServices.CallerMemberName] string name = "")
    {
        var dir = Path.Combine(Path.GetTempPath(), "kanjo-tests", $"{name}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(dir);
        lock (TempDirs)
        {
            TempDirs.Add(dir);
        }
        return dir;
    }

    private static readonly List<string> TempDirs = [];

    public static void CleanupTempDirs()
    {
        lock (TempDirs)
        {
            foreach (var dir in TempDirs)
            {
                try
                {
                    Directory.Delete(dir, true);
                }
                catch (Exception)
                {
                    // 尽力而为。
                }
            }
            TempDirs.Clear();
        }
    }

    protected static DateTimeOffset Ts(string s) =>
        ReportDates.ParseTimestamp(s) ?? throw new FormatException(s);

    protected static void SetLanguage(string language)
    {
        if (L10n.Store is AppSettings settings) settings.Set(SettingsKeys.AppLanguage, language);
        L10n.ResetCache();
    }

    public virtual void Dispose()
    {
        L10n.Store = null;
        GC.SuppressFinalize(this);
    }
}
