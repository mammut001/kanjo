// L10n / DefaultPaths 有几处进程级状态（当前语言、设置存储），测试串行跑才能保证确定性。
// 这些都是纯逻辑测试，串行总耗时仍在毫秒级。
[assembly: Xunit.CollectionBehavior(DisableTestParallelization = true)]
