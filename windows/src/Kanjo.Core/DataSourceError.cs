namespace Kanjo.Core;

/// <summary>数据源错误。文案与 Mac 版 <c>DataSourceError</c> 保持一致（英文）。</summary>
public enum DataSourceErrorKind
{
    FileNotFound,
    Unreadable,
    EmptyInput,
    InvalidJson,
    ContractMismatch,
    CommandFailed,
    CommandTimedOut,
    LaunchFailed,
}

public sealed class DataSourceError : Exception
{
    public DataSourceErrorKind Kind { get; }

    public string Text => Message;

    private DataSourceError(DataSourceErrorKind kind, string text) : base(text) => Kind = kind;

    public static DataSourceError FileNotFound(string path) =>
        new(DataSourceErrorKind.FileNotFound, $"Data file not found: {path}");

    public static DataSourceError Unreadable(string path, string why) =>
        new(DataSourceErrorKind.Unreadable, $"Cannot read {path}: {why}");

    public static DataSourceError EmptyInput(string what) =>
        new(DataSourceErrorKind.EmptyInput, $"{what} is empty — expected kanjo export JSON.");

    public static DataSourceError InvalidJson(string why) =>
        new(DataSourceErrorKind.InvalidJson, $"Not valid JSON: {why}");

    public static DataSourceError ContractMismatch(string why, int? schemaVersion)
    {
        var text = $"JSON does not match the kanjo data contract: {why}";
        if (schemaVersion is { } v && v > Contract.SupportedSchemaVersion)
        {
            text += $"\n(schema_version {v} is newer than this app supports ({Contract.SupportedSchemaVersion}); update the app.)";
        }
        return new DataSourceError(DataSourceErrorKind.ContractMismatch, text);
    }

    public static DataSourceError CommandFailed(string command, int status, string stderr)
    {
        var tail = (stderr ?? string.Empty).Trim();
        var text = $"Command exited with status {status}: {command}";
        if (tail.Length > 0)
        {
            text += "\n" + (tail.Length > 600 ? tail[^600..] : tail);
        }
        return new DataSourceError(DataSourceErrorKind.CommandFailed, text);
    }

    public static DataSourceError CommandTimedOut(string command, int seconds) =>
        new(DataSourceErrorKind.CommandTimedOut, $"Command timed out after {seconds}s: {command}");

    public static DataSourceError LaunchFailed(string why) =>
        new(DataSourceErrorKind.LaunchFailed, $"Could not start command: {why}");
}
