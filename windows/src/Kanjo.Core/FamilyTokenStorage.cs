using System.Runtime.InteropServices;
using System.Text;

namespace Kanjo.Core;

/// <summary>家庭上报令牌的存储（对应 Mac 的 Keychain）。<see cref="Target"/> 是存储里的条目名。</summary>
public interface IFamilyTokenStorage
{
    string Target { get; }

    string? LoadToken();

    bool SaveToken(string token);

    bool DeleteToken();

    bool HasToken();
}

/// <summary>内存实现：测试和非 Windows 开发运行用（绝不写真实凭据）。</summary>
public sealed class InMemoryFamilyTokenStorage : IFamilyTokenStorage
{
    private readonly object _lock = new();
    private string? _token;

    public string Target { get; }

    public InMemoryFamilyTokenStorage(string target = "KanjoFamilyReport", string? initialToken = null)
    {
        Target = target;
        _token = initialToken;
    }

    public string? LoadToken()
    {
        lock (_lock) return _token;
    }

    public bool SaveToken(string token)
    {
        lock (_lock) _token = token;
        return true;
    }

    public bool DeleteToken()
    {
        lock (_lock) _token = null;
        return true;
    }

    public bool HasToken()
    {
        lock (_lock) return !string.IsNullOrEmpty(_token);
    }
}

/// <summary>
/// Windows 凭据管理器（Generic 凭据，目标名 <c>KanjoFamilyReport</c>），P/Invoke advapi32 的
/// CredRead / CredWrite / CredDelete，和 Mac 的 Keychain 一样「只在本机、只对这个用户」。
/// 非 Windows 上退回内存实现，开发运行不会碰任何真实凭据。
/// </summary>
public sealed class WindowsCredentialFamilyTokenStorage : IFamilyTokenStorage
{
    private const uint CredTypeGeneric = 1;
    private const uint CredPersistLocalMachine = 2;
    private const int ErrorNotFound = 1168;
    private const int ErrorNoSuchLogonSession = 1312;

    private readonly IFamilyTokenStorage _fallback;

    public string Target { get; }

    public WindowsCredentialFamilyTokenStorage(string target = "KanjoFamilyReport")
    {
        Target = target;
        _fallback = new InMemoryFamilyTokenStorage(target);
    }

    public static bool IsSupported => OperatingSystem.IsWindows();

    public string? LoadToken()
    {
        if (!IsSupported) return _fallback.LoadToken();
        if (!CredReadW(Target, CredTypeGeneric, 0, out var handle)) return null;
        try
        {
            var credential = Marshal.PtrToStructure<NativeCredential>(handle);
            if (credential.CredentialBlobSize == 0 || credential.CredentialBlob == IntPtr.Zero) return null;
            var bytes = new byte[credential.CredentialBlobSize];
            Marshal.Copy(credential.CredentialBlob, bytes, 0, bytes.Length);
            return Encoding.Unicode.GetString(bytes);
        }
        finally
        {
            CredFree(handle);
        }
    }

    public bool SaveToken(string token)
    {
        if (!IsSupported) return _fallback.SaveToken(token);
        var bytes = Encoding.Unicode.GetBytes(token);
        var blob = Marshal.AllocHGlobal(bytes.Length);
        try
        {
            Marshal.Copy(bytes, 0, blob, bytes.Length);
            var credential = new NativeCredential
            {
                Type = CredTypeGeneric,
                TargetName = Target,
                CredentialBlobSize = (uint)bytes.Length,
                CredentialBlob = blob,
                Persist = CredPersistLocalMachine,
                UserName = Environment.UserName,
            };
            return CredWriteW(ref credential, 0);
        }
        finally
        {
            Marshal.FreeHGlobal(blob);
        }
    }

    public bool DeleteToken()
    {
        if (!IsSupported) return _fallback.DeleteToken();
        if (CredDeleteW(Target, CredTypeGeneric, 0)) return true;
        var error = Marshal.GetLastWin32Error();
        return error is ErrorNotFound or ErrorNoSuchLogonSession;
    }

    public bool HasToken()
    {
        if (!IsSupported) return _fallback.HasToken();
        if (!CredReadW(Target, CredTypeGeneric, 0, out var handle)) return false;
        CredFree(handle);
        return true;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct NativeCredential
    {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public string? Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string? TargetAlias;
        public string UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredReadW(string target, uint type, uint flags, out IntPtr credential);

    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWriteW([In] ref NativeCredential credential, uint flags);

    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredDeleteW(string target, uint type, uint flags);

    [DllImport("advapi32.dll", EntryPoint = "CredFree", SetLastError = true)]
    private static extern void CredFree(IntPtr buffer);
}
