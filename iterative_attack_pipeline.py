"""
NLPCC2026-Task8 FIIA 迭代攻击流水线

核心思路:
  1. 对 1089 条数据生成初始攻击（Flash 模型）
  2. 评估攻击结果，Score ≥ 0.5 的保留
  3. 低分条目按攻击潜力排序，送 Pro 模型重新生成
  4. 重复 2-3，直到合格数 ≥ 200 或完成 3 轮精炼

所有中间结果和最终输出保存到 results-v2/ 目录。

使用:
  python iterative_attack_pipeline.py                    # 从头开始
  python iterative_attack_pipeline.py --resume           # 从断点恢复
  python iterative_attack_pipeline.py --from-scratch     # 忽略进度重新开始
  python iterative_attack_pipeline.py --target 200 --threshold 0.5
"""

import os
import re
import json
import time
import argparse
import sys
import threading
from collections import Counter
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openai import OpenAI

# ============================================================
# 全局配置
# ============================================================

load_dotenv()

# --- API 配置 ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_FLASH = "deepseek-v4-flash"       # 批量生成 & 评估
MODEL_PRO = "deepseek-v4-pro"             # 精炼攻击（更强大的模型）

# --- 路径配置 ---
DATASET_PATH = "dataset/fiia_0427.json"
OUTPUT_DIR = "results-v3"
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "progress.json")

# --- 评测参数 ---
NUM_ROUNDS = 10          # 每条样本评估轮数
MAX_RETRIES = 3          # API 调用最大重试次数
API_SLEEP_INTER = 0.5    # 多轮调用间隔（秒）
API_SLEEP_ITEM = 1.0     # 条目间间隔（秒）

# --- 流水线参数 ---
TARGET_COUNT = 200         # 目标合格条目数
SCORE_THRESHOLD = 0.5      # 合格分数阈值
MAX_REFINEMENT_ROUNDS = 3  # 最大精炼轮数
BATCH_SIZE = 50            # 每批保存进度
MAX_WORKERS = 3            # 并行工作线程数（调高可加速但注意 API 限流）
VALIDATE_MAX_RETRIES = 3   # 每条攻击生成后验证失败最多重试次数

# --- 核验阈值（与 validate.py 一致）---
LCS_COVERAGE_THRESHOLD = 0.7   # R3 小句完整性阈值
SIM_THRESHOLD = 0.65           # R4 文本保留度阈值

# 线程安全锁
_PROGRESS_LOCK = threading.Lock()
_PRINT_LOCK = threading.Lock()


# ============================================================
# Prompt 模板
# ============================================================

# --- 评估用 Prompt（与原 attack.py 一致）---
EVAL_PROMPT_TEMPLATE = """根据"文本"的内容，判断"假设"的真值情况：
文本：{text}
假设：{hypothesis}
只允许答复T/F/U（对应真/假/无法确定），禁止回复其他解释性内容。"""

# --- 初始攻击生成 System Prompt（与 generate_attacks.py 一致）---
ATTACK_SYSTEM_PROMPT = """你是一个语言学家，正在参与一项关于大语言模型"叙实性推理一致性"的红队攻击测试。

你的任务：对给定的中文句子进行微小的语言学改编，目标是使模型在判断所述事件的真假时变得犹豫不决、前后矛盾。

改编规则：
1. 必须在原句基础上改动，不能完全重写
2. 谓词（如"哀叹""知道""认为"等）和假设小句的内容必须保留，不可删除
3. 可以添加/删除/替换修饰语、改变语序、增减逻辑连接词、改变情态、添加评价性副词等
4. 改编后的句子必须自然通顺，符合中文语法
5. 改动幅度严格控制在 5%~25%（确保编辑距离相似度≥0.70，能通过R4核验）

⚠️ 核心攻击策略（已被验证有效，Score可达0.6满分）：
- **多层让步转折**：在句首/句中/句尾分布多个让步连接词（尽管…但…却…且…然而…）
- **分散式模糊限定语**：在句中多个位置散布"似乎""或许""大概""某种程度""有意无意"等模糊词
- **关键技巧**：不要把所有模糊语堆在一起，要分散在句首、谓词前、谓词后等不同位置
- **成功案例**：原句"A抱怨B" → 改编"尽管A似乎已决定X，且Y或许并非主要原因，但A却在某种程度上有意无意地抱怨B大概太严重"

⚠️ 避免的失败模式：
- ❌ 只在谓词前加一个"似乎"（太弱，Score=0）
- ❌ 在句尾添加长反驳从句"但在某种程度上这并非完全如此"（会R4失败）
- ❌ 大幅删减原文内容（会R4失败）"""

ATTACK_USER_TEMPLATE = """请对下面的句子进行改编，使其可能干扰模型的叙实性推理一致性。

原句：{text_original}
谓词（必须保留）：{predicate}
假设小句（必须基本保留）：{hypothesis}

⚠️ 示例（来自官方数据，仅供参考）：
- 原句：人们都知道西部大开发需要资金和技术，但是负责人指出，从根本来看更需要知识和人才。
- 谓词：知道
- 假设：西部大开发需要资金和技术。
- 改编：尽管人们似乎都知道西部大开发需要资金和技术，但在某种程度上负责人却指出，从根本来看或许更需要知识和人才。
- 策略：多层让步转折（尽管…但…却…）+ 分散模糊限定语（似乎、在某种程度上、或许）
- 效果：原句一致率100% → 改编后模型判断变得犹豫不决

请优先使用「让步转折结构 + 多重模糊限定语」的组合策略。只给出1个最佳改编版本，格式如下：

策略：xxx
句子：xxx"""

# --- 验证失败重试 Prompt ---
VALIDATE_RETRY_TEMPLATE = """你上次生成的攻击句子未通过核验规则，请根据以下错误信息重新生成。

### 核验失败原因
{errors}

### 原始数据
- 原句：{text_original}
- 谓词（必须原样保留在改编句中）：{predicate}
- 假设小句（必须基本保留）：{hypothesis}

### 上次生成的句子（未通过核验）
{failed_attack}

### 改编规则提醒
- R2: 谓词「{predicate}」必须作为连续子串出现在改编句中，不可拆开或变形
- R3: 假设小句的主要字符必须能在改编句中按顺序找到（LCS覆盖率≥70%）
- R4: 与原文的编辑距离相似度必须≥65%（改动不能太大，控制在5%~25%）

请严格遵守上述规则重新生成，格式如下：

策略：xxx
句子：xxx"""

