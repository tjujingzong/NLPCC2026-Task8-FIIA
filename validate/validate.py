import json
import argparse
from transformers import pipeline, AutoModelForMaskedLM, AutoTokenizer
import warnings
import torch

# ================================================================================
# NLPCC-2026 FIIA 评测任务：本地准入核验脚本 (Fluency 增强版)
# ================================================================================

USE_LOCAL = False  # 是否使用本地模型

LCS_COVERAGE_THRESHOLD = 0.7 # “小句完整性”阈值
SIM_THRESHOLD = 0.65 # “文本保留度”阈值
FLUENCY_SCORE_THRESHOLD = 0.6  # “通顺保持度”阈值

warnings.filterwarnings("ignore")


def calculate_levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return calculate_levenshtein_distance(s2, s1)
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


def load_fluency_evaluator():
    model_id = "../hfl_macbert_base" if USE_LOCAL else "hfl/chinese-macbert-base"
    print(f"[1/3] 正在加载通顺度检测模型 ({model_id})...")
    try:
        # 加载用于计算 Loss 的组件
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForMaskedLM.from_pretrained(model_id)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        print(f" -> 模型加载成功，运行设备: {device}\n")
        return {"tokenizer": tokenizer, "model": model, "device": device}
    except Exception as e:
        print(f" -> [错误] 模型加载失败: {e}")
        return None


def calculate_fluency_loss(text, evaluator):
    """计算句子的平均交叉熵 Loss"""
    if not text.strip():
        return 99.0
    tokenizer = evaluator["tokenizer"]
    model = evaluator["model"]
    
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512).to(evaluator["device"])
    labels = inputs["input_ids"].clone()
    
    with torch.no_grad():
        outputs = model(**inputs, labels=labels)
        loss = outputs.loss
    return loss.item()


def calculate_relative_fluency_score(orig_loss, attack_loss):
    """
    基于原句 loss 和改编句 loss 计算相对通顺度保持分。
    返回:
    - loss_change_rate: loss 相对变化率，范围 [-1, +∞)
    - fluency_score: [0,1]，越接近 1 表示相对原句越没有劣化
    """
    if orig_loss <= 0:
        loss_change_rate = 0.0 if attack_loss <= 0 else float("inf")
    else:
        loss_change_rate = (attack_loss - orig_loss) / orig_loss

    worsening = max(0.0, loss_change_rate)
    fluency_score = 1 / (1 + worsening)

    return loss_change_rate, fluency_score


def get_attacked_text(item):
    return item.get("text_attack", "")


def check_required_fields(item):
    errors = []
    required_fields = ["id", "text_attack"]
    for field in required_fields:
        if field not in item:
            errors.append(f"R1: 缺少{field}字段")
    
    return errors


def calculate_lcs_length(a, b):
    """
    计算两个字符串的最长公共子序列长度。
    注意：Longest Common Subsequence，不要求连续，但要求顺序一致。
    """
    if not a or not b:
        return 0

    m, n = len(a), len(b)

    # 一维 DP，空间复杂度 O(n)
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

def calculate_lcs_coverage(hypothesis, text):
    """
    计算 hypothesis 相对于 text 的 LCS 覆盖率。
    coverage = LCS(hypothesis, text) / len(hypothesis)
    即：hypothesis 中有多少比例的字符能按顺序在 text 中找到。
    """
    if not hypothesis:
        return 0.0

    lcs_len = calculate_lcs_length(hypothesis, text)
    return lcs_len / len(hypothesis)

def normalize_for_lcs(text):
    """
    用于 predicate/hypothesis 保留检查的轻量规范化。
    只去除空白和常见标点，不改变实质字符。
    """
    if text is None:
        return ""
    remove_chars = set(" \t\r\n，。！？；：、“”‘’\"'（）()《》〈〉【】[]{}.,!?;:-—…·")
    return "".join(ch for ch in str(text).strip() if ch not in remove_chars)

