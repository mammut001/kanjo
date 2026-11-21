using System.Reflection;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Threading;
using Kanjo.App;
using Xunit;

namespace Kanjo.Core.Tests;

public sealed class HoverDismissTests : KanjoTestCase
{
    [Fact]
    public void LeavingBeforeDelayCancelsOnlyThatTargetsTimer()
    {
        OnUi(() =>
        {
            var layer = new HoverLayer();
            var first = new Border { Width = 20, Height = 20 };
            var second = new Border { Width = 20, Height = 20 };
            var root = new Grid { Children = { first, second, layer } };
            var window = TestWindows.Show(root, 200, 200);
            layer.Register(first, "first", () => new TextBlock { Text = "first" });
            layer.Register(second, "second", () => new TextBlock { Text = "second" });

            void Send(Control target, Avalonia.Interactivity.RoutedEvent<PointerEventArgs> ev)
            {
                target.RaiseEvent(new PointerEventArgs(ev, target, null!, window, new Point(), 0,
                    new PointerPointProperties(), KeyModifiers.None));
            }
            DispatcherTimer Timer() => (DispatcherTimer)typeof(HoverLayer)
                .GetField("_timer", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(layer)!;

            Send(first, InputElement.PointerEnteredEvent);
            Assert.True(Timer().IsEnabled);
            Send(first, InputElement.PointerExitedEvent);
            Assert.False(Timer().IsEnabled);

            Send(first, InputElement.PointerEnteredEvent);
            Send(second, InputElement.PointerEnteredEvent);
            Send(first, InputElement.PointerExitedEvent);
            Assert.True(Timer().IsEnabled);
            Send(second, InputElement.PointerExitedEvent);
            Assert.False(Timer().IsEnabled);
        });
    }
}
