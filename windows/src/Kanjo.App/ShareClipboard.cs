using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace Kanjo.App;

/// <summary>
/// 把分享图放上剪贴板：注册的 PNG 格式（浏览器、X、Teams）和 CF_DIB（画图、Word）。
/// 只有 Windows 会真的写剪贴板；其它系统返回 false。失败记一条日志，不把异常抛回界面。
/// </summary>
public static class ShareClipboard
{
    /// <summary>
    /// <paramref name="bgra"/> 是自上而下的 BGRA8888，长度必须是 <c>width * height * 4</c>。
    /// </summary>
    public static bool TrySetPng(byte[] png, int width, int height, byte[] bgra)
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            if (png.Length == 0 || width <= 0 || height <= 0) return false;
            if (bgra.Length != width * height * 4) return false;
            return Native.Set(png, Dib(width, height, bgra));
        }
        catch (Exception e)
        {
            Trace.WriteLine($"kanjo: clipboard failed: {e.Message}");
            return false;
        }
    }

    /// <summary>CF_DIB：BITMAPINFOHEADER + 自下而上的 32 位 BI_RGB。</summary>
    private static byte[] Dib(int width, int height, byte[] bgraTopDown)
    {
        const int header = 40;
        var stride = width * 4;
        var dib = new byte[header + stride * height];
        WriteInt32(dib, 0, header);
        WriteInt32(dib, 4, width);
        WriteInt32(dib, 8, height);
        WriteInt16(dib, 12, 1);
        WriteInt16(dib, 14, 32);
        WriteInt32(dib, 20, stride * height);
        for (var y = 0; y < height; y++)
        {
            var src = y * stride;
            var dst = header + (height - 1 - y) * stride;
            Buffer.BlockCopy(bgraTopDown, src, dib, dst, stride);
        }
        return dib;
    }

    private static void WriteInt32(byte[] buffer, int offset, int value)
    {
        buffer[offset] = (byte)value;
        buffer[offset + 1] = (byte)(value >> 8);
        buffer[offset + 2] = (byte)(value >> 16);
        buffer[offset + 3] = (byte)(value >> 24);
    }

    private static void WriteInt16(byte[] buffer, int offset, short value)
    {
        buffer[offset] = (byte)value;
        buffer[offset + 1] = (byte)(value >> 8);
    }

    [SupportedOSPlatform("windows")]
    private static class Native
    {
        private const uint CfDib = 8;
        private const uint GmemMoveable = 0x0002;

        internal static bool Set(byte[] png, byte[] dib)
        {
            if (!Open())
            {
                Trace.WriteLine("kanjo: OpenClipboard failed");
                return false;
            }

            try
            {
                if (!EmptyClipboard())
                {
                    Trace.WriteLine("kanjo: EmptyClipboard failed");
                    return false;
                }

                var pngFormat = RegisterClipboardFormat("PNG");
                if (pngFormat == 0)
                {
                    Trace.WriteLine("kanjo: RegisterClipboardFormat(PNG) failed");
                    return false;
                }

                if (!Put(pngFormat, png) || !Put(CfDib, dib)) return false;
                return true;
            }
            finally
            {
                CloseClipboard();
            }
        }

        private static bool Open()
        {
            for (var i = 0; i < 5; i++)
            {
                if (OpenClipboard(IntPtr.Zero)) return true;
                Thread.Sleep(15);
            }
            return false;
        }

        /// <summary>成功后内存归系统所有，不能再 Free。</summary>
        private static bool Put(uint format, byte[] data)
        {
            var mem = GlobalAlloc(GmemMoveable, (nuint)data.Length);
            if (mem == IntPtr.Zero) return false;
            var ptr = GlobalLock(mem);
            if (ptr == IntPtr.Zero)
            {
                GlobalFree(mem);
                return false;
            }

            Marshal.Copy(data, 0, ptr, data.Length);
            GlobalUnlock(mem);
            if (SetClipboardData(format, mem) == IntPtr.Zero)
            {
                GlobalFree(mem);
                Trace.WriteLine($"kanjo: SetClipboardData({format}) failed");
                return false;
            }
            return true;
        }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool OpenClipboard(IntPtr hWndNewOwner);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool CloseClipboard();

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool EmptyClipboard();

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr SetClipboardData(uint uFormat, IntPtr hMem);

        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern uint RegisterClipboardFormat(string lpszFormat);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr GlobalAlloc(uint uFlags, nuint dwBytes);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr GlobalLock(IntPtr hMem);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GlobalUnlock(IntPtr hMem);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr GlobalFree(IntPtr hMem);
    }
}
