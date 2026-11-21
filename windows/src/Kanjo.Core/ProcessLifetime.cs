using System.Diagnostics;

namespace Kanjo.Core;

/// <summary>Tracks CLI processes until completion and terminates them on shutdown.</summary>
public sealed class ProcessLifetime : IDisposable
{
    private readonly object Lock = new();
    private readonly HashSet<Process> Processes = [];
    private bool _stopping;

    public static ProcessLifetime Shared { get; } = new();

    static ProcessLifetime() => AppDomain.CurrentDomain.ProcessExit += (_, _) => Shared.Dispose();

    public IDisposable Track(Process process)
    {
        lock (Lock)
        {
            if (_stopping) Kill(process);
            else Processes.Add(process);
        }
        return new Registration(this, process);
    }

    public void Dispose()
    {
        lock (Lock)
        {
            _stopping = true;
            foreach (var process in Processes) Kill(process);
        }
    }

    public static void Kill(Process process)
    {
        try { process.Kill(entireProcessTree: true); }
        catch (Exception e) when (e is InvalidOperationException or System.ComponentModel.Win32Exception or NotSupportedException) { }
    }

    private sealed class Registration(ProcessLifetime owner, Process process) : IDisposable
    {
        public void Dispose() { lock (owner.Lock) owner.Processes.Remove(process); }
    }
}
