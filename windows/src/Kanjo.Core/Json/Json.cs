using System.Globalization;
using System.Text.Json;

namespace Kanjo.Core;

/// <summary>解码过程中抛出的字段级错误，最后会被包成 <see cref="DataSourceError.ContractMismatch"/>。</summary>
public sealed class DecodeError(string message) : Exception(message);

/// <summary>
/// 严格的 JSON 读取工具：必填字段缺失 / 类型不对时抛出带字段路径的 <see cref="DecodeError"/>，
/// 路径写法与 Mac 版一致（<c>projects[1].by_day</c>）。
/// </summary>
public static class J
{
    public static string Child(string path, string key) => path.Length == 0 ? key : path + "." + key;

    public static string Index(string path, int index) => path + "[" + index.ToString(CultureInfo.InvariantCulture) + "]";

    public static JsonElement Object(JsonElement element, string path)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            throw new DecodeError($"wrong type at {path} (expected object)");
        }
        return element;
    }

    public static JsonElement Required(JsonElement obj, string key, string path)
    {
        if (obj.ValueKind != JsonValueKind.Object || !obj.TryGetProperty(key, out var value))
        {
            throw new DecodeError($"missing field {Child(path, key)}");
        }
        return value;
    }

    public static JsonElement? Optional(JsonElement obj, string key)
    {
        if (obj.ValueKind != JsonValueKind.Object || !obj.TryGetProperty(key, out var value)) return null;
        return value.ValueKind == JsonValueKind.Null ? null : value;
    }

    public static JsonElement RequiredObject(JsonElement obj, string key, string path) =>
        Object(Required(obj, key, path), Child(path, key));

    public static double Number(JsonElement obj, string key, string path) =>
        ToDouble(Required(obj, key, path), Child(path, key));

    public static double? NumberOrNull(JsonElement obj, string key, string path)
    {
        var value = Optional(obj, key);
        return value is null ? null : ToDouble(value.Value, Child(path, key));
    }

    public static int Int(JsonElement obj, string key, string path) =>
        ToInt(Required(obj, key, path), Child(path, key));

    public static int? IntOrNull(JsonElement obj, string key, string path)
    {
        var value = Optional(obj, key);
        return value is null ? null : ToInt(value.Value, Child(path, key));
    }

    public static long Long(JsonElement obj, string key, string path) =>
        ToLong(Required(obj, key, path), Child(path, key));

    public static long? LongOrNull(JsonElement obj, string key, string path)
    {
        var value = Optional(obj, key);
        return value is null ? null : ToLong(value.Value, Child(path, key));
    }

    public static long ToLong(JsonElement element, string path)
    {
        if (element.ValueKind == JsonValueKind.Null)
        {
            throw new DecodeError($"null at {path} (expected integer)");
        }
        if (element.ValueKind != JsonValueKind.Number)
        {
            throw new DecodeError($"wrong type at {path} (expected integer)");
        }
        if (element.TryGetInt64(out var l)) return l;
        var d = element.GetDouble();
        if (Math.Abs(d - Math.Round(d)) < 1e-9 && d is >= long.MinValue and <= long.MaxValue)
        {
            return (long)Math.Round(d);
        }
        throw new DecodeError($"wrong type at {path} (expected integer)");
    }

    public static string String(JsonElement obj, string key, string path) =>
        ToString(Required(obj, key, path), Child(path, key));

    public static string? StringOrNull(JsonElement obj, string key, string path)
    {
        var value = Optional(obj, key);
        return value is null ? null : ToString(value.Value, Child(path, key));
    }

    public static bool Bool(JsonElement obj, string key, string path) =>
        ToBool(Required(obj, key, path), Child(path, key));

    public static bool? BoolOrNull(JsonElement obj, string key, string path)
    {
        var value = Optional(obj, key);
        return value is null ? null : ToBool(value.Value, Child(path, key));
    }

    public static JsonElement Array(JsonElement obj, string key, string path) =>
        ToArray(Required(obj, key, path), Child(path, key));

    public static JsonElement? ArrayOrNull(JsonElement obj, string key, string path)
    {
        var value = Optional(obj, key);
        return value is null ? null : ToArray(value.Value, Child(path, key));
    }

    public static double ToDouble(JsonElement element, string path)
    {
        if (element.ValueKind == JsonValueKind.Null)
        {
            throw new DecodeError($"null at {path} (expected number)");
        }
        if (element.ValueKind != JsonValueKind.Number)
        {
            throw new DecodeError($"wrong type at {path} (expected number)");
        }
        return element.GetDouble();
    }

    public static int ToInt(JsonElement element, string path)
    {
        if (element.ValueKind == JsonValueKind.Null)
        {
            throw new DecodeError($"null at {path} (expected integer)");
        }
        if (element.ValueKind != JsonValueKind.Number)
        {
            throw new DecodeError($"wrong type at {path} (expected integer)");
        }
        if (element.TryGetInt64(out var l) && l is >= int.MinValue and <= int.MaxValue)
        {
            return (int)l;
        }
        var d = element.GetDouble();
        if (Math.Abs(d - Math.Round(d)) < 1e-9 && d is >= int.MinValue and <= int.MaxValue)
        {
            return (int)Math.Round(d);
        }
        throw new DecodeError($"wrong type at {path} (expected integer)");
    }

    public static string ToString(JsonElement element, string path)
    {
        if (element.ValueKind == JsonValueKind.Null)
        {
            throw new DecodeError($"null at {path} (expected string)");
        }
        if (element.ValueKind != JsonValueKind.String)
        {
            throw new DecodeError($"wrong type at {path} (expected string)");
        }
        return element.GetString() ?? string.Empty;
    }

    public static bool ToBool(JsonElement element, string path)
    {
        return element.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Null => throw new DecodeError($"null at {path} (expected bool)"),
            _ => throw new DecodeError($"wrong type at {path} (expected bool)"),
        };
    }

    public static JsonElement ToArray(JsonElement element, string path)
    {
        if (element.ValueKind == JsonValueKind.Null)
        {
            throw new DecodeError($"null at {path} (expected array)");
        }
        if (element.ValueKind != JsonValueKind.Array)
        {
            throw new DecodeError($"wrong type at {path} (expected array)");
        }
        return element;
    }

    /// <summary>遍历对象的所有属性（键 → 值）。非对象视为类型错误。</summary>
    public static IEnumerable<(string Key, JsonElement Value)> Properties(JsonElement obj, string path)
    {
        Object(obj, path);
        foreach (var p in obj.EnumerateObject())
        {
            yield return (p.Name, p.Value);
        }
    }

    public static List<T> List<T>(JsonElement? array, string path, Func<JsonElement, string, T> decode)
    {
        if (array is null) return [];
        var element = ToArray(array.Value, path);
        var result = new List<T>();
        var i = 0;
        foreach (var item in element.EnumerateArray())
        {
            result.Add(decode(item, Index(path, i)));
            i++;
        }
        return result;
    }

    public static Dictionary<string, T> Dict<T>(JsonElement? obj, string path, Func<JsonElement, string, T> decode)
    {
        var result = new Dictionary<string, T>(StringComparer.Ordinal);
        if (obj is null) return result;
        foreach (var (key, value) in Properties(obj.Value, path))
        {
            result[key] = decode(value, Child(path, key));
        }
        return result;
    }

    public static Dictionary<string, double> DoubleDict(JsonElement? obj, string path)
    {
        var result = new Dictionary<string, double>(StringComparer.Ordinal);
        if (obj is null) return result;
        foreach (var (key, value) in Properties(obj.Value, path))
        {
            result[key] = ToDouble(value, Child(path, key));
        }
        return result;
    }

    public static Dictionary<string, int> IntDict(JsonElement? obj, string path)
    {
        var result = new Dictionary<string, int>(StringComparer.Ordinal);
        if (obj is null) return result;
        foreach (var (key, value) in Properties(obj.Value, path))
        {
            result[key] = ToInt(value, Child(path, key));
        }
        return result;
    }
}
