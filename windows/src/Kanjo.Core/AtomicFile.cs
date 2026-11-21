using System.Text;

namespace Kanjo.Core;

internal static class AtomicFile
{
    internal static void WriteAllText(string path, string content, Action<string, string>? write = null)
    {
        var fullPath = Path.GetFullPath(path);
        var directory = Path.GetDirectoryName(fullPath)!;
        Directory.CreateDirectory(directory);
        var temporary = Path.Combine(directory, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            (write ?? ((p, text) => File.WriteAllText(p, text, new UTF8Encoding(false))))(temporary, content);
            File.Move(temporary, fullPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }
}
