using Kanjo.Core;
using Xunit;

namespace Kanjo.Core.Tests;

/// <summary>
/// 单实例：主实例收到「激活」请求时弹面板，第二次启动只负责发消息然后退出。
/// 传输层用假实现；真实实现（命名 Mutex + 命名管道）只在测试里验证名字生成，不开端口。
/// </summary>
public sealed class SingleInstanceTests : KanjoTestCase
{
    private sealed class FakeTransport : ISingleInstanceTransport
    {
        public bool Primary { get; set; } = true;
        public bool SendSucceeds { get; set; } = true;
        public bool Disposed { get; private set; }
        public bool Listening { get; private set; }
        public Action<SingleInstanceMessage>? Handler { get; private set; }
        public List<(string Name, SingleInstanceMessage Message)> Sent { get; } = [];

        public bool TryRegister(string name) => Primary;

        public void StartListening(string name, Action<SingleInstanceMessage> onMessage)
        {
            Listening = true;
            Handler = onMessage;
        }

        public bool Send(string name, SingleInstanceMessage message)
        {
            Sent.Add((name, message));
            return SendSucceeds;
        }

        public void Dispose() => Disposed = true;

        public void Receive(SingleInstanceMessage message) => Handler?.Invoke(message);
    }

    [Fact]
    public void TestPrimaryStartsListening()
    {
        var transport = new FakeTransport();
        using var coordinator = new SingleInstanceCoordinator(transport, "kanjo-test");

        Assert.True(coordinator.IsPrimary);
        Assert.True(transport.Listening);
    }

    [Fact]
    public void TestSecondInstanceDoesNotListen()
    {
        var transport = new FakeTransport { Primary = false };
        using var coordinator = new SingleInstanceCoordinator(transport, "kanjo-test");

        Assert.False(coordinator.IsPrimary);
        Assert.False(transport.Listening);
    }

    [Fact]
    public void TestSecondInstanceSendsActivate()
    {
        var transport = new FakeTransport { Primary = false };
        using var coordinator = new SingleInstanceCoordinator(transport, "kanjo-test");

        Assert.True(coordinator.RequestActivation());
        var sent = Assert.Single(transport.Sent);
        Assert.Equal("kanjo-test", sent.Name);
        Assert.Equal(SingleInstanceMessage.Activate, sent.Message);
    }

    [Fact]
    public void TestPrimaryRaisesActivateRequested()
    {
        var transport = new FakeTransport();
        using var coordinator = new SingleInstanceCoordinator(transport, "kanjo-test");
        var activations = 0;
        coordinator.ActivateRequested += () => activations++;

        transport.Receive(SingleInstanceMessage.Activate);
        Assert.Equal(1, activations);
    }

    [Fact]
    public void TestActivationBeforeSubscriberIsReplayed()
    {
        // 启动瞬间来的第二份实例：托盘还没建好，等订阅者接上那一刻补发。
        var transport = new FakeTransport();
        using var coordinator = new SingleInstanceCoordinator(transport, "kanjo-test");
        transport.Receive(SingleInstanceMessage.Activate);

        var activations = 0;
        coordinator.ActivateRequested += () => activations++;
        Assert.True(coordinator.FlushPending());
        Assert.Equal(1, activations);

        // 补发只做一次。
        Assert.False(coordinator.FlushPending());
        Assert.Equal(1, activations);

        // 之后再来的请求直接触发。
        transport.Receive(SingleInstanceMessage.Activate);
        Assert.Equal(2, activations);
    }

    [Fact]
    public void TestDisposeDisposesTransport()
    {
        var transport = new FakeTransport();
        var coordinator = new SingleInstanceCoordinator(transport, "kanjo-test");
        coordinator.Dispose();
        Assert.True(transport.Disposed);
    }

    [Fact]
    public void TestSendFailureReported()
    {
        var transport = new FakeTransport { Primary = false, SendSucceeds = false };
        using var coordinator = new SingleInstanceCoordinator(transport, "kanjo-test");
        Assert.False(coordinator.RequestActivation());
    }

    [Fact]
    public void TestPipeNameIsStableAndUserScoped()
    {
        var transport = new NamedPipeSingleInstanceTransport();
        var name = transport.PipeNameFor("Kanjo");

        Assert.Equal(name, transport.PipeNameFor("Kanjo"));
        Assert.Equal(name, new NamedPipeSingleInstanceTransport().PipeNameFor("Kanjo"));
        Assert.Contains("kanjo", name);
        Assert.DoesNotContain(' ', name);
        Assert.DoesNotContain("Kanjo", name); // 统一小写，避免大小写不同的两份
        Assert.NotEqual(name, transport.PipeNameFor("Other"));
    }

    [Fact]
    public void TestRealTransportRegistersOncePerProcess()
    {
        // 同一个进程里注册两次：第二次应该拿到「已有主实例」。
        using var first = new NamedPipeSingleInstanceTransport();
        using var second = new NamedPipeSingleInstanceTransport();
        var name = $"kanjo-test-{Guid.NewGuid():N}";

        Assert.True(first.TryRegister(name));
        Assert.False(second.TryRegister(name));

        // 另一个名字不受影响（不同名字互不干扰）。
        using var other = new NamedPipeSingleInstanceTransport();
        Assert.True(other.TryRegister(name + "-other"));
    }
}
