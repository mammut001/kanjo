using System.Collections;

namespace Kanjo.Core;

/// <summary>
/// 只读列表，带结构相等（Swift 的 Array 值语义）。模型里的数组字段都用它，
/// 这样 record 的 == / Equals 比较的是内容而不是引用。
/// </summary>
public sealed class RoList<T> : IReadOnlyList<T>, IEquatable<RoList<T>>
{
    private readonly List<T> _items;

    public static readonly RoList<T> Empty = new(new List<T>());

    public RoList()
    {
        _items = [];
    }

    public RoList(IEnumerable<T> items)
    {
        _items = items as List<T> ?? [.. items];
    }

    /// <summary>集合表达式 `[a, b]` 支持（C# collection expression 需要 Add）。</summary>
    public void Add(T item) => _items.Add(item);

    public int Count => _items.Count;

    public T this[int index] => _items[index];

    public IEnumerator<T> GetEnumerator() => _items.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();

    public bool Equals(RoList<T>? other)
    {
        if (other is null) return false;
        if (ReferenceEquals(this, other)) return true;
        if (_items.Count != other._items.Count) return false;
        var comparer = EqualityComparer<T>.Default;
        for (var i = 0; i < _items.Count; i++)
        {
            if (!comparer.Equals(_items[i], other._items[i])) return false;
        }
        return true;
    }

    public override bool Equals(object? obj) => obj is RoList<T> other && Equals(other);

    public override int GetHashCode()
    {
        var hash = new HashCode();
        foreach (var item in _items) hash.Add(item);
        return hash.ToHashCode();
    }

    public override string ToString() => $"[{string.Join(", ", _items)}]";

    public static bool operator ==(RoList<T>? a, RoList<T>? b) => a is null ? b is null : a.Equals(b);

    public static bool operator !=(RoList<T>? a, RoList<T>? b) => !(a == b);

    public static implicit operator RoList<T>(List<T>? items) => items is null ? Empty : new RoList<T>(items);

    public static implicit operator RoList<T>(T[]? items) => items is null ? Empty : new RoList<T>(items);

    public List<T> ToList() => [.. _items];
}

/// <summary>只读字典，带结构相等（键 → 值逐项比较）。</summary>
public sealed class RoDict<TValue> : IReadOnlyDictionary<string, TValue>, IEquatable<RoDict<TValue>>
{
    private readonly Dictionary<string, TValue> _items;

    public RoDict()
    {
        _items = new Dictionary<string, TValue>(StringComparer.Ordinal);
    }

    public RoDict(IEnumerable<KeyValuePair<string, TValue>> items)
    {
        _items = new Dictionary<string, TValue>(StringComparer.Ordinal);
        foreach (var (key, value) in items) _items[key] = value;
    }

    public RoDict(Dictionary<string, TValue> items)
    {
        _items = new Dictionary<string, TValue>(items, StringComparer.Ordinal);
    }

    public TValue this[string key] => _items[key];

    public IEnumerable<string> Keys => _items.Keys;

    public IEnumerable<TValue> Values => _items.Values;

    public int Count => _items.Count;

    public bool ContainsKey(string key) => _items.ContainsKey(key);

    public bool TryGetValue(string key, out TValue value) => _items.TryGetValue(key, out value!);

    public TValue GetValueOrDefault(string key) => _items.GetValueOrDefault(key)!;

    public TValue GetValueOrDefault(string key, TValue fallback) =>
        _items.TryGetValue(key, out var value) ? value : fallback;

    public IEnumerator<KeyValuePair<string, TValue>> GetEnumerator() => _items.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();

    public bool Equals(RoDict<TValue>? other)
    {
        if (other is null) return false;
        if (ReferenceEquals(this, other)) return true;
        if (_items.Count != other._items.Count) return false;
        var comparer = EqualityComparer<TValue>.Default;
        foreach (var (key, value) in _items)
        {
            if (!other._items.TryGetValue(key, out var otherValue)) return false;
            if (!comparer.Equals(value, otherValue)) return false;
        }
        return true;
    }

    public override bool Equals(object? obj) => obj is RoDict<TValue> other && Equals(other);

    public override int GetHashCode()
    {
        var hash = new HashCode();
        foreach (var (key, value) in _items.OrderBy(kv => kv.Key, StringComparer.Ordinal))
        {
            hash.Add(key);
            hash.Add(value);
        }
        return hash.ToHashCode();
    }

    public static bool operator ==(RoDict<TValue>? a, RoDict<TValue>? b) => a is null ? b is null : a.Equals(b);

    public static bool operator !=(RoDict<TValue>? a, RoDict<TValue>? b) => !(a == b);

    public static implicit operator RoDict<TValue>(Dictionary<string, TValue>? items) =>
        items is null ? new RoDict<TValue>() : new RoDict<TValue>(items);

    public Dictionary<string, TValue> ToDictionary() => new(_items, StringComparer.Ordinal);
}
