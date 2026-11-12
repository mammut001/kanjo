namespace Kanjo.Core;

/// <summary>设置的键与默认值，与 Mac 版 `SettingsKeys.swift` 完全一致（同一套 key，同一个 JSON 文件里的字段名）。</summary>
public static class SettingsKeys
{
    public const string AppLanguage = "appLanguage";
    public const string SourceKind = "sourceKind";
    public const string FilePath = "filePath";
    public const string CliCommand = "cliCommand";
    public const string CliWorkingDirectory = "cliWorkingDirectory";
    public const string RefreshMinutes = "refreshMinutes";
    public const string ShowAmountInMenuBar = "showAmountInMenuBar";
    public const string MenuBarMode = "menuBarMode";
    public const string HiddenProjects = "hiddenProjects";
    public const string PinnedProjects = "pinnedProjects";
    public const string TimeRange = "timeRange";
    public const string RenewalNudgeDismissed = "renewalNudgeDismissed";
    public const string SubscriptionOrder = "subscriptionOrder";
    public const string CloudSyncEnabled = "cloudSyncEnabled";
    public const string CloudSyncHideProjectNames = "cloudSyncHideProjectNames";
    public const string CloudSyncDeviceID = "cloudSyncDeviceID";
    public const string CloudSyncLastUploadHash = "cloudSyncLastUploadHash";
    public const string CloudSyncLastFingerprint = "cloudSyncLastFingerprint";
    public const string CloudSyncLastUploadedAt = "cloudSyncLastUploadedAt";
    public const string PublishEnabled = "publishEnabled";
    public const string PublishFrequency = "publishFrequency";
    public const string PublishRepoPath = "publishRepoPath";
    public const string PublishFilePath = "publishFilePath";
    public const string PublishBranch = "publishBranch";
    public const string PublishLastAttemptAt = "publishLastAttemptAt";
    public const string PublishLastSuccessAt = "publishLastSuccessAt";
    public const string PublishLastResult = "publishLastResult";
    public const string FamilyReportEnabled = "familyReportEnabled";
    public const string FamilyReportMode = "familyReportMode";
    public const string FamilyReportUrl = "familyReportURL";
    public const string FamilyReportMemberLabel = "familyReportMemberLabel";
    public const string FamilyReportLastAttemptAt = "familyReportLastAttemptAt";
    public const string FamilyReportLastSuccessAt = "familyReportLastSuccessAt";
    public const string FamilyReportLastResult = "familyReportLastResult";
    public const string FamilyReportMigrationDone = "familyReportMigrationDone";
}

/// <summary>设置的默认值（和 Mac 版 @AppStorage 的初始值一致）。</summary>
public static class SettingsDefaults
{
    public const string AppLanguage = "system";
    public const string FilePath = "";
    public const string CliWorkingDirectory = "";
    public const int RefreshMinutes = 30;
    public const bool ShowAmountInMenuBar = true;
    public const string MenuBarMode = "cost";
    public const string HiddenProjects = "";
    public const string PinnedProjects = "";
    public const string TimeRange = "all";
    public const string RenewalNudgeDismissed = "";
    public const string SubscriptionOrder = "";
    public const bool CloudSyncEnabled = false;
    public const bool CloudSyncHideProjectNames = false;
    public const bool PublishEnabled = false;
    public const string PublishFrequency = "weekly";
    public const string PublishRepoPath = "";
    public const string PublishFilePath = "src/data/token-usage.json";
    public const string PublishBranch = "main";
    public const bool FamilyReportEnabled = false;
    public const string FamilyReportMode = "join";
    public const string FamilyReportUrl = "";
    public const string FamilyReportMemberLabel = "";
}

public enum PublishFrequency
{
    Daily,
    Weekly,
    Monthly,
}

public static class PublishFrequencies
{
    public static PublishFrequency? Parse(string? raw) => raw switch
    {
        "daily" => PublishFrequency.Daily,
        "weekly" => PublishFrequency.Weekly,
        "monthly" => PublishFrequency.Monthly,
        _ => null,
    };

    public static string RawValue(this PublishFrequency f) => f switch
    {
        PublishFrequency.Daily => "daily",
        PublishFrequency.Weekly => "weekly",
        PublishFrequency.Monthly => "monthly",
        _ => "weekly",
    };

    public static string Label(this PublishFrequency f) => f switch
    {
        PublishFrequency.Daily => L10n.Tr("settings.publish.frequency.daily"),
        PublishFrequency.Weekly => L10n.Tr("settings.publish.frequency.weekly"),
        _ => L10n.Tr("settings.publish.frequency.monthly"),
    };

    public static IReadOnlyList<PublishFrequency> All { get; } =
        [PublishFrequency.Daily, PublishFrequency.Weekly, PublishFrequency.Monthly];
}

public enum SourceKind
{
    File,
    Cli,
}

public static class SourceKinds
{
    public static SourceKind? Parse(string? raw) => raw switch
    {
        "file" => SourceKind.File,
        "cli" => SourceKind.Cli,
        _ => null,
    };

    public static string RawValue(this SourceKind k) => k == SourceKind.File ? "file" : "cli";

    public static string Label(this SourceKind k) =>
        k == SourceKind.File ? L10n.Tr("settings.source.file") : L10n.Tr("settings.source.cli");

    public static IReadOnlyList<SourceKind> All { get; } = [SourceKind.File, SourceKind.Cli];
}

public enum MenuBarMode
{
    Cost,
    Tokens,
}

public static class MenuBarModes
{
    public static MenuBarMode? Parse(string? raw) => raw switch
    {
        "cost" => MenuBarMode.Cost,
        "tokens" => MenuBarMode.Tokens,
        _ => null,
    };

    public static string RawValue(this MenuBarMode m) => m == MenuBarMode.Cost ? "cost" : "tokens";

    public static string Label(this MenuBarMode m) =>
        m == MenuBarMode.Cost ? L10n.Tr("settings.menubar.cost") : L10n.Tr("settings.menubar.tokens");

    public static IReadOnlyList<MenuBarMode> All { get; } = [MenuBarMode.Cost, MenuBarMode.Tokens];
}

public enum AppLanguage
{
    System,
    En,
    ZhHans,
    Fr,
}

public static class AppLanguages
{
    public static AppLanguage? Parse(string? raw) => raw switch
    {
        "system" => AppLanguage.System,
        "en" => AppLanguage.En,
        "zh-Hans" => AppLanguage.ZhHans,
        "fr" => AppLanguage.Fr,
        _ => null,
    };

    public static string RawValue(this AppLanguage l) => l switch
    {
        AppLanguage.System => "system",
        AppLanguage.En => "en",
        AppLanguage.ZhHans => "zh-Hans",
        _ => "fr",
    };

    /// <summary>在语言切换器中显示的名字（各语言使用其母语名称）。</summary>
    public static string DisplayName(this AppLanguage l) => l switch
    {
        AppLanguage.System => L10n.Tr("settings.language.system"),
        AppLanguage.En => "English",
        AppLanguage.ZhHans => "简体中文",
        _ => "Français",
    };

    public static IReadOnlyList<AppLanguage> All { get; } =
        [AppLanguage.System, AppLanguage.En, AppLanguage.ZhHans, AppLanguage.Fr];
}
