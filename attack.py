"""
NLPCC2026-Task8 FIIA 攻击流水线 (Track B: DeepSeek)

功能:
  1. 加载原始数据集
  2. 对原句 (text_original) 做 10 轮 API 调用，计算 MIR_orig
  3. 对攻击句 (text_attack) 做 10 轮 API 调用，计算 MIR_attack
  4. 计算单条攻击得分 Score_i = max(MIR_attack - MIR_orig, 0)
  5. 汇总输出并按得分排序

使用:
  1. 复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
  2. python attack.py --mode eval --items 0001,0003,0005
  3. python attack.py --mode full --limit 10
"""

import os
import re
import json
import time
import argparse
from collections import Counter
from dotenv import load_dotenv
from openai import OpenAI

# ============================================================
# 配置
# ============================================================
load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-v4-flash"
DATASET_PATH = "dataset/fiia_0427.json"
NUM_ROUNDS = 10  # 每条样本调用轮数
MAX_RETRIES = 3  # 单次调用最大重试次数

PROMPT_TEMPLATE = """根据"文本"的内容，判断"假设"的真值情况：
文本：{text}
假设：{hypothesis}
只允许答复T/F/U（对应真/假/无法确定），禁止回复其他解释性内容。"""

# ============================================================
# DeepSeek API 调用
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
    
    # 尝试匹配 "X" 或 X\n 或 X。 等模式
    m = re.search(r'\b([TFU])\b', text)
    if m:
        return m.group(1)
    
    # 宽松匹配：第一个 T/F/U 字符
    for ch in text:
        if ch in ("T", "F", "U"):
            return ch
    
    return "R"


def call_model(client: OpenAI, text: str, hypothesis: str) -> str:
    """
    单次调用 DeepSeek，返回提取的答案 (T/F/U/R)。
    带重试逻辑。
    """
    prompt = PROMPT_TEMPLATE.format(text=text, hypothesis=hypothesis)
    
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=10,
                temperature=1.0,  # DeepSeek 官方默认值
                extra_body={"thinking": {"type": "disabled"}},  # 禁用思考模式
            )
            raw = response.choices[0].message.content or ""
            return extract_answer(raw)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                print(f"    [重试 {attempt + 1}/{MAX_RETRIES}] API 错误: {e}，等待 {wait} 秒...")
                time.sleep(wait)
            else:
                print(f"    [失败] API 调用最终失败: {e}")
                return "R"
    return "R"


def multi_turn_eval(client: OpenAI, text: str, hypothesis: str,
                    label: str = "") -> dict:
    """
    对一条样本做 NUM_ROUNDS 轮调用，返回:
      { "answers": [T,F,U,...], "counts": {T:n, F:n, U:n, R:n}, "mir": float }
    """
    answers = []
    for i in range(NUM_ROUNDS):
        ans = call_model(client, text, hypothesis)
        answers.append(ans)
        print(f"    [{label}] 轮次 {i + 1}/{NUM_ROUNDS} → {ans}")
        if i < NUM_ROUNDS - 1:
            time.sleep(0.5)  # 避免触发频率限制

    counts = dict(Counter(answers))
    # 只统计有效回答 T/F/U（R 不计入一致性计算）
    valid = {k: v for k, v in counts.items() if k in ("T", "F", "U")}
    total_valid = sum(valid.values())
    
    if total_valid == 0:
        mir = 0.0  # 全是 R，无法评估一致性
    else:
        max_count = max(valid.values())
        mir = round(1.0 - max_count / total_valid, 4)

    return {"answers": answers, "counts": counts, "mir": mir}


# ============================================================
# 数据集加载 & 提交加载
# ============================================================

def load_dataset(path: str = DATASET_PATH) -> dict:
    """加载原始数据集，返回 {id: item} 字典"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["id"]: item for item in data}


def load_attacks(path: str) -> dict:
    """加载攻击样本文件，返回 {id: text_attack} 字典"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["id"]: item["text_attack"] for item in data}


# ============================================================
# 主流程
# ============================================================

