# Tabular Quality

这个受信、只读的教学 Skill 接收平台已经绑定的表格 JSON，返回行数、逐列空值计数和简短告警。它不
读取宿主路径、不访问网络，也不写入外部系统。

教学版会在应用进程内加载仓库自带的 entrypoint，因此它不是不受信代码沙箱。只有经过本地清单注册、
被当前 Scenario 授权且 `effect: read` 的 executable Skill 才能进入通用 `skill` Plan step。
