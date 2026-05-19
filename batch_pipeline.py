"""
批量攻击流水线：生成→验证→修复→评估→排序
一键完成从原始数据到最终提交的全流程。
"""

import json
import sys
import os
import subprocess
import argparse

sys.path.insert(0, 'validate')
from validate import calculate_levenshtein_distance

DATASET_PATH = "dataset/fiia_0427.json"


def load_dataset():
    with open(DATASET_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {item['id']: item for item in data}


def make_minimal_attack(item):
    """为单条样本生成最小改动攻击（仅在谓词前加'似乎'）"""
    text = item['text_original']
    predicate = item['predicate']
    # 在谓词前插入"似乎"
    idx = text.find(predicate)
    if idx > 0:
        text_attack = text[:idx] + "似乎" + text[idx:]
    else:
        text_attack = text + "（似乎如此）"
    return text_attack


def fix_r4_failure(item, dataset, attack_text):
    """
    尝试修复 R4 失败的攻击：
    1. 逐步移除结尾多余从句
    2. 如果仍失败，降级为最小改动攻击
    """
    orig = dataset[item['id']]['text_original']
    
    # 计算当前 R4
    dist = calculate_levenshtein_distance(orig, attack_text)
    similarity = 1 - dist / max(len(orig), len(attack_text))
    
    if similarity >= 0.65:
        return attack_text
    
    # 尝试从尾部逐渐删除字符，直到 R4≥0.65
    # 从逗号、句号等分隔符处截断
    delimiters = ['。', '，', '；', '、', '然而', '但', '而']
    test = attack_text
    for d in delimiters:
        while d in test:
            last_idx = test.rfind(d)
            if last_idx < len(test) * 0.6:  # 不要删太多
                break
            test = test[:last_idx]
            dist = calculate_levenshtein_distance(orig, test)
            similarity = 1 - dist / max(len(orig), len(test))
            if similarity >= 0.65:
                return test
            break  # 每个分隔符只试一次
    
    # 降级：最小改动攻击
    return make_minimal_attack(dataset[item['id']])


def run_generate(item_ids, output, limit=None, offset=0):
    """调用 generate_attacks.py"""
    cmd = ["python", "generate_attacks.py", "--output", output, "--variants", "1"]
    if item_ids:
        cmd += ["--items", item_ids]
    elif limit:
        cmd += ["--limit", str(limit), "--offset", str(offset)]
    subprocess.run(cmd, check=True)


def run_validate(submission_file):
    """调用 validate.py，返回通过的ID列表"""
    result = subprocess.run(
        ["python", "validate/validate.py", "--original", DATASET_PATH,
         "--submission", submission_file],
        capture_output=True, text=True, env={**os.environ, "HF_ENDPOINT": "https://hf-mirror.com"}
    )
    output = result.stdout + result.stderr
    
    passed = []
    for line in output.split('\n'):
        if 'OK.' in line:
            # 提取ID
            parts = line.strip().split()
            if parts:
                passed.append(parts[0].strip('[]'))
    return passed


def run_evaluate(item_ids, attacks_file, output_file):
    """调用 attack.py 评估"""
    ids_str = ",".join(item_ids)
    subprocess.run(
        ["python", "attack.py", "--mode", "eval", "--items", ids_str,
         "--attacks", attacks_file, "--output", output_file],
        check=True
    )


def merge_and_sort(result_files, output_file):
    """合并多个评估结果，按Score降序排列"""
    all_results = []
    for f in result_files:
        if os.path.exists(f):
            with open(f, 'r', encoding='utf-8') as fp:
                results = json.load(fp)
                all_results.extend(results)
    
    # 按Score降序
    all_results.sort(key=lambda x: x.get('score', 0) or 0, reverse=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    # 打印统计
    scored = [r for r in all_results if r.get('score', 0) and r['score'] > 0]
    total_score = sum(r['score'] for r in scored)
    print(f"\n总攻击样本: {len(all_results)}")
    print(f"有效攻击 (Score>0): {len(scored)}")
    print(f"总得分: {total_score:.4f}")
    print(f"Top 5:")
    for r in scored[:5]:
        print(f"  [{r['id']}] Score={r['score']:.4f} MIR_orig={r['mir_orig']:.4f} MIR_attack={r['mir_attack']:.4f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["generate", "validate", "fix", "evaluate", "merge", "all"], 
                        default="all")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--items", type=str, default=None)
    args = parser.parse_args()
    
    dataset = load_dataset()
    
    if args.step in ("generate", "all"):
        print("=" * 60)
        print("Step 1: 生成攻击样本")
        item_ids = args.items.split(",") if args.items else None
        run_generate(item_ids, "attacks_batch.json", limit=args.limit, offset=args.offset)
    
    if args.step in ("validate", "all"):
        print("=" * 60)
        print("Step 2: 核验攻击样本")
        passed_ids = run_validate("attacks_batch_submission.json")
        print(f"通过核验: {len(passed_ids)} 条")
        
        # 保存通过的ID
        with open("passed_ids.json", "w") as f:
            json.dump(passed_ids, f)
    
    if args.step in ("fix", "all"):
        print("=" * 60)
        print("Step 3: 修复失败攻击")
        with open("attacks_batch_submission.json", "r") as f:
            attacks = json.load(f)
        
        fixed = []
        fail_count = 0
        for item in attacks:
            item_id = item['id']
            attack_text = item['text_attack']
            fixed_text = fix_r4_failure(item, dataset, attack_text)
            if fixed_text != attack_text:
                fail_count += 1
            fixed.append({"id": item_id, "text_attack": fixed_text})
        
        with open("attacks_batch_fixed.json", "w", encoding='utf-8') as f:
            json.dump(fixed, f, ensure_ascii=False, indent=2)
        print(f"修复了 {fail_count} 条攻击")
        
        # 再验证一次
        passed_ids = run_validate("attacks_batch_fixed.json")
        print(f"修复后通过核验: {len(passed_ids)} 条")
        with open("passed_ids.json", "w") as f:
            json.dump(passed_ids, f)


if __name__ == "__main__":
    main()
