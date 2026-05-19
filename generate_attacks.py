"""
NLPCC2026-Task8 FIIA 攻击样本生成器

使用 DeepSeek API 自动生成 text_attack 候选句。
策略：让模型扮演攻击者，对原句做语言学层面的微小扰动，
     目标是使叙实性推理一致性下降。

使用:
  python generate_attacks.py --items 0001,0003,0005 --output attacks_v1.json
  python generate_attacks.py --limit 20 --output attacks_v1.json
"""

import os
import json
import time
import random
import argparse
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-v4-flash"
DATASET_PATH = "dataset/fiia_0427.json"
VARIANTS_PER_ITEM = 1  # 每条样本生成几个变体

# ============================================================
# 攻击生成 Prompt
# ============================================================

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

请优先使用「让步转折结构 + 多重模糊限定语」的组合策略。只给出1个最佳改编版本，格式如下：

策略：xxx
句子：xxx"""


# ============================================================
# 核心逻辑
# ============================================================

def init_client():
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未找到 DEEPSEEK_API_KEY")
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def load_dataset(path: str = DATASET_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["id"]: item for item in data}


def generate_attacks(client: OpenAI, item: dict, n: int = VARIANTS_PER_ITEM) -> list:
    """
    对单条样本生成 n 个攻击变体。
    返回: [(strategy, text_attack), ...]
    """
    prompt = ATTACK_USER_TEMPLATE.format(
        text_original=item["text_original"],
        predicate=item["predicate"],
        hypothesis=item["hypothesis"],
    )

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": ATTACK_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.9,  # 较高温度增加多样性
                extra_body={"thinking": {"type": "disabled"}},
            )
            raw = response.choices[0].message.content or ""
            return parse_attack_response(raw)
        except Exception as e:
            print(f"    [重试 {attempt + 1}/3] 生成失败: {e}")
            time.sleep(2)

    return []


def parse_attack_response(text: str) -> list:
    """解析模型回复，提取改编句子"""
    results = []
    import re
    # 新格式：策略：xxx\n句子：xxx
    strategy_match = re.search(r'策略[：:]\s*(.+?)(?:\n|$)', text)
    sentence_match = re.search(r'句子[：:]\s*(.+?)(?:\n|$)', text)
    strategy = strategy_match.group(1).strip() if strategy_match else "未标注"
    sentence = sentence_match.group(1).strip() if sentence_match else ""
    
    if not sentence:
        # 回退：尝试旧格式
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


def run_generation(dataset: dict, item_ids: list, output_path: str,
                   n_variants: int = VARIANTS_PER_ITEM):
    """主入口：批量生成攻击样本"""
    client = init_client()
    attacks = []
    total = 0

    for item_id in item_ids:
        if item_id not in dataset:
            print(f"[警告] ID {item_id} 不在数据集中，跳过")
            continue

        item = dataset[item_id]
        print(f"\n[{item_id}] 谓词={item['predicate']}")
        print(f"  原句: {item['text_original'][:80]}...")

        variants = generate_attacks(client, item, n=n_variants)
        print(f"  → 生成 {len(variants)} 个变体")

        for strategy, sentence in variants:
            attacks.append({
                "id": item_id,
                "text_attack": sentence,
                "strategy": strategy,
            })
            print(f"    [{strategy}] {sentence[:60]}...")
            total += 1

        # 避免触发频率限制
        time.sleep(1.0)

    # 保存
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(attacks, f, ensure_ascii=False, indent=2)

    # 也生成一个仅保留 id + text_attack 的提交格式文件
    sub_path = output_path.replace(".json", "_submission.json")
    submission = [{"id": a["id"], "text_attack": a["text_attack"]} for a in attacks]
    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(submission, f, ensure_ascii=False, indent=2)

    print(f"\n完成! 共生成 {total} 条攻击样本")
    print(f"  完整版: {output_path}")
    print(f"  提交版: {sub_path}")


def main():
    parser = argparse.ArgumentParser(description="FIIA 攻击样本生成器")
    parser.add_argument("--items", type=str, default=None,
                        help="要改编的 ID，逗号分隔（如 0001,0003,0005）")
    parser.add_argument("--limit", type=int, default=None,
                        help="改编数据集前 N 条")
    parser.add_argument("--offset", type=int, default=0,
                        help="跳过前 N 条（配合 --limit 使用）")
    parser.add_argument("--output", type=str, default="results/attacks_v1.json",
                        help="输出 JSON 文件路径")
    parser.add_argument("--variants", type=int, default=VARIANTS_PER_ITEM,
                        help="每条样本生成几个变体")
    parser.add_argument("--dataset", type=str, default=DATASET_PATH,
                        help="数据集路径")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)

    if args.items:
        item_ids = [x.strip() for x in args.items.split(",")]
    elif args.limit:
        all_ids = list(dataset.keys())
        item_ids = all_ids[args.offset:args.offset + args.limit]
    else:
        print("请指定 --items 或 --limit")
        return

    run_generation(dataset, item_ids, args.output, n_variants=args.variants)


if __name__ == "__main__":
    main()