def check_rules(item, orig, evaluator):
    errors = []

    text = get_attacked_text(item).strip()
    predicate = orig.get("predicate", "")
    hypothesis = orig.get("hypothesis", "")
    text_original = orig.get("text_original", "")
    
    print("\n原句：", text_original)
    print("改编：", text)
    # print("原始predicate：", predicate)
    # print("原始hypothesis：", hypothesis)

    # R2 谓词完整性
    if predicate not in text:
        errors.append("R2: text 中缺失 predicate")

    # R3 小句完整性
    # 不要求 hypothesis 是 text 的连续子串；只要求 hypothesis 的主要字符能按顺序在 text 中找到。
    norm_hyp = normalize_for_lcs(hypothesis)
    norm_text = normalize_for_lcs(text)
    lcs_coverage = calculate_lcs_coverage(norm_hyp, norm_text)
    print(f"R3 小句完整性：{lcs_coverage:.3f}")
    if lcs_coverage < LCS_COVERAGE_THRESHOLD:
        errors.append(
            f"R3: 小句完整性过低 (coverage={lcs_coverage:.3f} < {LCS_COVERAGE_THRESHOLD})"
        )

    # R4 文本保留度
    if 'text_original' in orig:
        a, b = orig['text_original'], text
        dist = calculate_levenshtein_distance(a, b)
        edit_ratio = dist / max(len(a), len(b))
        similarity = 1 - edit_ratio
        print(f"R4 文本保留度：{similarity:.3f}")
        if similarity < SIM_THRESHOLD:
            errors.append(f"R4: 文本保留度过低 (similarity={similarity:.3f} <{SIM_THRESHOLD})")

    # R5 通顺保持度
    orig_loss = calculate_fluency_loss(orig["text_original"], evaluator)
    attack_loss = calculate_fluency_loss(text, evaluator)
    loss_change_rate, fluency_score = calculate_relative_fluency_score(orig_loss, attack_loss)
    print(f"R5 通顺保持度：{fluency_score:.3f}")
    if fluency_score < FLUENCY_SCORE_THRESHOLD:
        errors.append(f"R5: 通顺保持度过低 (fluency_score={fluency_score:.3f} <{FLUENCY_SCORE_THRESHOLD})")

    return errors


def verify_submission(original_file, submission_file):
    print("=== NLPCC-2026 FIIA 准入核验启动 ===\n")

    evaluator = load_fluency_evaluator()
    if not evaluator: return

    try:
        with open(original_file, 'r', encoding='utf-8') as f:
            original_data = {item['id']: item for item in json.load(f)}
        with open(submission_file, 'r', encoding='utf-8') as f:
            submission_data = json.load(f)
    except Exception as e:
        print(f"[错误] 文件读取失败: {e}")
        return

    valid_ids = set(original_data.keys())
    ITEM_LMT = 200
    if len(submission_data) > ITEM_LMT:
        print(f"[警告] 当前的改编数据共 {len(submission_data)} 条。本程序会检测全部条目，但最终提交时仅将前 {ITEM_LMT} 条计入最终成绩，超出部分为无效题，请知悉。\n")
        # submission_data = submission_data[:ITEM_LMT]

    failed_items = []
    seen_ids = set()
    print(f"[2/3] 开始核验 {len(submission_data)} 条数据...\n")

    for item in submission_data:
        # 1. Field & ID Check
        item_id = item.get('id')
        errors = check_required_fields(item)
        if errors:
            reason = "; ".join(errors)
            failed_items.append((item_id or "Unknown", reason))
            print(f"[{item_id or 'Unknown'}] Fail: {reason}")
            continue

        if item_id in seen_ids:
            reason = "R1: ID重复"
            failed_items.append((item_id, reason))
            print(f"[{item_id}] Fail: {reason}")
            continue
        seen_ids.add(item_id)

        if item_id not in valid_ids:
            reason = "R1: ID非法或不存在"
            failed_items.append((item_id, reason))
            print(f"[{item_id}] Fail: {reason}")
            continue
        
        # 2. Content Check
        orig = original_data[item_id]
        errors = check_rules(item, orig, evaluator)

        if errors:
            reason = "; ".join(errors)
            failed_items.append((item_id, reason))
            print(f"[{item_id}] Fail: {reason}")
        else:
            print(f"[{item_id}] OK.")

    print("\n[3/3] 核验完成。")
    if not failed_items:
        print(">>> 🏆 全部校验通过！您可以放心提交。")
    else:
        print(f">>> ⚠️ 校验存在问题: {len(failed_items)}条。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", default="FIIA_dataset_full.no_queshi_auto.json")
    parser.add_argument("--submission", default="submission_example.json")
    args = parser.parse_args()
    verify_submission(args.original, args.submission)
