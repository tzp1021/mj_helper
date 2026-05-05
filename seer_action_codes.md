# Seer Action 编码规则

这个文件记录雀魂 `SeerReport` / `MAKA` 分析结果里 `events[].recommends[].predictions[].action` 的解码规则。

## 背景

`SeerReport` 里的推荐动作不是直接写成 `2s`、`东`、`碰` 这种可读文本，而是一个整数编码，例如：

```json
{"action": 132, "score": 72}
{"action": 141, "score": 18}
{"action": 118, "score": 6}
```

这些值需要先拆成：

- 动作类型
- 对应牌张

再转成人能读的建议。

## 编码总规则

页面内 `game.MakaManager.convertCodeToOperation()` 的逻辑可以概括成：

- `1..9`：非出牌动作
- `100..199`：普通打牌 `DA`
- `200..299`：立直打牌 `LICHIDA`
- `300..399`：杠相关 `GANG`

伪代码：

```text
if action < 10:
  直接按操作枚举解释
elif action < 200:
  operationType = DA
  tile = convertNumberToPai(action - 100)
elif action < 300:
  operationType = LICHIDA
  tile = convertNumberToPai(action - 200)
elif action < 400:
  operationType = GANG
  tile = convertNumberToPai(action - 300)
```

## 小于 10 的操作

来自页面里的 `EMakaOperationType`：

```text
0  DEFAULT
1  SKIP
2  CHI_FRONT
3  CHI_MIDDLE
4  CHI_BACK
5  PENG
6  GANG
7  HU
8  LIUJU
9  BABEI
11 DA
12 LICHIDA
13 ZIMO
```

常用解释：

- `1` = 跳过
- `5` = 碰
- `6` = 杠
- `7` = 和
- `8` = 九种九牌 / 流局类操作
- `9` = 拔北

## 牌号到牌张

`convertNumberToPai(n)` 返回一个对象：

```json
{
  "type": 2,
  "index": 2,
  "dora": false,
  "touming": false,
  "baida": false
}
```

其中：

- `type = 0` -> `m`
- `type = 1` -> `p`
- `type = 2` -> `s`
- `type = 3` -> `z`

`index` 是牌面数字：

- `m/p/s`：`1..9`
- `z`：`1..7`
  - `1z = 东`
  - `2z = 南`
  - `3z = 西`
  - `4z = 北`
  - `5z = 白`
  - `6z = 发`
  - `7z = 中`

所以：

```text
{type: 0, index: 2} -> 2m
{type: 1, index: 8} -> 8p
{type: 2, index: 2} -> 2s
{type: 3, index: 1} -> 东
```

## 例子

### 例 1

```json
{"action": 132, "score": 72}
```

解释：

- `132` 在 `100..199` 区间
- 所以是普通打牌 `DA`
- 牌号是 `132 - 100 = 32`
- 页面里 `convertNumberToPai(32)` 解出来是：

```json
{"type": 2, "index": 2}
```

也就是：

```text
打 2s
```

### 例 2

```json
{"action": 141, "score": 18}
```

解释：

- `141 - 100 = 41`
- `convertNumberToPai(41)` -> `{type: 3, index: 1}`
- 即：

```text
打 东
```

### 例 3

```json
{"action": 118, "score": 6}
```

解释：

- `118 - 100 = 18`
- `convertNumberToPai(18)` -> `{type: 1, index: 8}`
- 即：

```text
打 8p
```

所以这组三个推荐的人话是：

```text
1. 打 2s  (72)
2. 打 东  (18)
3. 打 8p  (6)
```

## 分数字段

`score` 不是严格概率，更像是 Seer 内部对候选动作的相对评分。

实用上可以这样理解：

- 分差很大：Seer 很明确偏向第一选择
- 分差接近：说明这手分歧不小

不要直接把它当成胜率百分比。

## 对齐牌谱

Seer 的推荐通常通过下面字段和牌谱动作流对齐：

- 对局级：`report.uuid`
- 决策点级：`events[].record_index`

`SeerEvent` 结构大致是：

```json
{
  "record_index": 128,
  "seer_index": 145,
  "recommends": [
    {
      "seat": 2,
      "predictions": [
        {"action": 132, "score": 72},
        {"action": 141, "score": 18},
        {"action": 118, "score": 6}
      ]
    }
  ]
}
```

字段解释：

- `record_index`
  - 这是最重要的对齐字段
  - 指向牌谱动作流里的某个动作位置
  - 通常用来对应：

```text
paipu.game_detail_records.actions[record_index]
```

- `seer_index`
  - Seer 自己内部的事件编号
  - 可以当辅助编号用
  - 但做“牌谱 <-> Seer”对齐时，优先用 `record_index`

- `recommends`
  - 这一时点的推荐集合
  - 里面可能按 `seat` 拆开
  - 每个 `seat` 下再给多个 `predictions`

也就是：

```text
paipu.game_detail_records.actions[record_index]
    <->
seer.report.events[i]
```

这样能把：

- 实际动作
- Seer 推荐候选
- Seer 分数

放到同一个决策点上分析。

### 对齐示例

如果牌谱动作流里有：

```json
{
  "name": "RecordDiscardTile",
  "seat": 2,
  "tile": "2s"
}
```

并且它在：

```text
paipu.game_detail_records.actions[128]
```

同时 Seer 有：

```json
{
  "record_index": 128,
  "seer_index": 145,
  "recommends": [
    {
      "seat": 2,
      "predictions": [
        {"action": 132, "score": 72},
        {"action": 141, "score": 18},
        {"action": 118, "score": 6}
      ]
    }
  ]
}
```

那就可以读成：

```text
这局的第 128 个动作点：
- 实际发生：seat 2 打 2s
- Seer 第一推荐：打 2s，72 分
- Seer 第二推荐：打 东，18 分
- Seer 第三推荐：打 8p，6 分
```

### 实战使用建议

后续如果要做自动分析，建议每条样本至少保留：

- `uuid`
- `record_index`
- `seer_index`
- `seat`
- `actual_action`
- `actual_tile`
- `predictions`

这样就能稳定做：

- 玩家实际动作 vs Seer 第一推荐
- 本地助手推荐 vs Seer 第一推荐
- 高分歧决策点筛选

## 目前已验证的页面内入口

这些规则是从页面运行时代码验证出来的：

- `game.MakaManager.convertCodeToOperation()`
- `game.MakaManager.convertNumberToPai()`
- `game.EMakaOperationType`

如果后续要继续自动化解析，优先复用这套规则，不要重新猜测 `action` 编码。
