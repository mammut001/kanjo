using Avalonia;
using Avalonia.Controls;
using Avalonia.Threading;

namespace Kanjo.Core.Tests;

/// <summary>
/// 所有 UI 用例里建出来的窗口都在这里登记，用例结束（成功或失败）后统一关掉。
///
/// 为什么需要：headless 会话的每一次 <c>Dispatch</c> 都会新建一个 <see cref="Application"/>，
/// 而窗口挂在**上一个** Application 的树里。用例忘了关（断言失败提前抛异常最常见）时，
/// 那个窗口会活到下一轮：下一轮改全局资源 / 主题变体时，Avalonia 会遍历它的逻辑树，
/// 而那个 Application 正在被拆除 —— 这正是 CI 上偶发的 ArgumentOutOfRangeException /
/// "Call from invalid thread" 的来源。用例中间不必自己关窗口，收尾统一在
/// <see cref="KanjoTestCase.OnUi"/> 里做。
/// </summary>
internal static class TestWindows
{
    private static readonly List<Window> Live = [];

    /// <summary>建窗口、显示、登记（必须在 UI 线程上调用）。</summary>
    public static Window Show(Control page, double width, double height)
    {
        var window = new Window { Width = width, Height = height, Content = page };
        // 用例自己关掉时就从名单里摘掉，收尾时不用再碰（重复 Close 会再走一遍关闭流程）。
        window.Closed += (_, _) => Live.Remove(window);
        window.Show();
        Live.Add(window);
        return window;
    }

    /// <summary>关掉所有还开着的窗口（必须在 UI 线程上调用）。</summary>
    public static void CloseAll()
    {
        foreach (var window in Live.ToList())
        {
            try
            {
                window.Close();
            }
            catch (Exception)
            {
                // 收尾：关不掉就算了，绝不能掩盖用例本身的断言失败。
            }
        }
        Live.Clear();
        Dispatcher.UIThread.RunJobs();
    }
}
