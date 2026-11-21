namespace Kanjo.Core;

public static class AntigravityAccountLogic
{
    public static string LocalPart(string email)
    {
        var at = email.IndexOf('@');
        return at >= 0 ? email[..at] : email;
    }

    /// <summary>两个账号 local part 相同时显示完整邮箱，否则只显示 local part。</summary>
    public static string DisplayName(string email, IReadOnlyList<string> emails)
    {
        var lp = LocalPart(email);
        var lower = email.ToLowerInvariant();
        var shares = emails.Any(e =>
            !e.Equals(email, StringComparison.OrdinalIgnoreCase) &&
            LocalPart(e).Equals(lp, StringComparison.Ordinal));
        return shares ? email : lp;
    }

    public static string DisplayName(AntigravityAccount account, IReadOnlyList<AntigravityAccount> accounts) =>
        DisplayName(account.Email, accounts.Select(a => a.Email).ToList());
}