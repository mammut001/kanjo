namespace Kanjo.Core;

/// <summary>
/// Windows 版独有的文案覆盖：只放 Mac 版字符串表里没有、或必须按平台改写的句子。
/// 其余全部走 Mac 的 Localizable.strings（不复制翻译）。
/// </summary>
public static class WindowsL10n
{
    private static readonly Dictionary<string, Dictionary<string, string>> Overrides = new(StringComparer.Ordinal)
    {
        // 资源管理器没有「Finder」，菜单项直接说 Explorer。
        ["context.show_in_explorer"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Show in Explorer",
            ["zh-Hans"] = "在资源管理器中显示",
            ["fr"] = "Afficher dans l'Explorateur",
        },
        // Windows 上是回收站，不是废纸篓。
        ["disk.card.move_button"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Move to Recycle Bin",
            ["zh-Hans"] = "移到回收站",
            ["fr"] = "Mettre à la corbeille",
        },
        ["disk.card.moved_title"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Moved to Recycle Bin",
            ["zh-Hans"] = "已移到回收站",
            ["fr"] = "Déplacé dans la corbeille",
        },
        ["disk.card.confirm_title"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Move to Recycle Bin?",
            ["zh-Hans"] = "移到回收站？",
            ["fr"] = "Mettre à la corbeille ?",
        },
        ["disk.card.warning"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Files go to the Recycle Bin via kanjo disk clean. Nothing is deleted permanently.",
            ["zh-Hans"] = "文件由 kanjo disk clean 移到回收站，不会永久删除。",
            ["fr"] = "Les fichiers vont à la corbeille via kanjo disk clean. Rien n'est supprimé définitivement.",
        },
        ["disk.badge.reclaimable_help"] = new(StringComparer.Ordinal)
        {
            ["en"] = "The CLI can move this to the Recycle Bin. Numbers stay in the ledger after the files are gone.",
            ["zh-Hans"] = "CLI 可以把它移到回收站。文件清掉后，账本里的数字仍然保留。",
            ["fr"] = "La CLI peut le déplacer dans la corbeille. Les chiffres restent au registre après la suppression.",
        },
        ["disk.clean_help"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Runs kanjo disk clean --dry-run, then asks before moving files to the Recycle Bin.",
            ["zh-Hans"] = "先跑 kanjo disk clean --dry-run，确认后才把文件移到回收站。",
            ["fr"] = "Lance kanjo disk clean --dry-run, puis demande avant de déplacer les fichiers dans la corbeille.",
        },
        // Windows 上不经过 /bin/zsh，直接起子进程。
        ["settings.cli_note"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Runs as a subprocess and reads kanjo export JSON from stdout.",
            ["zh-Hans"] = "以子进程方式运行，从标准输出读取 kanjo export 的 JSON。",
            ["fr"] = "Exécuté comme sous-processus ; lit le JSON de kanjo export sur la sortie standard.",
        },
        // iCloud 同步是 Mac 独有的（Windows 版这一节只显示说明）。
        ["settings.icloud.windows_only"] = new(StringComparer.Ordinal)
        {
            ["en"] = "iCloud sync is Mac only. The Windows app skips the iPhone snapshot upload.",
            ["zh-Hans"] = "iCloud 同步是 Mac 专属功能，Windows 版不上传手机快照。",
            ["fr"] = "La synchronisation iCloud est réservée au Mac. L'application Windows n'envoie pas d'instantané iPhone.",
        },
        // 凭据存进 Windows 凭据管理器，不是 macOS Keychain。
        ["settings.family.token.prompt_message"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Paste the token provided by your family administrator. Stored securely in Windows Credential Manager.",
            ["zh-Hans"] = "粘贴家庭管理员提供的令牌。它安全地保存在 Windows 凭据管理器中。",
            ["fr"] = "Collez le jeton fourni par votre administrateur familial. Stocké dans le Gestionnaire d'identifiants Windows.",
        },
        ["settings.family.manager.desc"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Requires a VPS with Docker, a domain on Cloudflare, and a Firebase project. Once deployed, you can switch back to \"Join a family\" to report this PC's usage as well.",
            ["zh-Hans"] = "需要一台装了 Docker 的 VPS、Cloudflare 上的域名和一个 Firebase 项目。部署完成后可以切回「加入家庭」上报这台电脑的用量。",
            ["fr"] = "Nécessite un VPS avec Docker, un domaine sur Cloudflare et un projet Firebase. Une fois déployé, revenez à « Rejoindre une famille » pour rapporter l'usage de ce PC.",
        },
        // 托盘菜单：只在更新已经下载完、可以立刻装上时出现（Mac 版没有更新界面）。
        ["update.restart_to_install"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Restart to update",
            ["zh-Hans"] = "重启以更新",
            ["fr"] = "Redémarrer pour mettre à jour",
        },
        // 更新横幅（面板顶部）与设置页的 Updates 卡片。三语都在这一张表里，和其余 Windows 覆盖一致。
        ["update.section"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Updates",
            ["zh-Hans"] = "更新",
            ["fr"] = "Mises à jour",
        },
        ["update.version_label"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Current version",
            ["zh-Hans"] = "当前版本",
            ["fr"] = "Version actuelle",
        },
        ["update.check"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Check for updates",
            ["zh-Hans"] = "检查更新",
            ["fr"] = "Rechercher des mises à jour",
        },
        ["update.checking"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Checking for updates…",
            ["zh-Hans"] = "正在检查更新…",
            ["fr"] = "Recherche de mises à jour…",
        },
        ["update.downloading_button"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Downloading…",
            ["zh-Hans"] = "正在下载…",
            ["fr"] = "Téléchargement…",
        },
        ["update.up_to_date"] = new(StringComparer.Ordinal)
        {
            ["en"] = "You're up to date",
            ["zh-Hans"] = "已是最新版本",
            ["fr"] = "Vous êtes à jour",
        },
        ["update.downloading"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Downloading Kanjo %@… %d%%",
            ["zh-Hans"] = "正在下载 Kanjo %@… %d%%",
            ["fr"] = "Téléchargement de Kanjo %@… %d %%",
        },
        ["update.ready"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Kanjo %@ is ready",
            ["zh-Hans"] = "Kanjo %@ 已就绪",
            ["fr"] = "Kanjo %@ est prêt",
        },
        ["update.ready_hint"] = new(StringComparer.Ordinal)
        {
            ["en"] = "The new version opens a few seconds after restarting.",
            ["zh-Hans"] = "重启后几秒内就会打开新版本。",
            ["fr"] = "La nouvelle version s'ouvre quelques secondes après le redémarrage.",
        },
        ["update.failed"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Couldn't check for updates",
            ["zh-Hans"] = "检查更新失败",
            ["fr"] = "Impossible de rechercher des mises à jour",
        },
        ["update.idle"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Updates are checked automatically in the background.",
            ["zh-Hans"] = "更新会在后台自动检查。",
            ["fr"] = "Les mises à jour sont recherchées automatiquement en arrière-plan.",
        },
        ["update.last_checked"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Last checked today at %@",
            ["zh-Hans"] = "上次检查：今天 %@",
            ["fr"] = "Dernière vérification aujourd'hui à %@",
        },
        ["update.never_checked"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Not checked yet",
            ["zh-Hans"] = "还没有检查过",
            ["fr"] = "Pas encore vérifié",
        },
        ["update.not_installed"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Updates are only available in the installed version",
            ["zh-Hans"] = "只有安装版才能自动更新",
            ["fr"] = "Les mises à jour ne sont disponibles que dans la version installée",
        },
        ["update.dismiss"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Dismiss",
            ["zh-Hans"] = "关闭",
            ["fr"] = "Ignorer",
        },
        // 外观（Windows 专有；Mac 版跟随系统，没有这一节）。
        ["settings.section.appearance"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Appearance",
            ["zh-Hans"] = "外观",
            ["fr"] = "Apparence",
        },
        ["settings.appearance"] = new(StringComparer.Ordinal)
        {
            ["en"] = "App appearance",
            ["zh-Hans"] = "应用外观",
            ["fr"] = "Apparence de l'application",
        },
        ["settings.appearance.note"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Applies to this Windows app only. The Mac app follows the system setting.",
            ["zh-Hans"] = "只影响 Windows 版；Mac 版跟随系统设置。",
            ["fr"] = "S'applique à l'application Windows uniquement. L'app Mac suit le réglage système.",
        },
        ["settings.appearance.dark"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Dark",
            ["zh-Hans"] = "深色",
            ["fr"] = "Sombre",
        },
        ["settings.appearance.light"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Light",
            ["zh-Hans"] = "浅色",
            ["fr"] = "Clair",
        },
        ["settings.appearance.system"] = new(StringComparer.Ordinal)
        {
            ["en"] = "Use system setting",
            ["zh-Hans"] = "跟随系统",
            ["fr"] = "Suivre le système",
        },
    };

    /// <summary>取覆盖文案；没有覆盖的 key 回退到 Mac 字符串表。</summary>
    public static string Tr(string key, params object?[] args) => TrL(null, key, args);

    /// <summary>取覆盖文案（显式指定语言，测试 / 截图用）。</summary>
    public static string TrL(string? language, string key, params object?[] args)
    {
        var lang = language ?? L10n.CurrentLanguage;
        if (Overrides.TryGetValue(key, out var table))
        {
            var format = table.TryGetValue(lang, out var localized)
                ? localized
                : table.GetValueOrDefault(L10n.DefaultLanguage, key);
            return args.Length == 0 ? format : L10n.Format(format, args);
        }
        return L10n.TrL(language, key, args);
    }

    /// <summary>某个 key 是否有 Windows 覆盖（测试用）。</summary>
    public static bool HasOverride(string key) => Overrides.ContainsKey(key);
}
