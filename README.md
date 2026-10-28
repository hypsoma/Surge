# Surge

Surge 配置里引用的外部规则镜像，以及自己写的模块。GitHub Actions 每天从源头拉取一次，有变化就自动提交，所以这里的文件会跟着源头更新。

## 使用

把 Surge 配置里的源头地址换成下表里的地址，例如：

```ini
RULE-SET,https://raw.githubusercontent.com/hypsoma/Surge/main/rules/OpenAI.list,OpenAI,"update-interval=172800"
DOMAIN-SET,https://raw.githubusercontent.com/hypsoma/Surge/main/rules/adblocksurge.list,REJECT,"update-interval=604800"
```

`CN_IP.list` 和 `Google_IP.list` 在源头是纯 CIDR 列表，这里已经转换成 `IP-CIDR` / `IP-CIDR6` 规则，可以直接当 `RULE-SET` 用，不需要再经过 Script-Hub。

## 模块

| 模块 | 订阅地址 | 说明 |
| --- | --- | --- |
| E-IX 面板 | `https://raw.githubusercontent.com/hypsoma/Surge/main/modules/E-IX.sgmodule` | 在 Surge 面板里显示 E-IX 的套餐、流量、重置日、到期时间、在线设备和余额 |

在 Surge 的模块设置里选择从 URL 安装，填入订阅地址即可。E-IX 面板需要 MITM：用浏览器打开一次 E-IX 网页，cloud.e-ix.com 或 e-ix.cloud 都可以（旧域名 ap.cdn.e-ix.com 会自动跳转），就会自动获取登录 token，也可以在模块参数 `TOKEN` 里手动填写，详见模块参数说明。

## 规则列表

下表由同步脚本自动生成。

<!-- sources:start -->
| 文件 | 规则数 | 源头 | 许可证 | 说明 |
| --- | ---: | --- | --- | --- |
| [adblocksurge.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/adblocksurge.list) | 241184 | [217heidai/adblockfilters](https://raw.githubusercontent.com/217heidai/adblockfilters/main/rules/adblocksurge.list) | GPL-3.0 | DOMAIN-SET 去广告 |
| [CN_ASN.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/CN_ASN.list) | 5231 | [Kwisma/ASN-List](https://raw.githubusercontent.com/Kwisma/ASN-List/main/country/CN/CN_ASN.list) | GPL-3.0 |  |
| [CN_IP.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/CN_IP.list) | 56395 | [Kwisma/ASN-List](https://raw.githubusercontent.com/Kwisma/ASN-List/main/country/CN/CN_IP.list) | GPL-3.0 | 已从纯 CIDR 转换 |
| [Tencent_ASN.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/Tencent_ASN.list) | 6 | [Kwisma/ASN-List](https://raw.githubusercontent.com/Kwisma/ASN-List/main/data/Tencent/Tencent_ASN.list) | GPL-3.0 |  |
| [anthropic.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/anthropic.list) | 52 | [VPSDance/ai-proxy-rules](https://raw.githubusercontent.com/VPSDance/ai-proxy-rules/main/rules/surge/anthropic.list) | MIT |  |
| [OpenAI.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/OpenAI.list) | 35 | [blackmatrix7/ios_rule_script](https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Surge/OpenAI/OpenAI.list) | GPL-2.0 |  |
| [Gemini.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/Gemini.list) | 13 | [blackmatrix7/ios_rule_script](https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Surge/Gemini/Gemini.list) | GPL-2.0 |  |
| [Binance.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/Binance.list) | 12 | [blackmatrix7/ios_rule_script](https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Surge/Binance/Binance.list) | GPL-2.0 |  |
| [Google_ASN.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/Google_ASN.list) | 45 | [Kwisma/ASN-List](https://raw.githubusercontent.com/Kwisma/ASN-List/main/data/Google/Google_ASN.list) | GPL-3.0 |  |
| [Google_IP.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/Google_IP.list) | 9054 | [Kwisma/ASN-List](https://raw.githubusercontent.com/Kwisma/ASN-List/main/data/Google/Google_IP.list) | GPL-3.0 | 已从纯 CIDR 转换 |
| [Twitter_ASN.list](https://raw.githubusercontent.com/hypsoma/Surge/main/rules/Twitter_ASN.list) | 4 | [Kwisma/ASN-List](https://raw.githubusercontent.com/Kwisma/ASN-List/main/data/Twitter/Twitter_ASN.list) | GPL-3.0 |  |
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
