# 雀魂实时助手

本项目是一个本地运行的雀魂四人日麻辅助工具。它通过 Chrome DevTools 监听雀魂网页版 websocket，对实时动作做 protobuf 解包，维护当前局面状态，并在摸牌、副露、立直、防守等关键节点给出规则型建议。

当前定位：可实战试用的中上级规则助手。它能稳定处理常规牌效、基础攻守、立直/默听、副露取舍和牌谱回放评估，但不是 MAKA/Seer 级别的完整搜索或神经网络 AI。

## 亮点

- 实时链路完整：Chrome DevTools -> websocket 帧 -> protobuf 解包 -> 局面状态机 -> 本地建议。
- 不依赖外部服务：核心推荐逻辑在本地运行，适合调试和复现。
- 可回放评估：支持从原始牌谱重新 replay 当前逻辑，导出建议快照。
- 可对齐分析：支持将助手建议与 MAKA/Seer 对齐数据、实战实际出牌放在同一动作点比较。
- 有回归测试：核心牌效、攻守、立直、副露和解析逻辑有单测覆盖。

## 适用场景

- 实战时作为切牌、鸣牌、立直和危险牌提醒器。
- 复盘时定位某类错误建议，并把错例沉淀成回归测试。
- 研究规则型日麻助手如何从实时事件维护完整局面。

低置信度、强攻守分歧、终盘高压局面仍需要人工判断。这个工具适合做辅助参考，不应该当作绝对答案。

## 快速开始

环境要求：

- Python 3.10+
- Google Chrome
- 雀魂网页版

安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

启动带调试端口的 Chrome：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/majsoul-cdp
```

打开雀魂网页版并进入对局后，在仓库根目录运行：

```bash
python3 -u majsoul_cdp_live.py \
  --debug-log live_debug.jsonl
```

## 实时建议

建议触发点主要包括：

- 起手配牌
- 自家自摸后
- 自家副露后
- 可吃、碰、杠时的操作提示
- 立直/默听边界判断
- 有明显危险时的基础攻守提示

实时链路：

```text
Chrome DevTools websocket
-> game-gateway 帧
-> parse_majsoul_har.py 解包
-> LiveGameState 更新局面
-> majsoul_live_helper.py 输出建议
```

## 离线回放

从原始牌谱生成助手建议快照：

```bash
python3 tools/replay_paipu_dir.py \
  data/paipu_exports \
  --player-name Levey \
  --snapshot-jsonl decision_snapshots.jsonl
```

也可以直接解析 HAR：

```bash
python3 majsoul_live_helper.py your.har \
  --snapshot-jsonl decision_snapshots.jsonl
```

## MAKA/Seer 对齐评估

当前主要质量评估入口：

```bash
python3 tools/analyze_aligned_paipu.py \
  data/paipu_4p_aligned \
  data/paipu_exports \
  --player-name Levey \
  --max-record-index 500 \
  --summary-json data/archive/latest_aligned_summary.json \
  --summary-only \
  --progress
```

这个脚本会：

- 从 `data/paipu_exports` 重新回放原始牌谱，得到当前代码的建议。
- 从 `data/paipu_4p_aligned` 读取 MAKA/Seer 推荐和实际动作。
- 用 `record_index` 对齐同一个动作点。
- 只比较真正可比的自家出牌点。

关键输出字段：

- `discard_matched`：成功对齐并可比较的自家出牌点数量。
- `discard_exact`：助手建议和 Seer top 完全一致的数量。
- `discard_top3`：助手建议落在 Seer top3 内的数量。
- `discard_actual_match`：助手建议和实战实际出牌一致的数量。
- `seer_actual_match`：Seer top 和实战实际出牌一致的数量。
- `consensus_mismatch_count`：助手和实战不一致，而 Seer 与实战同向的高价值错例数量。
- `consensus_family_patterns`：高价值错例的牌类方向，比如 `middle->honor`。

单局或小范围排查：

```bash
python3 tools/analyze_aligned_paipu.py \
  data/paipu_4p_aligned \
  data/paipu_exports \
  --player-name Levey \
  --uuid 250602-93eef05b-0281-4eff-b39f-22e79a48de95 \
  --max-record-index 500
