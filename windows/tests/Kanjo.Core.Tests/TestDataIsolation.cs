using System.Runtime.CompilerServices;

namespace Kanjo.Core.Tests;

/// <summary>
/// Runs once when the test assembly loads. Some tests drive the app with a fake
/// <c>config</c> runner but let the normal refresh start the real <c>kanjo export</c>;
/// without this, those runs read the user's real logs and wrote to their real
/// ledger, caches and Antigravity login record. Every CLI a test starts inherits
/// these throwaway folders, and with <c>KANJO_DATA_DIR</c> set the CLI also stops
/// reading the default log folders and the Antigravity app's storage.
/// </summary>
internal static class TestDataIsolation
{
    [ModuleInitializer]
    internal static void Isolate()
    {
        var root = Path.Combine(Path.GetTempPath(), "kanjo-dotnet-tests-" + Environment.ProcessId);
        Directory.CreateDirectory(Path.Combine(root, "data"));
        Directory.CreateDirectory(Path.Combine(root, "cache"));
        Environment.SetEnvironmentVariable("KANJO_DATA_DIR", Path.Combine(root, "data"));
        Environment.SetEnvironmentVariable("KANJO_CACHE_DIR", Path.Combine(root, "cache"));
        Environment.SetEnvironmentVariable("KANJO_ANTIGRAVITY_APP_STORAGE", Path.Combine(root, "no-app-storage.json"));
        AppDomain.CurrentDomain.ProcessExit += (_, _) =>
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        };
    }
}
