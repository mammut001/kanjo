using Xunit;

namespace Kanjo.Core.Tests;

public sealed class ProjectPrefsTests : KanjoTestCase
{
    [Fact]
    public void TestParse()
    {
        Assert.Empty(ProjectPrefs.Parse(""));
        Assert.Equal(new HashSet<string> { "a", "b", "c" }, ProjectPrefs.Parse("a\nb\n\n  c  \r\nb\n"));
        Assert.Equal(new HashSet<string> { "/Users/me/My Repo", "github.com/x/y" },
            ProjectPrefs.Parse("/Users/me/My Repo\ngithub.com/x/y"));
    }

    [Fact]
    public void TestSerializeIsSortedAndRoundTrips()
    {
        var s = new HashSet<string> { "github.com/b", "/local/a", "github.com/a" };
        Assert.Equal("/local/a\ngithub.com/a\ngithub.com/b", ProjectPrefs.Serialize(s));
        Assert.Equal(s, ProjectPrefs.Parse(ProjectPrefs.Serialize(s)));
        Assert.Equal("", ProjectPrefs.Serialize([]));
    }

    [Fact]
    public void TestToggle()
    {
        Assert.Equal(new HashSet<string> { "a" }, ProjectPrefs.Toggle("a", new HashSet<string>()));
        Assert.Equal(new HashSet<string> { "b" }, ProjectPrefs.Toggle("a", new HashSet<string> { "a", "b" }));
        Assert.Equal("a\nb\nc", ProjectPrefs.Toggle("c", "a\nb"));
        Assert.Equal("b", ProjectPrefs.Toggle("a", "a\nb"));
        Assert.Equal("", ProjectPrefs.Toggle("a", "a"));
    }

    [Fact]
    public void TestArrange()
    {
        string[] items = ["p1", "p2", "p3", "p4", "p5"];
        var r = ProjectPrefs.Arrange(items, i => i, new HashSet<string> { "p4", "p2", "p5" },
            new HashSet<string> { "p3", "p5" });
        Assert.Equal(["p2", "p4", "p1"], r.Visible); // 置顶在前、各自保持原顺序；隐藏优先于置顶
        Assert.Equal(["p3", "p5"], r.Hidden);

        var none = ProjectPrefs.Arrange(items, i => i, new HashSet<string>(), new HashSet<string>());
        Assert.Equal(items, none.Visible);
        Assert.Empty(none.Hidden);
    }
}
