namespace Kanjo.Core;

/// <summary>
/// 数据源解析（App 和设置页共用一套，免得两处回退规则不一致）。
///
/// Mac 的规则（<c>ReportStore.init</c> / <c>makeSource</c>）：
/// <list type="bullet">
/// <item>默认来源 = 找得到 CLI 就用 CLI，否则用 JSON 文件；</item>
/// <item>JSON 文件来源下 <c>filePath</c> 留空才用示例数据 <c>sample.json</c>。</item>
/// </list>
/// 所以一个装了内置 CLI 的 Windows 安装包**永远**默认走 CLI，不会悄悄显示示例数据。
/// </summary>
public static class SourceResolution
{
    /// <summary>
    /// 实际生效的来源：设置里有值就用它，没有就按「找得到 CLI 吗」决定（和 Mac 的 register default 一致）。
    /// </summary>
    public static SourceKind Resolve(string? stored)
    {
        if (SourceKinds.Parse(stored) is { } parsed) return parsed;
        return DefaultKind();
    }

    /// <summary>默认来源：内置 / 仓库 / 安装的 CLI 存在就用 CLI，否则用 JSON 文件。</summary>
    public static SourceKind DefaultKind() =>
        DefaultPaths.CliDirectoryExists ? SourceKind.Cli : SourceKind.File;

    /// <summary>
    /// 文件来源下实际读哪个文件：<c>filePath</c> 留空时才是示例数据（Mac 的 <c>settings.file_note</c>）。
    /// </summary>
    public static string FileFor(string? storedPath) =>
        string.IsNullOrWhiteSpace(storedPath)
            ? DefaultPaths.SampleFixture
            : DefaultPaths.ExpandTilde(storedPath.Trim());

    /// <summary>
    /// 会不会显示示例数据：只有文件来源 + 路径留空时才是。
    /// 安装版（内置 CLI）默认走 CLI，所以不会出现。
    /// </summary>
    public static bool UsesSampleData(string? storedKind, string? storedPath) =>
        Resolve(storedKind) == SourceKind.File && string.IsNullOrWhiteSpace(storedPath);
}
