using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace Kanjo.Core;

/// <summary>节电模式变化的参数（对应 Mac 的 <c>.NSProcessInfoPowerStateDidChange</c>）。</summary>
public sealed class LowPowerModeEventArgs(bool enabled) : EventArgs
{
    public bool Enabled { get; } = enabled;
}

/// <summary>
/// 系统电源事件（Mac 的 <c>NSWorkspace.willSleepNotification</c> / <c>didWakeNotification</c> /
/// <c>NSProcessInfoPowerStateDidChange</c>）。Windows 用 <c>SystemEvents.PowerModeChanged</c> +
/// 查询系统电源状态；其它平台是空实现（开发运行不会假装睡过觉）。
/// </summary>
public interface IPowerMonitor : IDisposable
{
    event EventHandler? WillSuspend;

    event EventHandler? DidResume;

    event EventHandler<LowPowerModeEventArgs>? LowPowerModeChanged;

    /// <summary>开始监听（Windows 上订阅 SystemEvents，并定期查一次节电模式）。</summary>
    void Start();

    /// <summary>当前是否处于节电模式；不支持时返回 false。</summary>
    bool IsLowPowerMode { get; }
}

/// <summary>什么都不做的实现：非 Windows 开发运行 / 无电源事件的测试用。</summary>
public sealed class NullPowerMonitor : IPowerMonitor
{
    public static NullPowerMonitor Shared { get; } = new();

    public event EventHandler? WillSuspend
    {
        add { }
        remove { }
    }

    public event EventHandler? DidResume
    {
        add { }
        remove { }
    }

    public event EventHandler<LowPowerModeEventArgs>? LowPowerModeChanged
    {
        add { }
        remove { }
    }

    public void Start()
    {
    }

    public bool IsLowPowerMode => false;

    public void Dispose()
    {
    }
}

/// <summary>
/// Windows 电源事件：挂 <c>Microsoft.Win32.SystemEvents.PowerModeChanged</c>（挂之前要先有消息循环，
/// 见 <see cref="SystemEvents"/>），节电模式用 <c>GetSystemPowerStatus</c> 的
/// <c>SystemStatusFlag</c>（1 = 节电模式开启）轮询。
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class WindowsPowerMonitor : IPowerMonitor
{
    /// <summary>节电模式轮询间隔：Mac 是系统推送通知，Windows 没有对应事件。</summary>
    public static readonly TimeSpan PollInterval = TimeSpan.FromSeconds(30);

    private readonly object _lock = new();
    private System.Threading.Timer? _poll;
    private bool _started;
    private bool _isLowPower;
    private bool _disposed;

    public event EventHandler? WillSuspend;

    public event EventHandler? DidResume;

    public event EventHandler<LowPowerModeEventArgs>? LowPowerModeChanged;

    public bool IsLowPowerMode
    {
        get { lock (_lock) return _isLowPower; }
    }

    public void Start()
    {
        lock (_lock)
        {
            if (_disposed || _started) return;
            _started = true;
        }
        try
        {
            Microsoft.Win32.SystemEvents.PowerModeChanged += OnPowerModeChanged;
        }
        catch (Exception)
        {
            // 没有消息循环 / 权限：只剩节电模式轮询。
        }
        _isLowPower = QueryLowPowerMode();
        _poll = new System.Threading.Timer(_ => Poll(), null, PollInterval, PollInterval);
    }

    private void OnPowerModeChanged(object sender, Microsoft.Win32.PowerModeChangedEventArgs e)
    {
        switch (e.Mode)
        {
            case Microsoft.Win32.PowerModes.Suspend:
                WillSuspend?.Invoke(this, EventArgs.Empty);
                return;
            case Microsoft.Win32.PowerModes.Resume:
                DidResume?.Invoke(this, EventArgs.Empty);
                return;
            default:
                return;
        }
    }

    private void Poll()
    {
        lock (_lock)
        {
            if (_disposed) return;
        }
        var low = QueryLowPowerMode();
        bool changed;
        lock (_lock)
        {
            changed = low != _isLowPower;
            _isLowPower = low;
        }
        if (changed) LowPowerModeChanged?.Invoke(this, new LowPowerModeEventArgs(low));
    }

    /// <summary>
    /// <c>SYSTEM_POWER_STATUS.SystemStatusFlag</c> 的最低位就是「节电模式开启」（Windows 10 1703+）。
    /// 取不到状态时按「不是节电模式」处理。
    /// </summary>
    public static bool QueryLowPowerMode()
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            if (!NativeMethods.GetSystemPowerStatus(out var status)) return false;
            return (status.SystemStatusFlag & 1) == 1;
        }
        catch (Exception)
        {
            return false;
        }
    }

    public void Dispose()
    {
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            _poll?.Dispose();
            _poll = null;
            if (!_started) return;
            _started = false;
        }
        try
        {
            Microsoft.Win32.SystemEvents.PowerModeChanged -= OnPowerModeChanged;
        }
        catch (Exception)
        {
            // 已经释放。
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SystemPowerStatus
    {
        public byte ACLineStatus;
        public byte BatteryFlag;
        public byte BatteryLifePercent;
        public byte SystemStatusFlag;
        public int BatteryLifeTime;
        public int BatteryFullLifeTime;
    }

    private static class NativeMethods
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool GetSystemPowerStatus(out SystemPowerStatus status);
    }
}
