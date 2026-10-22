# Surge

Surge 配置里引用的外部规则镜像。GitHub Actions 每天从源头拉取一次，有变化就自动提交，所以这里的文件会跟着源头更新。

## 使用

把 Surge 配置里的源头地址换成下表里的地址，例如：

```ini
RULE-SET,https://raw.githubusercontent.com/hypsoma/Surge/main/rules/OpenAI.list,OpenAI,"update-interval=172800"
DOMAIN-SET,https://raw.githubusercontent.com/hypsoma/Surge/main/rules/adblocksurge.list,REJECT,"update-interval=604800"
```

`CN_IP.list` 和 `Google_IP.list` 在源头是纯 CIDR 列表，这里已经转换成 `IP-CIDR` / `IP-CIDR6` 规则，可以直接当 `RULE-SET` 用，不需要再经过 Script-Hub。

## 规则列表

下表由同步脚本自动生成。

<!-- sources:start -->
<!-- sources:end -->

## 同步机制

- 源头清单在 `sources.json`。每条写 `url` 和 `path`，`path` 必须在 `rules/` 下；可选字段有 `convert`、`license`、`note`。
- `"convert": "cidr"` 会把纯 CIDR 列表转换成 `IP-CIDR` / `IP-CIDR6` 规则。没有 `convert` 的文件按源头原样保存。
- 每天 UTC 03:30（北京时间 11:30）自动运行。推送对 `sources.json`、同步脚本或 workflow 的修改后也会立即运行。也可以在 Actions 页面手动运行。
- 某个源头下载失败、返回网页、没有任何规则，或者规则条数比上次少一半以上时，保留旧文件不覆盖，这次运行会标记为失败，GitHub 会发邮件通知。确认源头确实大幅删减后，可以手动运行并勾选 `force`。
- 从 `sources.json` 删掉的条目，对应文件会在下次同步时从 `rules/` 删除。

## 手动同步

```bash
python3 scripts/sync_surge_rules.py
```

## 版权

`rules/` 下的文件来自各自的源头仓库，版权和许可证归原作者，见上表。转换过的文件只改了规则格式，保留了原文件的注释。
