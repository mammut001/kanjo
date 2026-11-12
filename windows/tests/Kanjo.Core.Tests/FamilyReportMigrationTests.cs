using Xunit;

namespace Kanjo.Core.Tests;

public sealed class FamilyReportMigrationTests : KanjoTestCase
{
    [Fact]
    public void TestMigrationWhenEnabledAndUrlAbsent()
    {
        Settings.Set(SettingsKeys.FamilyReportEnabled, true);
        Assert.Null(Settings.Raw(SettingsKeys.FamilyReportUrl));
        Assert.False(Settings.Bool(SettingsKeys.FamilyReportMigrationDone, false));

        var migrated = FamilyReportMigration.Migrate(Settings);

        Assert.True(migrated);
        Assert.Equal("https://usage.paytonpei.top", Settings.GetString(SettingsKeys.FamilyReportUrl));
        Assert.True(Settings.Bool(SettingsKeys.FamilyReportMigrationDone, false));
    }

    [Fact]
    public void TestMigrationDoesNotWriteWhenDisabled()
    {
        Settings.Set(SettingsKeys.FamilyReportEnabled, false);
        Assert.False(FamilyReportMigration.Migrate(Settings));
        Assert.Null(Settings.Raw(SettingsKeys.FamilyReportUrl));
        Assert.True(Settings.Bool(SettingsKeys.FamilyReportMigrationDone, false));
    }

    [Fact]
    public void TestMigrationDoesNotOverwriteCustomUrl()
    {
        Settings.Set(SettingsKeys.FamilyReportEnabled, true);
        Settings.Set(SettingsKeys.FamilyReportUrl, "https://usage.customfamily.net");

        Assert.False(FamilyReportMigration.Migrate(Settings));
        Assert.Equal("https://usage.customfamily.net", Settings.GetString(SettingsKeys.FamilyReportUrl));
        Assert.True(Settings.Bool(SettingsKeys.FamilyReportMigrationDone, false));
    }

    [Fact]
    public void TestMigrationRunsOnlyOnce()
    {
        Settings.Set(SettingsKeys.FamilyReportEnabled, true);
        Assert.True(FamilyReportMigration.Migrate(Settings));
        Assert.Equal("https://usage.paytonpei.top", Settings.GetString(SettingsKeys.FamilyReportUrl));

        Settings.Set(SettingsKeys.FamilyReportUrl, "https://usage.example.com");
        Assert.False(FamilyReportMigration.Migrate(Settings));
        Assert.Equal("https://usage.example.com", Settings.GetString(SettingsKeys.FamilyReportUrl));
    }
}
