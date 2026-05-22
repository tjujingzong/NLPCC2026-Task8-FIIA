# FIIA 攻击流水线脚本说明

## 概览

本项目包含 4 个核心 Python 脚本，覆盖从攻击样本生成到最终 Attack Score 计算的完整流水线：

```
generate_attacks.py → clean_attacks.py → validate.py → attack.py
                                               ↑
                                        batch_pipeline.py (一键串联)
```

---

## 一、`attack.py` — 评估 & Attack Score 计算

### 功能

核心评估脚本。对给定的原始文本和攻击文本分别进行 10 轮 DeepSeek API 调用，计算：

1. **MIR_orig**：原句不一致率
2. **MIR_attack**：攻击句不一致率
3. **Score_i** = max(MIR_attack − MIR_orig, 0)
4. **AttackScore** = Σ Score_i（所有有效样本的得分累加）

### 使用方法

```bash
# 评估指定 ID（调试用）
python attack.py --mode eval --items 0001,0003,0005 --output results/eval_test.json

# 评估指定 ID + 攻击样本
python attack.py --mode eval --items 0001,0003,0005 \
  --attacks results/attacks_v1.json --output results/eval_test.json

# 全量评估前 N 条
python attack.py --mode full --limit 50 \
  --attacks results/attacks_v3_fixed.json --output results/attack_v3_results.json
```

### 输出格式

结果 JSON 文件中每条记录包含：

```json
{
  "id": "0001",
  "mir_orig": 0.0,
  "mir_attack": 0.4,
  "score": 0.4,
  "orig_counts": {"T": 10},
  "attack_counts": {"T": 6, "F": 4}
}
```

终端输出会自动汇总 **AttackScore**（累积总得分）。

> ⚠️ 注意：若某条数据的 `mir_attack` 为 `null`，表示未提供攻击文本，不计入 Score（等价于 0 分）。

---

## 二、`generate_attacks.py` — 攻击样本生成器

### 功能

使用 DeepSeek API 自动生成 `text_attack` 候选句。模型扮演语言学攻击者，对原句进行微小扰动。

当前默认策略：**让步转折结构 + 多重模糊限定语**（已验证有效，Score 可达 0.6 满分）。

### 使用方法

```bash
# 为指定 ID 生成攻击
python generate_attacks.py --items 0001,0003,0005 --output results/attacks_x.json

# 为前 N 条生成（从 offset 开始）
python generate_attacks.py --limit 20 --offset 0 --output results/attacks_x.json

# 每条生成多个变体
python generate_attacks.py --limit 10 --variants 3 --output results/attacks_x.json
```

### 输出文件

| 文件 | 说明 |
|------|------|
| `attacks_x.json` | 完整版（含 `strategy` 字段） |
| `attacks_x_submission.json` | 提交版（仅 `id` + `text_attack`） |

---

## 三、`clean_attacks.py` — 攻击变体去重 & 优选

### 功能

当同一条数据生成多个攻击变体时（`generate_attacks.py --variants 3`），此脚本为每个 `id` 只保留 **R4 文本保留度最高** 的变体（最接近原句，最易通过 validate.py 核验）。

### 使用方法

```bash
# 默认参数
python clean_attacks.py

# 或修改 main 调用自定义路径
```

目前硬编码路径，可按需在 `__main__` 中修改：
- 输入：`attacks_v1.json`（多变体文件）
- 输出：`attacks_v1_clean.json`（去重后文件）

---

## 四、`batch_pipeline.py` — 一键批量流水线

### 功能

自动化串联生成 → 核验 → 修复 → 评估全流程：

```
Step 1: 生成攻击样本  (调用 generate_attacks.py)
Step 2: 核验攻击样本  (调用 validate.py)
Step 3: 修复失败攻击  (R4 截断 + 降级为"似乎"攻击)
Step 4: 评估 & 排序   (调用 attack.py 或合并已有结果)
```

### 使用方法

```bash
# 全流程自动化（前 50 条）
python batch_pipeline.py --step all --limit 50

# 单步执行
python batch_pipeline.py --step generate --limit 50
python batch_pipeline.py --step validate
python batch_pipeline.py --step fix
python batch_pipeline.py --step merge

# 指定 ID
python batch_pipeline.py --step all --items 0001,0003,0005
```

### R4 修复策略

`fix_r4_failure()` 对未通过 R4 核验（相似度 < 0.65）的攻击文本：

1. 从尾部逐个删除从句（按 `。，；、然而但而` 等分隔符截断）
2. 每次截断后重新计算 Levenshtein 相似度
3. 若仍不通过，降级为**最小改动攻击**（仅在谓词前插入"似乎"）

---

## 五、关于 Attack Score

### 计算方式（与 README 一致）

$$
Score_i = \max(MIR_{attack} - MIR_{orig}, 0)
$$

$$
AttackScore = \sum_i Score_i
$$

- 单条 $Score_i \in [0, 0.6]$
- 最多计入 200 条有效攻击，$AttackScore \in [0, 120]$

### 如何获取 Attack Score

**方法 1**：`attack.py` 终端输出会自动打印 `攻击总得分 (AttackScore)`

**方法 2**：从结果 JSON 手动累加 `score` 字段（null 视为 0）

```python
import json
with open("results/attack_results.json") as f:
    data = json.load(f)
total = sum(r.get("score") or 0 for r in data)
print(f"AttackScore = {total}")
```

---

## 六、当前结果

| 版本 | 攻击数 | Attack Score | 说明 |
|------|--------|-------------|------|
| V1+V2 合并 | 34 条有效 | **2.6** | 30 条原始句 + 4 条改编句，2 阶段混合攻击 |
| V3 | 150 条（50×3） | 未评估 | 全量数据集攻击，已核验通过，待运行 attack.py |

V3 评估命令：
```bash
python attack.py --mode full --limit 50 \
  --attacks results/attacks_v3_fixed.json \
  --output results/attack_v3_results.json
```