# --- 精炼攻击 Prompt（给 Pro 模型的反馈式 Prompt）---
REFINE_SYSTEM_PROMPT = """你是一位世界级的红队攻击专家和计算语言学家，正在参与一项针对大语言模型"叙实性推理一致性"的高级攻击任务。

你的核心目标：通过精确的语言学改编，最大化破坏模型对同一假设在10轮推理中的自洽性。

你必须严格遵守以下改编规则（R2-R5 核验）：
1. 谓词（predicate）必须原样保留在改编句中
2. 假设小句的主要字符必须能在改编句中按顺序找到（LCS覆盖率≥70%）
3. 与原文的编辑距离相似度必须 ≥65%（不能改太多）
4. 改编句必须自然通顺，与原文的通顺保持度 ≥60%

成功的攻击模式参考：
- 多层让步转折 + 分散式模糊限定语的组合拳（已被验证 Score 可达 0.6）
- 在不同句法位置（句首状语、谓词前、谓词后）散布模糊语
- 避免将所有模糊词语堆在一起，避免在句尾添加过长的独立从句"""

REFINE_USER_TEMPLATE = """## 任务：改进攻击策略

我需要你对以下样本重新设计攻击方案。你的上次攻击未能达到 Score ≥ 0.5 的阈值。

### 原始数据
- **原句**：{text_original}
- **谓词**（必须保留）：{predicate}
- **假设小句**（必须基本保留）：{hypothesis}

### 上次攻击
- **改编句**：{previous_attack}
- **策略**：{previous_strategy}

### 评估反馈
- **原句不一致率 MIR_orig**：{mir_orig}（10轮中最多 {orig_max_count} 次相同回答）
- **攻击句不一致率 MIR_attack**：{mir_attack}（10轮中最多 {attack_max_count} 次相同回答）
- **攻击得分 Score**：{score}（目标 ≥ 0.5，当前差距 {score_gap}）

### 你的任务
请仔细分析上次攻击策略为何效果不足，然后设计一个**全新的、更有效的**攻击句子。

注意事项：
- 如果上次策略过于保守（如仅添加一个模糊词），请尝试更激进的让步转折组合
- 如果上次策略过于激进（改动太大），请适当收敛确保 R4 核验通过
- 可以尝试完全不同的策略角度：情态转换、否定嵌入、信息稀释、预设取消等
- 始终确保满足 R2-R5 核验规则

请按以下格式回复：

策略：[简述新策略，包括与上次的不同之处]
句子：[新的改编句子]"""


# ============================================================
# 工具函数
# ============================================================

def init_client():
    """初始化 DeepSeek 客户端"""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "未找到 DEEPSEEK_API_KEY。请在 .env 文件中设置，"
            "或设置环境变量 DEEPSEEK_API_KEY=sk-xxx"
        )
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def extract_answer(response_text: str) -> str:
    """
    从模型回复中提取 T/F/U/R。
    规则:
    - 优先匹配首个独立出现的 T/F/U（忽略大小写）
    - 如果回复中包含 "拒绝" 等关键词，返回 R
    - 若无法提取，返回 R（无效回答）
    """
    text = response_text.strip().upper()
    m = re.search(r'\b([TFU])\b', text)
    if m:
        return m.group(1)
    for ch in text:
        if ch in ("T", "F", "U"):
            return ch
    return "R"


def call_model(client: OpenAI, text: str, hypothesis: str,
               model: str = MODEL_FLASH) -> str:
    """
    单次调用 DeepSeek 推理，返回提取的答案 (T/F/U/R)。
    带重试逻辑。
    """
    prompt = EVAL_PROMPT_TEMPLATE.format(text=text, hypothesis=hypothesis)
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=1.0,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = response.choices[0].message.content or ""
            return extract_answer(raw)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                tprint(f"    [重试 {attempt + 1}/{MAX_RETRIES}] API 错误: {e}，等待 {wait} 秒...")
                time.sleep(wait)
            else:
                tprint(f"    [失败] API 调用最终失败: {e}")
                return "R"
    return "R"


def multi_turn_eval(client: OpenAI, text: str, hypothesis: str,
                    label: str = "", model: str = MODEL_FLASH) -> dict:
    """
    对一条样本做 NUM_ROUNDS 轮调用，返回:
      { "answers": [T,F,U,...], "counts": {T:n, F:n, U:n, R:n}, "mir": float }
    """
    answers = []
    for i in range(NUM_ROUNDS):
        ans = call_model(client, text, hypothesis, model=model)
        answers.append(ans)
        tprint(f"    [{label}] 轮次 {i + 1}/{NUM_ROUNDS} → {ans}")
        if i < NUM_ROUNDS - 1:
            time.sleep(API_SLEEP_INTER)

    counts = dict(Counter(answers))
    valid = {k: v for k, v in counts.items() if k in ("T", "F", "U")}
    max_count = max(valid.values()) if valid else 0
    mir = round(1.0 - max_count / NUM_ROUNDS, 4)

    return {"answers": answers, "counts": counts, "mir": mir}


def load_dataset(path: str = DATASET_PATH) -> dict:
    """加载原始数据集，返回 {id: item} 字典"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["id"]: item for item in data}


# ============================================================
# 进度管理（断点续传）
# ============================================================

def load_progress() -> dict:
    """加载进度文件"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "phase": "init",
        "round": 0,
        "completed_ids": [],
        "qualified_pool": {},  # {id: attack_dict}
        "low_score_pool": {},  # {id: eval_result}
        "total_dataset_size": 0,
        "last_updated": None,
    }


def save_progress(progress: dict):
    """保存进度文件"""
    progress["last_updated"] = datetime.now().isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def save_progress_safe(progress: dict):
    """线程安全的进度保存"""
    with _PROGRESS_LOCK:
        save_progress(progress)


def tprint(*args, **kwargs):
    """线程安全的 print"""
    with _PRINT_LOCK:
        print(*args, **kwargs)


def save_json(data, filepath: str):
    """保存 JSON 到 results-v2/"""
    full_path = os.path.join(OUTPUT_DIR, filepath) if not filepath.startswith(OUTPUT_DIR) else filepath
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → 已保存: {full_path}")


# ============================================================
# 内联核验（R2-R4，纯计算，不需要加载模型）
# ============================================================

