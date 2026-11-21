using Xunit;

namespace Kanjo.Core.Tests;

public sealed class DecodingEquivalenceTests : KanjoTestCase
{
    private static string SnapshotPath =>
        Path.Combine(AppContext.BaseDirectory, "Fixtures", "decoded-sample-snapshot.json");

    [Fact]
    public void TestSampleFixtureMatchesCanonicalSnapshot()
    {
        var bytes = File.ReadAllBytes(FixturePath);
        var report = ReportDecoder.Decode(bytes);
        var actual = ReportCanonicalJson.Serialize(report);
        var write = Environment.GetEnvironmentVariable("KANJO_DECODE_SNAPSHOT_WRITE");
        if (write is not null)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(write)!);
            File.WriteAllText(write, actual);
            return;
        }
        var expected = File.ReadAllText(SnapshotPath);
        Assert.Equal(expected.TrimEnd(), actual);
    }
}