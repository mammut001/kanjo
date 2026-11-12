using System.Globalization;
using Avalonia;
using Avalonia.Headless;
using Kanjo.App;
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

    /// <summary>
    /// 共享的 headless 会话（进程级只建一次）。
    /// 必须显式指定 <see cref="HeadlessApplication"/>：默认的 Application 没有装 FluentTheme，
    /// ToggleSwitch / ComboBox 这些模板控件会缺模板部件（KeyNotFoundException: PART_MovingKnobs）。
    /// </summary>
    private static HeadlessUnitTestSession? _session;

    private static readonly object SessionLock = new();

    private static HeadlessUnitTestSession Session
    {
        get
        {
            lock (SessionLock)
            {
                return _session ??= HeadlessUnitTestSession.StartNew(typeof(HeadlessApplication));
            }
        }
    }

    /// <summary>
    /// 在 Avalonia 的 UI 线程上跑一段 UI 断言。
    ///
    /// 一旦进程里建立过 headless 会话，在测试线程上 new 任何 Avalonia 对象都会抛
    /// "Call from invalid thread"，所以所有涉及控件的测试都必须走这里。
    /// </summary>
    protected static void OnUi(Action body)
    {
        AppSetup.ConfigureHeadless("light");
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        Session.Dispatch(() =>
        {
            body();
            return true;
        }, cts.Token).GetAwaiter().GetResult();
    }

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
