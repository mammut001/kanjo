using System.IO.Pipes;
using System.Text;

namespace Kanjo.Core;

/// <summary>第二次启动要告诉正在运行的实例做什么（目前只有「把面板弹出来」）。</summary>
public enum SingleInstanceMessage
{
    /// <summary>激活已运行实例的面板（第二次启动时托盘图标已经在了）。</summary>
    Activate,
}

/// <summary>
/// 单实例的传输层：一个名字 → 一个「主实例」+ 一条能把消息送过去的通道。
/// 生产用 <see cref="NamedPipeSingleInstanceTransport"/>（命名 Mutex + 命名管道），测试用假实现。
/// </summary>
public interface ISingleInstanceTransport : IDisposable
{
    /// <summary>尝试成为主实例。已经有一个主实例时返回 false。</summary>
    bool TryRegister(string name);

    /// <summary>主实例开始接收消息（后台线程）。</summary>
    void StartListening(string name, Action<SingleInstanceMessage> onMessage);

    /// <summary>把消息发给主实例。没有主实例 / 发送失败时返回 false。</summary>
    bool Send(string name, SingleInstanceMessage message);
}

/// <summary>
/// 单实例：第一个进程成为主实例并等待消息，之后的进程把「激活面板」发给它然后退出
/// （Mac 上第二次打开 App 由系统激活已有实例，Windows 没有这个机制）。
/// </summary>
public sealed class SingleInstanceCoordinator : IDisposable
{
    public const string DefaultName = "Kanjo";

    private readonly object _lock = new();
    private readonly ISingleInstanceTransport _transport;
    private readonly string _name;
    private bool _pendingActivation;
    private bool _disposed;

    public SingleInstanceCoordinator(ISingleInstanceTransport? transport = null, string name = DefaultName)
    {
        _transport = transport ?? new NamedPipeSingleInstanceTransport();
        _name = name;
        IsPrimary = _transport.TryRegister(name);
        if (IsPrimary) _transport.StartListening(name, Handle);
    }

    /// <summary>本进程是否是要留在托盘里的那一个。</summary>
    public bool IsPrimary { get; }

    /// <summary>主实例收到「激活」请求（托盘要把面板弹出来）。可能在后台线程触发。</summary>
    public event Action? ActivateRequested;

    /// <summary>
    /// 启动瞬间就收到「激活」（托盘还没建好）时先记下；订阅 <see cref="ActivateRequested"/> 之后
    /// 调用一次，把积压的请求补发出去。
    /// </summary>
    public bool FlushPending()
    {
        bool fire;
        lock (_lock)
        {
            if (_disposed || !_pendingActivation) return false;
            _pendingActivation = false;
            fire = ActivateRequested is not null;
        }
        if (fire) ActivateRequested?.Invoke();
        return fire;
    }

    /// <summary>非主实例：让主实例把面板弹出来。返回是否送达。</summary>
    public bool RequestActivation() => _transport.Send(_name, SingleInstanceMessage.Activate);

    private void Handle(SingleInstanceMessage message)
    {
        if (message != SingleInstanceMessage.Activate) return;
        Action? handler;
        lock (_lock)
        {
            if (_disposed) return;
            handler = ActivateRequested;
            if (handler is null)
            {
                // 托盘还没接上（启动瞬间的第二份实例）：等订阅者来了再弹。
                _pendingActivation = true;
                return;
            }
        }
        handler();
    }

    public void Dispose()
    {
        lock (_lock)
        {
            if (_disposed) return;
            _disposed = true;
            ActivateRequested = null;
        }
        _transport.Dispose();
    }
}

/// <summary>
/// 命名 Mutex（判断谁是主实例）+ 命名管道（传消息）。名字带当前用户名，
/// 同一台机器上的多个用户各有一个实例；管道名加随机后缀避免和别的程序撞。
/// </summary>
public sealed class NamedPipeSingleInstanceTransport : ISingleInstanceTransport
{
    private Mutex? _mutex;
    private bool _ownsMutex;
    private CancellationTokenSource? _cts;
    private Task? _listenTask;

    public string PipeNameFor(string name)
    {
        var user = Environment.UserName.ToLowerInvariant();
        var safeName = new string(name.Where(char.IsLetterOrDigit).ToArray()).ToLowerInvariant();
        var safeUser = new string(user.Where(char.IsLetterOrDigit).ToArray());
        return $"kanjo-{safeName}-{safeUser}-activate";
    }

    public bool TryRegister(string name)
    {
        var mutexName = OperatingSystem.IsWindows() ? $"Local\\{PipeNameFor(name)}" : PipeNameFor(name);
        try
        {
            _mutex = new Mutex(initiallyOwned: true, mutexName, out var createdNew);
            _ownsMutex = createdNew;
            return createdNew;
        }
        catch (Exception)
        {
            // 名字冲突 / 没有权限：当作主实例（宁可多开也不要开不起来）。
            _mutex?.Dispose();
            _mutex = null;
            _ownsMutex = false;
            return true;
        }
    }

    public void StartListening(string name, Action<SingleInstanceMessage> onMessage)
    {
        var pipeName = PipeNameFor(name);
        _cts = new CancellationTokenSource();
        var token = _cts.Token;
        _listenTask = Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    await using var server = new NamedPipeServerStream(pipeName, PipeDirection.In, 1,
                        PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
                    await server.WaitForConnectionAsync(token).ConfigureAwait(false);
                    using var reader = new StreamReader(server, Encoding.UTF8, false, 256, leaveOpen: true);
                    var line = await reader.ReadLineAsync(token).ConfigureAwait(false);
                    if (line is not null && Enum.TryParse<SingleInstanceMessage>(line.Trim(), out var message))
                    {
                        onMessage(message);
                    }
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                catch (Exception)
                {
                    // 管道被别人占用 / 关闭：稍等一下再等一下一个连接。
                    try
                    {
                        await Task.Delay(TimeSpan.FromMilliseconds(100), token).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException)
                    {
                        return;
                    }
                }
            }
        }, token);
    }

    public bool Send(string name, SingleInstanceMessage message)
    {
        var pipeName = PipeNameFor(name);
        try
        {
            using var client = new NamedPipeClientStream(".", pipeName, PipeDirection.Out);
            client.Connect(2000);
            using var writer = new StreamWriter(client, new UTF8Encoding(false), 256, leaveOpen: true)
            {
                AutoFlush = true,
            };
            writer.WriteLine(message.ToString());
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    public void Dispose()
    {
        _cts?.Cancel();
        try
        {
            _listenTask?.Wait(TimeSpan.FromSeconds(1));
        }
        catch (Exception)
        {
            // 已经结束。
        }
        _cts?.Dispose();
        _cts = null;
        _listenTask = null;
        if (_ownsMutex)
        {
            try
            {
                _mutex?.ReleaseMutex();
            }
            catch (Exception)
            {
                // 线程不对 / 已经释放。
            }
        }
        _mutex?.Dispose();
        _mutex = null;
        _ownsMutex = false;
    }
}