```

批量评估时推荐使用：

- `--summary-only`：只输出汇总，避免每局样本刷屏。
- `--progress`：打印当前跑到哪一局。
- `--suggestion-lookback N`：只在可比出牌点前 N 个 record 生成建议，默认 `3`，用于减少离线评估计算量。

## 当前评估结果

截至当前 `20` 份 aligned 牌谱，使用：

```bash
python3 tools/analyze_aligned_paipu.py \
  data/paipu_4p_aligned \
  data/paipu_exports \
  --player-name Levey \
  --max-record-index 500 \
  --summary-json data/archive/latest_aligned_summary.json \
  --summary-only
```

得到的核心汇总是：

```text
files: 20
missing_paipu_count: 0
discard_matched: 84
discard_actual_match: 51 / 84 = 60.7%
seer_actual_match: 4 / 84 = 4.8%
consensus_mismatch_count: 3
```

这个结果的解释：

- 当前助手在这些样本里和实战选择贴合度不错，而且新版规则重跑后略有提升。
- Seer top 和实战实际出牌的一致率很低，说明不能把 Seer top 当作单点标准答案。
- 高价值共识错例只有 `3` 个，数量还不足以支撑大幅改规则。
- 目前更适合继续积累 aligned 数据，而不是为了少数错例强行调参。

## 项目结构

根目录保留运行和测试必需文件：

- `majsoul_live_helper.py`：核心状态机和决策逻辑。
- `majsoul_cdp_live.py`：实时连接 Chrome DevTools 的入口。
- `parse_majsoul_har.py`：雀魂 websocket / protobuf 解包逻辑。
- `liqi.json`：雀魂 protobuf schema。
- `test_majsoul_live_helper.py`：回归测试。
- `seer_action_codes.md`：Seer action 编码说明。
- `tools/analyze_aligned_paipu.py`：当前主评估脚本。
- `tools/replay_paipu_dir.py`：批量回放原始牌谱并导出助手快照。
- `tools/analyze_aligned_seer.py`：Seer action 解码辅助。

常见本地数据目录：

- `data/paipu_exports/`：原始牌谱 JSON，用于 replay 当前助手逻辑。
- `data/paipu_4p_aligned/`：已对齐的 MAKA/Seer 分析数据，用于质量评估。
- `data/paipu_4p_status/`：原始牌谱和 Seer 报告的中间整理结果。
- `data/seer_exports/`：Seer 报告导出。
- `data/archive/`：旧日志、旧临时数据和备份。

`data/` 默认不提交到仓库。公开 issue 或 pull request 里请使用脱敏后的最小复现数据。

## 质量水平

按目前样本和实战能力估计：

- 明显强于最初的简单规则版。
- 基础牌效、孤张处理、宝牌/役牌价值、常见副露和立直提示已经可用。
- 能作为雀豪到弱雀圣区间的实战辅助参考。
- 还不能严肃声称达到稳定雀圣+ 或魂天级，因为它不是搜索/神经网络 AI，复杂攻守、终盘读牌、点棒条件和特殊局面仍然偏规则近似。

## 回归测试

修改核心逻辑后跑：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mj_pycache \
python3 -m unittest test_majsoul_live_helper.py
```

轻量编译检查：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mj_pycache \
python3 -m py_compile \
  majsoul_live_helper.py \
  majsoul_cdp_live.py \
  parse_majsoul_har.py \
  tools/analyze_aligned_paipu.py \
  test_majsoul_live_helper.py
```

如果本地已有未提交的规则调整，先以当前测试输出为准，再更新公开说明里的评估数字。

## 开源维护

- 贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 安全和数据处理说明见 [SECURITY.md](SECURITY.md)。
- Codex for Open Source 申请材料草稿见 [docs/codex-for-oss.md](docs/codex-for-oss.md)。

## 免责声明

本项目是非官方工具，与雀魂、MAKA、Seer 无隶属关系。使用时请遵守相关平台规则，并避免公开提交包含账号、会话、牌谱隐私或第三方报告原始内容的数据。

## License

MIT License. See [LICENSE](LICENSE).