def evaluate_single_item(client: OpenAI, item: dict,
                         text_attack: str = None) -> dict:
    """
    评估单条样本的原始 MIR 和攻击 MIR。
    
    Returns:
      {
        "id": str,
        "mir_orig": float,
        "mir_attack": float | None,
        "score": float | None,
        "orig_counts": dict,
        "attack_counts": dict | None,
      }
    """
    item_id = item["id"]
    hypothesis = item["hypothesis"]
    text_original = item["text_original"]

    print(f"\n{'=' * 60}")
    print(f"[{item_id}] 原句评估")
    print(f"  text: {text_original[:80]}...")
    print(f"  hypothesis: {hypothesis}")
    
    result_orig = multi_turn_eval(client, text_original, hypothesis, label="原句")
    print(f"  → MIR_orig = {result_orig['mir']:.4f}  (分布: {result_orig['counts']})")

    result = {
        "id": item_id,
        "mir_orig": result_orig["mir"],
        "mir_attack": None,
        "score": None,
        "orig_counts": result_orig["counts"],
        "attack_counts": None,
    }

    if text_attack:
        print(f"\n[{item_id}] 攻击句评估")
        print(f"  text: {text_attack[:80]}...")
        result_atk = multi_turn_eval(client, text_attack, hypothesis, label="攻击句")
        print(f"  → MIR_attack = {result_atk['mir']:.4f}  (分布: {result_atk['counts']})")
        
        score = round(max(result_atk["mir"] - result_orig["mir"], 0), 4)
        print(f"  → Score = {score:.4f}")
        
        result["mir_attack"] = result_atk["mir"]
        result["score"] = score
        result["attack_counts"] = result_atk["counts"]

    return result


def eval_mode(client: OpenAI, dataset: dict, item_ids: list,
              attacks: dict = None, output_path: str = None):
    """评估指定 ID 的样本（调试 / 小规模验证用）"""
    results = []
    for item_id in item_ids:
        if item_id not in dataset:
            print(f"[警告] ID {item_id} 不在数据集中，跳过")
            continue
        item = dataset[item_id]
        text_attack = attacks.get(item_id) if attacks else None
        result = evaluate_single_item(client, item, text_attack)
        results.append(result)

    print_summary(results)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存至: {output_path}")


def full_mode(client: OpenAI, dataset: dict, attacks: dict = None, limit: int = 10,
             output_path: str = None):
    """全量评估模式：遍历数据集前 N 条"""
    results = []
    for i, (item_id, item) in enumerate(dataset.items()):
        if i >= limit:
            break
        text_attack = attacks.get(item_id) if attacks else None
        result = evaluate_single_item(client, item, text_attack)
        results.append(result)
        # 每条之间稍作暂停，避免 API 限流
        if i < limit - 1:
            time.sleep(1.0)

    print_summary(results)

    # 保存结果到 JSON 文件
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存至: {output_path}")

    return results


def print_summary(results: list):
    """打印汇总"""
    print(f"\n{'=' * 60}")
    print("汇总")
    print(f"{'=' * 60}")
    
    scored = [r for r in results if r["score"] is not None]
    orig_only = [r for r in results if r["score"] is None]
    
    print(f"总样本数: {len(results)}")
    print(f"原句 + 攻击句评估: {len(scored)} 条")
    print(f"仅原句评估: {len(orig_only)} 条")
    
    if scored:
        avg_score = sum(r["score"] for r in scored) / len(scored)
        total_score = sum(r["score"] for r in scored)
        print(f"攻击平均得分: {avg_score:.4f}")
        print(f"攻击总得分 (AttackScore): {total_score:.4f}")
        print(f"\n得分详情:")
        for r in scored:
            print(f"  [{r['id']}] MIR_orig={r['mir_orig']:.4f}  "
                  f"MIR_attack={r['mir_attack']:.4f}  "
                  f"Score={r['score']:.4f}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="FIIA 攻击流水线 (DeepSeek)")
    parser.add_argument("--mode", choices=["eval", "full"], default="eval",
                        help="eval: 评估指定ID; full: 全量评估")
    parser.add_argument("--items", type=str, default="0001",
                        help="要评估的 ID，逗号分隔（eval 模式）")
    parser.add_argument("--limit", type=int, default=10,
                        help="全量模式下评估前 N 条（full 模式）")
    parser.add_argument("--attacks", type=str, default=None,
                        help="攻击样本 JSON 文件路径（可选）")
    parser.add_argument("--dataset", type=str, default=DATASET_PATH,
                        help="数据集路径")
    parser.add_argument("--output", type=str, default="results/attack_results.json",
                        help="结果输出 JSON 文件路径")
    args = parser.parse_args()

    # 初始化
    client = init_client()
    dataset = load_dataset(args.dataset)
    attacks = load_attacks(args.attacks) if args.attacks else None

    if args.mode == "eval":
        item_ids = [x.strip() for x in args.items.split(",")]
        eval_mode(client, dataset, item_ids, attacks, output_path=args.output)
    else:
        full_mode(client, dataset, attacks, limit=args.limit, output_path=args.output)


if __name__ == "__main__":
    main()