def _calculate_levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串的编辑距离"""
    if len(s1) < len(s2):
        return _calculate_levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _calculate_lcs_length(a: str, b: str) -> int:
    """计算最长公共子序列长度"""
    if not a or not b:
        return 0
    m, n = len(a), len(b)
    dp = [0] * (n + 1)
    for i in range(1, m + 1):
        prev = 0
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
            else:
                dp[j] = max(dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _normalize_for_lcs(text: str) -> str:
    """用于 LCS 检查的轻量规范化"""
    if text is None:
        return ""
    remove_chars = set(" \t\r\n，。！？；：、“”‘’\"'（）()《》〈〉【】[]{}.,!?;:-—…·")
    return "".join(ch for ch in str(text).strip() if ch not in remove_chars)


def validate_attack_inline(text_attack: str, item: dict) -> list:
    """
    轻量级内联核验 (R2-R4)，纯计算，不需要加载模型。
    返回错误列表，空列表表示通过。
    """
    errors = []
    predicate = item.get("predicate", "")
    hypothesis = item.get("hypothesis", "")
    text_original = item.get("text_original", "")

    if not text_attack or len(text_attack.strip()) < 5:
        errors.append("R1: 攻击句为空或太短")
        return errors

    # R2: 谓词必须在 text_attack 中
    if predicate and predicate not in text_attack:
        errors.append(f"R2: text_attack中缺失谓词『{predicate}』")

    # R3: 小句完整性 (LCS覆盖率 >= 0.7)
    norm_hyp = _normalize_for_lcs(hypothesis)
    norm_text = _normalize_for_lcs(text_attack)
    if norm_hyp:
        lcs_len = _calculate_lcs_length(norm_hyp, norm_text)
        lcs_coverage = lcs_len / len(norm_hyp)
        if lcs_coverage < LCS_COVERAGE_THRESHOLD:
            errors.append(f"R3: 小句完整性过低(coverage={lcs_coverage:.3f}<{LCS_COVERAGE_THRESHOLD})")

    # R4: 文本保留度 (编辑距离相似度 >= 0.65)
    if text_original:
        dist = _calculate_levenshtein_distance(text_original, text_attack)
        max_len = max(len(text_original), len(text_attack))
        similarity = 1 - dist / max_len if max_len > 0 else 1.0
        if similarity < SIM_THRESHOLD:
            errors.append(f"R4: 文本保留度过低(similarity={similarity:.3f}<{SIM_THRESHOLD})")

    return errors


# ============================================================
# Phase 1: 初始攻击生成
# ============================================================

def generate_single_attack(client: OpenAI, item: dict, model: str = MODEL_PRO) -> dict:
    """
    对单条样本生成 1 个攻击变体，并内联验证 R2-R4。
    如果验证失败，将错误反馈给模型重新生成，最多重试 VALIDATE_MAX_RETRIES 次。
    返回: {"id": str, "text_attack": str, "strategy": str} 或 None（验证始终失败则跳过）
    """
    prompt = ATTACK_USER_TEMPLATE.format(
        text_original=item["text_original"],
        predicate=item["predicate"],
        hypothesis=item["hypothesis"],
    )

    # 第一次生成
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ATTACK_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.9,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = response.choices[0].message.content or ""
            parsed = parse_attack_response(raw)
            if parsed:
                strategy, sentence = parsed[0]
                break
            else:
                tprint(f"    [警告] 解析失败，回复内容: {raw[:100]}...")
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                tprint(f"    [重试 {attempt + 1}/{MAX_RETRIES}] 生成失败: {e}")
                time.sleep(2 ** attempt)
            else:
                tprint(f"    [失败] 生成最终失败: {e}")
                return None
    else:
        # 所有 API 尝试均失败
        return None

    # 验证+重试循环
    for validate_attempt in range(VALIDATE_MAX_RETRIES):
        errors = validate_attack_inline(sentence, item)
        if not errors:
            # 验证通过
            return {
                "id": item["id"],
                "text_attack": sentence,
                "strategy": strategy,
            }

        # 验证失败，反馈重试
        tprint(f"    [{item['id']}] 验证失败({validate_attempt+1}/{VALIDATE_MAX_RETRIES}): {'; '.join(errors)}")

        if validate_attempt >= VALIDATE_MAX_RETRIES - 1:
            break  # 已达重试上限

        # 构建重试 prompt
        retry_prompt = VALIDATE_RETRY_TEMPLATE.format(
            errors="\n".join(f"- {e}" for e in errors),
            text_original=item["text_original"],
            predicate=item["predicate"],
            hypothesis=item["hypothesis"],
            failed_attack=sentence,
        )

        # 重新生成
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ATTACK_SYSTEM_PROMPT},
                    {"role": "user", "content": retry_prompt},
                ],
                max_tokens=2048,
                temperature=0.85,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = response.choices[0].message.content or ""
            parsed = parse_attack_response(raw)
            if parsed:
                strategy, sentence = parsed[0]
            else:
                tprint(f"    [警告] 重试解析失败: {raw[:100]}...")
        except Exception as e:
            tprint(f"    [重试失败] 验证重生成异常: {e}")

    # 所有验证重试均失败，跳过该条目
    tprint(f"    [{item['id']}] ❗ 验证始终失败，放弃该条目")
    return None


def parse_attack_response(text: str) -> list:
    """解析模型回复，提取 (strategy, sentence) 列表"""
    results = []
    strategy_match = re.search(r'策略[：:]\s*(.+?)(?:\n|$)', text)
    sentence_match = re.search(r'句子[：:]\s*(.+?)(?:\n|$)', text)
    strategy = strategy_match.group(1).strip() if strategy_match else "未标注"
    sentence = sentence_match.group(1).strip() if sentence_match else ""

    if not sentence:
        blocks = re.split(r'改编\d+\s*[：:]', text)
        for block in blocks[1:]:
            s_match = re.search(r'策略[：:]\s*(.+?)(?:\n|$)', block)
            sent_match = re.search(r'句子[：:]\s*(.+?)(?:\n|$)', block)
            s = s_match.group(1).strip() if s_match else "未标注"
            sent = sent_match.group(1).strip() if sent_match else block.strip()
            if sent and len(sent) > 5:
                results.append((s, sent))
        return results

    if sentence and len(sentence) > 5:
        results.append((strategy, sentence))
    return results


def make_fallback_attack(item: dict) -> dict:
    """降级：在谓词前添加'似乎'的最小改动"""
    text = item["text_original"]
    predicate = item["predicate"]
    idx = text.find(predicate)
    if idx > 0:
        text_attack = text[:idx] + "似乎" + text[idx:]
    else:
        text_attack = text + "（似乎如此）"
    return {
        "id": item["id"],
        "text_attack": text_attack,
        "strategy": "降级-最小改动(似乎)",
    }


def _worker_generate(item_id: str, item: dict, model: str):
    """Worker: 对单条数据生成攻击（每个线程独立 client）"""
    client = init_client()
    result = generate_single_attack(client, item, model=model)
    if result:
        tprint(f"  [{item_id}] ✅ 生成完成 | 策略: {result['strategy'][:40]}")
    else:
        tprint(f"  [{item_id}] ❌ 生成失败（验证未通过，跳过）")
    return item_id, result


def phase_generate_initial_attacks(client: OpenAI, dataset: dict,
                                   progress: dict, workers: int = MAX_WORKERS) -> list:
    """
    Phase 1: 对全部 1089 条数据并行生成初始攻击。
    支持断点续传。
    返回: 攻击列表 [{id, text_attack, strategy}, ...]
    """
    all_ids = sorted(dataset.keys())
    completed = set(progress.get("completed_generation_ids", []))
    attacks = progress.get("generated_attacks", [])

    pending_ids = [iid for iid in all_ids if iid not in completed]
    total = len(all_ids)
    done = len(completed)

    print(f"\n{'=' * 60}")
    print(f"Phase 1: 初始攻击生成 ({MODEL_PRO}) | 并行度: {workers}")
    print(f"  总数据: {total} 条 | 已完成: {done} | 待处理: {len(pending_ids)}")
    print(f"{'=' * 60}")

    if not pending_ids:
        print("  → 全部已完成，跳过生成阶段")
        return attacks

    # 分批并行处理：每批 workers*10 条
    batch_total = workers * 10
    for batch_start in range(0, len(pending_ids), batch_total):
        batch_ids = pending_ids[batch_start:batch_start + batch_total]
        batch_num = batch_start // batch_total + 1
        total_batches = (len(pending_ids) + batch_total - 1) // batch_total

        print(f"\n  [批次 {batch_num}/{total_batches}] 处理 {len(batch_ids)} 条...")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for item_id in batch_ids:
                item = dataset[item_id]
                future = executor.submit(_worker_generate, item_id, item, MODEL_PRO)
                futures[future] = item_id

            for future in as_completed(futures):
                try:
                    item_id, attack = future.result()
                    if attack:
                        attacks.append(attack)
                    # 即使 attack 为 None（验证失败）也标记已完成，不再重试
                    completed.add(item_id)
                except Exception as e:
                    item_id = futures[future]
                    tprint(f"  [{item_id}] Worker 异常: {e}")
                    completed.add(item_id)

        # 批次完成后保存进度
        progress["completed_generation_ids"] = list(completed)
        progress["generated_attacks"] = attacks
        progress["phase"] = "generation"
        save_progress(progress)
        save_json(attacks, "01_initial_attacks.json")
        print(f"  [进度] 已保存: {len(attacks)} 条攻击 (进度 {len(completed)}/{total})")

    # 最终保存
    progress["completed_generation_ids"] = list(completed)
    progress["generated_attacks"] = attacks
    progress["phase"] = "generation_done"
    save_progress(progress)
    save_json(attacks, "01_initial_attacks.json")

    print(f"\n  ✅ Phase 1 完成! 共生成 {len(attacks)} 条攻击")
    return attacks


# ============================================================
# Phase 2: 评估
# ============================================================

def evaluate_single_item(client: OpenAI, item: dict, text_attack: str,
                         model: str = MODEL_FLASH) -> dict:
    """
    评估单条样本，返回:
      { "id", "mir_orig", "mir_attack", "score",
        "orig_counts", "attack_counts", "orig_answers", "attack_answers" }
    """
    item_id = item["id"]
    hypothesis = item["hypothesis"]
    text_original = item["text_original"]

    tprint(f"\n  [{item_id}] 原句评估")
    tprint(f"    text: {text_original[:80]}...")
    result_orig = multi_turn_eval(client, text_original, hypothesis,
                                  label=f"{item_id}-原句", model=model)
    tprint(f"    → MIR_orig = {result_orig['mir']:.4f}  (分布: {result_orig['counts']})")

    tprint(f"\n  [{item_id}] 攻击句评估")
    tprint(f"    text: {text_attack[:80]}...")
    result_atk = multi_turn_eval(client, text_attack, hypothesis,
                                 label=f"{item_id}-攻击", model=model)
    tprint(f"    → MIR_attack = {result_atk['mir']:.4f}  (分布: {result_atk['counts']})")

    score = round(max(result_atk["mir"] - result_orig["mir"], 0), 4)
    tprint(f"    → Score = {score:.4f} {'✅' if score >= SCORE_THRESHOLD else '❌'}")

    return {
        "id": item_id,
        "predicate": item.get("predicate", ""),
        "text_original": text_original,
        "text_attack": text_attack,
        "hypothesis": hypothesis,
        "mir_orig": result_orig["mir"],
        "mir_attack": result_atk["mir"],
        "score": score,
        "orig_counts": result_orig["counts"],
        "attack_counts": result_atk["counts"],
        "orig_answers": result_orig["answers"],
        "attack_answers": result_atk["answers"],
    }


def _worker_evaluate(item_id: str, dataset: dict, attacks: dict, model: str):
    """Worker: 评估单条攻击（每个线程独立 client）"""
    if item_id not in dataset:
        return item_id, None, "不在数据集中"

    item = dataset[item_id]
    attack_entry = attacks.get(item_id)
    if isinstance(attack_entry, dict):
        text_attack = attack_entry.get("text_attack", "")
        strategy = attack_entry.get("strategy", "")
    else:
        text_attack = attack_entry or ""
        strategy = ""

    client = init_client()
    eval_result = evaluate_single_item(client, item, text_attack, model=model)
    eval_result["strategy"] = strategy
    return item_id, eval_result, None


def phase_evaluate(client: OpenAI, dataset: dict, attacks: dict,
                   progress: dict, round_num: int,
                   eval_output_file: str, workers: int = MAX_WORKERS,
                   existing_qualified_count: int = 0,
                   target: int = 0) -> list:
    """
    并行评估攻击效果。
    attacks: {id: {"text_attack": str, "strategy": str}} 或 {id: text_attack_str}
    existing_qualified_count: 已有合格数（用于提前终止判断）
    target: 目标合格数，>0 时开启提前终止
    返回: 评估结果列表 [{id, mir_orig, mir_attack, score, ...}]
    """
    eval_key = f"eval_round{round_num}_completed"
    completed = set(progress.get(eval_key, []))
    results = progress.get(f"eval_round{round_num}_results", [])
    results_dict = {r["id"]: r for r in results}  # 用于去重

    pending_ids = [iid for iid in attacks.keys() if iid not in completed]

    print(f"\n{'=' * 60}")
    print(f"Phase 2: 攻击评估 (Round {round_num}) | 并行度: {workers}")
    print(f"  待评估: {len(pending_ids)} 条 | 已完成: {len(completed)}")
    print(f"{'=' * 60}")

    if not pending_ids:
        print("  → 全部已完成，跳过评估阶段")
        return results

    # 分批并行处理
    batch_total = workers * 5
    for batch_start in range(0, len(pending_ids), batch_total):
        batch_ids = pending_ids[batch_start:batch_start + batch_total]
        batch_num = batch_start // batch_total + 1
        total_batches = (len(pending_ids) + batch_total - 1) // batch_total

        print(f"\n  [批次 {batch_num}/{total_batches}] 评估 {len(batch_ids)} 条...")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for item_id in batch_ids:
                future = executor.submit(_worker_evaluate, item_id, dataset, attacks, MODEL_FLASH)
                futures[future] = item_id

            for future in as_completed(futures):
                try:
                    item_id, eval_result, error = future.result()
                    if error:
                        tprint(f"  [{item_id}] 跳过: {error}")
                        completed.add(item_id)
                    elif eval_result:
                        results_dict[item_id] = eval_result
                        completed.add(item_id)
                except Exception as e:
                    item_id = futures[future]
                    tprint(f"  [{item_id}] Worker 异常: {e}")
                    completed.add(item_id)

        # 重建有序列表
        results = [results_dict[iid] for iid in sorted(results_dict.keys())]

        # 批次完成后保存进度
        progress[eval_key] = list(completed)
        progress[f"eval_round{round_num}_results"] = results
        save_progress(progress)
        save_json(results, eval_output_file)
        print(f"  [进度] 已评估 {len(results)} 条，保存至 {eval_output_file}")

        # 提前终止检查：已有合格 + 本轮新合格 >= 目标
        if target > 0:
            new_qualified = sum(1 for r in results_dict.values()
                                if r.get("score", 0) >= SCORE_THRESHOLD)
            if existing_qualified_count + new_qualified >= target:
                print(f"\n  🎯 提前终止！已有合格 {existing_qualified_count} + 本轮新合格 {new_qualified} = "
                      f"{existing_qualified_count + new_qualified} 条 ≥ 目标 {target}，停止评估")
                break

    # 最终保存
    results = [results_dict[iid] for iid in sorted(results_dict.keys())]
    progress[eval_key] = list(completed)
    progress[f"eval_round{round_num}_results"] = results
    save_progress(progress)
    save_json(results, eval_output_file)

    # 打印汇总
    qualified = [r for r in results if r["score"] >= SCORE_THRESHOLD]
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    total_score = sum(r["score"] for r in results)
    print(f"\n  📊 Round {round_num} 评估汇总:")
    print(f"     总评估: {len(results)} 条")
    print(f"     合格 (Score≥{SCORE_THRESHOLD}): {len(qualified)} 条")
    print(f"     平均 Score: {avg_score:.4f}")
    print(f"     总 Score: {total_score:.4f}")

    return results


# ============================================================
# Phase 3: 筛选与排序
# ============================================================

def filter_and_sort(eval_results: list, round_num: int,
                    progress: dict):
    """
    将评估结果分为合格池和低分池。
    - 合格 (score >= threshold) → 移入 qualified_pool
    - 低分 (score < threshold) → 按攻击潜力排序后放入 low_score_pool

    排序规则（优先攻击容易的）:
      P1: score 降序（当前得分越高，越接近目标）
      P2: mir_orig 降序（原句本身不稳定，更容易攻破）
      P3: (mir_attack - mir_orig) 降序（提升幅度大，策略方向对）
    """
    qualified_pool = progress.get("qualified_pool", {})
    low_score_pool = progress.get("low_score_pool", {})

    new_qualified = []
    new_low_score = []

    for r in eval_results:
        if r["score"] >= SCORE_THRESHOLD:
            qualified_pool[r["id"]] = r
            new_qualified.append(r)
        else:
            low_score_pool[r["id"]] = r
            new_low_score.append(r)

    # 低分池排序
    low_score_sorted = sorted(
        low_score_pool.values(),
        key=lambda x: (
            x.get("score", 0),
            x.get("mir_orig", 0),
            x.get("mir_attack", 0) - x.get("mir_orig", 0),
        ),
        reverse=True,
    )

    # 保存
    save_json(list(qualified_pool.values()),
              f"{'03' if round_num == 1 else f'{4 * round_num - 1:02d}'}_qualified_round{round_num}.json")
    save_json(low_score_sorted,
              f"{'04' if round_num == 1 else f'{4 * round_num:02d}'}_lowscore_round{round_num}_sorted.json")
    save_json(list(qualified_pool.values()), "cumulative_qualified.json")

    progress["qualified_pool"] = qualified_pool
    progress["low_score_pool"] = {r["id"]: r for r in low_score_sorted}
    progress["phase"] = f"round{round_num}_filtered"
    save_progress(progress)

    print(f"\n  📊 筛选结果 (Round {round_num}):")
    print(f"     合格池累计: {len(qualified_pool)} 条")
    print(f"     低分池剩余: {len(low_score_sorted)} 条")
    if new_qualified:
        print(f"     本轮新增合格: {len(new_qualified)} 条")
        for r in sorted(new_qualified, key=lambda x: x["score"], reverse=True)[:5]:
            print(f"       [{r['id']}] Score={r['score']:.4f}")

    return qualified_pool, low_score_sorted


# ============================================================
# Phase 4: 精炼攻击（Pro 模型）
# ============================================================

def refine_single_attack(client: OpenAI, eval_result: dict,
                         dataset: dict) -> dict:
    """
    基于上次评估结果，使用 Pro 模型重新生成攻击。
    生成后内联验证 R2-R4，失败则反馈重试，最多 VALIDATE_MAX_RETRIES 次。
    返回: {"id": str, "text_attack": str, "strategy": str, ...} 或 None
    """
    item_id = eval_result["id"]
    item = dataset.get(item_id)
    if not item:
        return None

    # 提取上次攻击信息
    orig_max_count = max(
        [v for k, v in eval_result.get("orig_counts", {}).items() if k in ("T", "F", "U")],
        default=0
    )
    attack_max_count = max(
        [v for k, v in eval_result.get("attack_counts", {}).items() if k in ("T", "F", "U")],
        default=0
    )
    score_gap = round(SCORE_THRESHOLD - eval_result["score"], 4)

    prompt = REFINE_USER_TEMPLATE.format(
        text_original=item["text_original"],
        predicate=item["predicate"],
        hypothesis=item["hypothesis"],
        previous_attack=eval_result.get("text_attack", ""),
        previous_strategy=eval_result.get("strategy", "未知"),
        mir_orig=eval_result["mir_orig"],
        mir_attack=eval_result["mir_attack"],
        orig_max_count=orig_max_count,
        attack_max_count=attack_max_count,
        score=eval_result["score"],
        score_gap=score_gap,
    )

    # 第一次生成
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_PRO,
                messages=[
                    {"role": "system", "content": REFINE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.8,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = response.choices[0].message.content or ""
            parsed = parse_attack_response(raw)
            if parsed:
                strategy, sentence = parsed[0]
                break
            else:
                tprint(f"    [警告] Pro 模型解析失败: {raw[:100]}...")
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                tprint(f"    [重试 {attempt + 1}/{MAX_RETRIES}] Pro 生成失败: {e}，等待 {wait}s")
                time.sleep(wait)
            else:
                tprint(f"    [失败] Pro 生成最终失败: {e}")
                return None
    else:
        return None

    # 验证+重试循环
    for validate_attempt in range(VALIDATE_MAX_RETRIES):
        errors = validate_attack_inline(sentence, item)
        if not errors:
            return {
                "id": item_id,
                "text_attack": sentence,
                "strategy": strategy,
                "prev_score": eval_result["score"],
                "prev_strategy": eval_result.get("strategy", ""),
            }

        # 验证失败，反馈重试
        tprint(f"    [{item_id}] 精炼验证失败({validate_attempt+1}/{VALIDATE_MAX_RETRIES}): {'; '.join(errors)}")

        if validate_attempt >= VALIDATE_MAX_RETRIES - 1:
            break

        retry_prompt = VALIDATE_RETRY_TEMPLATE.format(
            errors="\n".join(f"- {e}" for e in errors),
            text_original=item["text_original"],
            predicate=item["predicate"],
            hypothesis=item["hypothesis"],
            failed_attack=sentence,
        )

        try:
            response = client.chat.completions.create(
                model=MODEL_PRO,
                messages=[
                    {"role": "system", "content": REFINE_SYSTEM_PROMPT},
                    {"role": "user", "content": retry_prompt},
                ],
                max_tokens=2048,
                temperature=0.8,
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = response.choices[0].message.content or ""
            parsed = parse_attack_response(raw)
            if parsed:
                strategy, sentence = parsed[0]
            else:
                tprint(f"    [警告] 精炼重试解析失败: {raw[:100]}...")
        except Exception as e:
            tprint(f"    [重试失败] 精炼验证重生成异常: {e}")

    # 验证始终失败
    tprint(f"    [{item_id}] ❗ 精炼验证始终失败，放弃该条目")
    return None


def _worker_refine(eval_result: dict, dataset: dict):
    """Worker: 精炼单条攻击（每个线程独立 client）"""
    item_id = eval_result["id"]
    client = init_client()
    refined = refine_single_attack(client, eval_result, dataset)
    if refined:
        tprint(f"  [{item_id}] ✅ 精炼完成 | 新策略: {refined['strategy'][:40]}")
        return item_id, refined
    else:
        # 精炼失败（验证未通过），保留原攻击供后续评估
        tprint(f"  [{item_id}] ❌ 精炼失败，保留原攻击")
        return item_id, {
            "id": item_id,
            "text_attack": eval_result.get("text_attack", ""),
            "strategy": eval_result.get("strategy", "") + " (精炼失败-保留原版)",
        }


def phase_refine(client: OpenAI, low_score_sorted: list,
                 dataset: dict, round_num: int,
                 progress: dict, workers: int = MAX_WORKERS) -> dict:
    """
    并行精炼：对低分池条目使用 Pro 模型重新生成攻击。
    返回: {id: {"text_attack": str, "strategy": str}}
    """
    refine_key = f"refine_round{round_num}_completed"
    completed = set(progress.get(refine_key, []))
    refined_attacks = progress.get(f"refine_round{round_num}_attacks", {})

    pending = [r for r in low_score_sorted if r["id"] not in completed]

    output_file = f"{4 * round_num + 1:02d}_refined_attacks_round{round_num + 1}.json"

    print(f"\n{'=' * 60}")
    print(f"Phase 4: Pro 模型精炼攻击 (Round {round_num} → {round_num + 1}) | 并行度: {workers}")
    print(f"  模型: {MODEL_PRO}")
    print(f"  待精炼: {len(pending)} 条 | 已完成: {len(completed)}")
    print(f"{'=' * 60}")

    if not pending:
        print("  → 无待精炼条目，跳过")
        return refined_attacks

    # 分批并行处理
    batch_total = workers * 10
    for batch_start in range(0, len(pending), batch_total):
        batch_ids = pending[batch_start:batch_start + batch_total]
        batch_num = batch_start // batch_total + 1
        total_batches = (len(pending) + batch_total - 1) // batch_total

        print(f"\n  [批次 {batch_num}/{total_batches}] 精炼 {len(batch_ids)} 条...")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for eval_result in batch_ids:
                future = executor.submit(_worker_refine, eval_result, dataset)
                futures[future] = eval_result["id"]

            for future in as_completed(futures):
                try:
                    item_id, result = future.result()
                    refined_attacks[item_id] = result
                    completed.add(item_id)
                except Exception as e:
                    item_id = futures[future]
                    tprint(f"  [{item_id}] Worker 异常: {e}")
                    completed.add(item_id)

        # 批次完成后保存进度
        progress[refine_key] = list(completed)
        progress[f"refine_round{round_num}_attacks"] = refined_attacks
        save_progress(progress)
        refined_list = [
            {"id": iid, "text_attack": v["text_attack"], "strategy": v.get("strategy", "")}
            for iid, v in refined_attacks.items()
        ]
        save_json(refined_list, output_file)
        print(f"  [进度] 已精炼 {len(refined_attacks)} 条")

    progress[refine_key] = list(completed)
    progress[f"refine_round{round_num}_attacks"] = refined_attacks
    save_progress(progress)

    refined_list = [
        {"id": iid, "text_attack": v["text_attack"], "strategy": v.get("strategy", "")}
        for iid, v in refined_attacks.items()
    ]
    save_json(refined_list, output_file)

    print(f"\n  ✅ 精炼完成! 共处理 {len(refined_attacks)} 条")
    return refined_attacks


# ============================================================
# 最终提交生成
# ============================================================

def generate_final_submission(qualified_pool: dict, low_score_pool: dict,
                             target: int = TARGET_COUNT):
    """
    生成最终提交的 200 条攻击样本。

    策略（最大化 AttackScore）：
    1. 优先取合格池（Score ≥ 0.5）的条目，按 Score 降序排列
    2. 如果合格池 ≥ 200 条：取 Top 200，优先保留 Score 高的（0.6 > 0.5）
    3. 如果合格池 < 200 条：全部纳入，剩余从低分池按 Score 降序补足到 200
    """
    sorted_qualified = sorted(
        qualified_pool.values(),
        key=lambda x: x.get("score", 0),
        reverse=True,
    )

    if len(sorted_qualified) >= target:
        # 合格池充足：取 Top 200，高分优先
        top_n = sorted_qualified[:target]
        fill_count = 0
        print(f"  合格池充足 ({len(sorted_qualified)} ≥ {target})，按 Score 降序取 Top {target}")
    else:
        # 合格池不足：全部纳入 + 从低分池补齐
        shortage = target - len(sorted_qualified)
        print(f"  合格池不足 ({len(sorted_qualified)} < {target})，缺 {shortage} 条，从低分池补齐")

        sorted_low = sorted(
            low_score_pool.values(),
            key=lambda x: x.get("score", 0),
            reverse=True,
        )

        # 补齐：取前 shortage 条低分条目
        fill_items = sorted_low[:shortage]
        top_n = sorted_qualified + fill_items
        fill_count = len(fill_items)

        if fill_count < shortage:
            print(f"  ⚠️ 低分池仅 {len(sorted_low)} 条，实际补齐 {fill_count} 条，总计 {len(top_n)} 条")

    submission = [
        {"id": item["id"], "text_attack": item["text_attack"]}
        for item in top_n
    ]

    save_json(submission, "final_submission.json")

    total_score = sum(item["score"] for item in top_n)
    qualified_in_top = sum(1 for item in top_n if item.get("score", 0) >= SCORE_THRESHOLD)

    print(f"\n{'=' * 60}")
    print(f"🏆 最终提交生成")
    print(f"{'=' * 60}")
    print(f"  合格池总数: {len(sorted_qualified)}")
    print(f"  低分池总数: {len(low_score_pool)}")
    print(f"  提交数量: {len(submission)} (合格 {qualified_in_top} + 补齐 {fill_count})")
    print(f"  AttackScore: {total_score:.4f}")
    print(f"  Score 范围: {top_n[-1]['score']:.4f} ~ {top_n[0]['score']:.4f}")
    print(f"  Top 5:")
    for item in top_n[:5]:
        print(f"    [{item['id']}] Score={item['score']:.4f}")

    return submission


# ============================================================
# 主流程
# ============================================================

def run_pipeline(args):
    """主流水线入口"""
    workers = getattr(args, 'workers', MAX_WORKERS)
    print("=" * 60)
    print("NLPCC2026-Task8 FIIA 迭代攻击流水线")
    print(f"启动时间: {datetime.now().isoformat()}")
    print(f"输出目录: {OUTPUT_DIR}/")
    print(f"目标合格数: {args.target}")
    print(f"分数阈值: {args.threshold}")
    print(f"最大精炼轮数: {args.max_refinement_rounds}")
    print(f"并行线程数: {workers}")
    print("=" * 60)

    # 全局参数覆盖
    global TARGET_COUNT, SCORE_THRESHOLD, MAX_REFINEMENT_ROUNDS
    TARGET_COUNT = args.target
    SCORE_THRESHOLD = args.threshold
    MAX_REFINEMENT_ROUNDS = args.max_refinement_rounds

    # 加载数据集
    dataset = load_dataset(DATASET_PATH)
    print(f"\n数据集加载完成: {len(dataset)} 条")

    # 进度管理
    if args.from_scratch:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print("已删除旧进度文件，从头开始")
        progress = load_progress()
    elif args.resume:
        progress = load_progress()
        print(f"从断点恢复: phase={progress.get('phase')}, round={progress.get('round')}")
    else:
        if os.path.exists(PROGRESS_FILE):
            print("发现已有进度文件，自动从断点恢复。使用 --from-scratch 重新开始。")
        progress = load_progress()

    progress["total_dataset_size"] = len(dataset)
    save_progress(progress)

    client = init_client()

    # ==========================================
    # Round 1: 初始生成 + 评估 + 筛选
    # ==========================================

    if progress.get("phase") in ("init", "generation", "generation_done", None):
        # Phase 1: 生成初始攻击
        attacks_list = phase_generate_initial_attacks(client, dataset, progress, workers=workers)

        # 转为字典便于查找
        attacks_dict = {a["id"]: a for a in attacks_list}
        progress["attacks_dict"] = {
            iid: {"text_attack": a["text_attack"], "strategy": a.get("strategy", "")}
            for iid, a in attacks_dict.items()
        }
        progress["phase"] = "generation_done"
        progress["round"] = 1
        save_progress(progress)

        # Phase 2: 评估
        eval_results = phase_evaluate(
            client, dataset, progress["attacks_dict"],
            progress, round_num=1,
            eval_output_file="02_eval_round1.json",
            workers=workers,
            existing_qualified_count=0,
            target=TARGET_COUNT,
        )
        progress["phase"] = "round1_evaluated"
        save_progress(progress)

        # Phase 3: 筛选
        qualified_pool, low_score_sorted = filter_and_sort(
            eval_results, round_num=1, progress=progress
        )
        progress["phase"] = "round1_filtered"
        save_progress(progress)
    else:
        print(f"\n  → 跳过 Round 1（当前阶段: {progress.get('phase')}）")
        qualified_pool = progress.get("qualified_pool", {})
        low_score_sorted = list(progress.get("low_score_pool", {}).values())

    # ==========================================
    # Round 2~4: 迭代精炼
    # ==========================================

    current_round = progress.get("round", 1)

    for refine_round in range(1, MAX_REFINEMENT_ROUNDS + 1):
        round_label = refine_round + 1  # Round 2, 3, 4

        # 检查终止条件
        if len(qualified_pool) >= TARGET_COUNT:
            print(f"\n  🎯 已达到目标 {TARGET_COUNT} 条合格样本，停止迭代!")
            break

        if not low_score_sorted:
            print("\n  ⚠️ 低分池为空，无法继续精炼")
            break

        if progress.get("phase") == f"round{round_label}_filtered":
            print(f"\n  → Round {round_label} 已完成，跳过")
            qualified_pool = progress.get("qualified_pool", {})
            low_score_sorted = list(progress.get("low_score_pool", {}).values())
            continue

        print(f"\n{'#' * 60}")
        print(f"# 精炼轮次: Round {round_label} / {MAX_REFINEMENT_ROUNDS + 1}")
        print(f"# 当前合格: {len(qualified_pool)} | 目标: {TARGET_COUNT}")
        print(f"# 低分池: {len(low_score_sorted)} 条")
        print(f"{'#' * 60}")

        # Phase 4: 精炼攻击
        progress["round"] = refine_round
        save_progress(progress)

        refined_attacks = phase_refine(
            client, low_score_sorted, dataset,
            round_num=refine_round, progress=progress, workers=workers
        )
        progress["phase"] = f"round{round_label}_refined"
        save_progress(progress)

        # Phase 2+: 重新评估精炼后的攻击
        # 注意：只评估被精炼的条目
        eval_file = f"{4 * round_label - 2:02d}_eval_round{round_label}.json"
        new_eval_results = phase_evaluate(
            client, dataset, refined_attacks,
            progress, round_num=round_label,
            eval_output_file=eval_file,
            workers=workers,
            existing_qualified_count=len(qualified_pool),
            target=TARGET_COUNT,
        )
        progress["phase"] = f"round{round_label}_evaluated"
        save_progress(progress)

        # Phase 3+: 更新池
        # 对于精炼后的条目，更新 qualified_pool 和 low_score_pool
        newly_qualified = []
        still_low = []

        for r in new_eval_results:
            if r["score"] >= SCORE_THRESHOLD:
                qualified_pool[r["id"]] = r
                newly_qualified.append(r)
                # 从低分池移除
                progress.get("low_score_pool", {}).pop(r["id"], None)
            else:
                still_low.append(r)
                progress.setdefault("low_score_pool", {})[r["id"]] = r

        # 更新低分池排序
        low_score_sorted = sorted(
            progress.get("low_score_pool", {}).values(),
            key=lambda x: (
                x.get("score", 0),
                x.get("mir_orig", 0),
                x.get("mir_attack", 0) - x.get("mir_orig", 0),
            ),
            reverse=True,
        )

        # 保存
        save_json(newly_qualified,
                  f"{4 * round_label - 1:02d}_qualified_round{round_label}.json")
        save_json(low_score_sorted,
                  f"{4 * round_label:02d}_lowscore_round{round_label}_sorted.json")
        save_json(list(qualified_pool.values()), "cumulative_qualified.json")

        progress["qualified_pool"] = qualified_pool
        progress["low_score_pool"] = {r["id"]: r for r in low_score_sorted}
        progress["phase"] = f"round{round_label}_filtered"
        progress["round"] = round_label
        save_progress(progress)

        print(f"\n  📊 Round {round_label} 完成:")
        print(f"     本轮新增合格: {len(newly_qualified)} 条")
        print(f"     合格池累计: {len(qualified_pool)} 条")
        print(f"     低分池剩余: {len(low_score_sorted)} 条")
        if newly_qualified:
            for r in sorted(newly_qualified, key=lambda x: x["score"], reverse=True)[:5]:
                print(f"       [{r['id']}] Score={r['score']:.4f}")

    # ==========================================
    # 最终提交
    # ==========================================
    final_submission = generate_final_submission(
        qualified_pool, progress.get("low_score_pool", {}), target=TARGET_COUNT
    )

    # 最终进度保存
    progress["phase"] = "completed"
    progress["final_submission_count"] = len(final_submission)
    save_progress(progress)

    print(f"\n{'=' * 60}")
    print("✅ 流水线执行完成!")
    print(f"   最终提交: results-v2/final_submission.json")
    print(f"   提交条目数: {len(final_submission)}")
    print(f"   合格池总数: {len(qualified_pool)}")
    print(f"{'=' * 60}")

    return final_submission


# ============================================================
# CLI
# ============================================================

def main():
    global OUTPUT_DIR, PROGRESS_FILE, BATCH_SIZE, MAX_WORKERS

    parser = argparse.ArgumentParser(
        description="FIIA 迭代攻击流水线 — 生成→评估→筛选→精炼 循环"
    )
    parser.add_argument("--resume", action="store_true",
                        help="从断点恢复")
    parser.add_argument("--from-scratch", action="store_true",
                        help="忽略进度文件，从头开始")
    parser.add_argument("--target", type=int, default=TARGET_COUNT,
                        help=f"目标合格条目数（默认: {TARGET_COUNT}）")
    parser.add_argument("--threshold", type=float, default=SCORE_THRESHOLD,
                        help=f"合格分数阈值（默认: {SCORE_THRESHOLD}）")
    parser.add_argument("--max-refinement-rounds", type=int, default=MAX_REFINEMENT_ROUNDS,
                        help=f"最大精炼轮数（默认: {MAX_REFINEMENT_ROUNDS}）")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help=f"每批保存进度大小（默认: {BATCH_SIZE}）")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"并行工作线程数，调高可加速但注意 API 限流（默认: {MAX_WORKERS}）")
    parser.add_argument("--output-dir", type=str, default=OUTPUT_DIR,
                        help=f"输出目录（默认: {OUTPUT_DIR}）")
    args = parser.parse_args()

    OUTPUT_DIR = args.output_dir
    PROGRESS_FILE = os.path.join(OUTPUT_DIR, "progress.json")
    BATCH_SIZE = args.batch_size
    MAX_WORKERS = args.workers

    run_pipeline(args)


if __name__ == "__main__":
    main()
