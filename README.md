# GitHub 趋势微信推送

每天北京时间 17:06 获取 [GitHub Trending](https://github.com/trending) 的每周榜、每月榜前三名，通过 GitHub Models 生成简短中文说明，再由 Server酱推送到微信。

脚本会保存本次两个榜单的项目。下一次运行时，任何已出现在前一次周榜或月榜前三名中的项目都不会再次推送；没有新入选项目时不发送消息。

中文总结使用工作流自动生成的临时 `GITHUB_TOKEN`，不需要配置额外的 AI API Key。模型暂时不可用时会自动使用 GitHub 原始项目简介，推送任务不会因此中断。

## 部署

1. 在 GitHub 新建仓库，把本目录内容推送到仓库默认分支。
2. 打开 [Server酱](https://sct.ftqq.com)，微信扫码登录并复制 `SendKey`。
3. 在 GitHub 仓库进入 `Settings` → `Secrets and variables` → `Actions`，新建 Repository secret：
   - Name：`SERVERCHAN_SENDKEY`
   - Secret：上一步复制的 SendKey
4. 进入仓库的 `Actions` 页面，启用工作流，并手动运行一次 `Daily GitHub Trending` 验证推送。

定时工作流使用 GitHub Actions 的 `Asia/Shanghai` 时区配置。GitHub 在任务高峰时可能延迟执行，因此 17:06 是计划时间，并非秒级准点保证。

## 本地验证

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python trending_notifier.py --dry-run
```

`--dry-run` 只打印当前新入选项目，不推送，也不更新 `data/state.json`。

## 手动运行并推送

```powershell
$env:SERVERCHAN_SENDKEY = "你的 SendKey"
python trending_notifier.py
```

不要把 SendKey 写进源码或提交到 Git。
