"""
清理攻击样本：每个ID只保留一个最佳变体。
策略：优先选 R4 文本保留度最高的变体（越接近原句越容易通过核验）。
"""
import json
import sys
sys.path.insert(0, 'validate')
from validate import calculate_levenshtein_distance


def pick_best_variant(attacks_file, dataset_file, output_file):
    with open(attacks_file, 'r', encoding='utf-8') as f:
        attacks = json.load(f)
    with open(dataset_file, 'r', encoding='utf-8') as f:
        dataset = {item['id']: item for item in json.load(f)}

    # 按 ID 分组
    by_id = {}
    for item in attacks:
        item_id = item['id']
        if item_id not in by_id:
            by_id[item_id] = []
        by_id[item_id].append(item)

    cleaned = []
    for item_id, variants in by_id.items():
        orig_text = dataset[item_id]['text_original']
        
        # 计算每个变体的 R4 相似度
        best_variant = None
        best_similarity = -1
        
        for v in variants:
            a, b = orig_text, v['text_attack']
            dist = calculate_levenshtein_distance(a, b)
            similarity = 1 - dist / max(len(a), len(b))
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_variant = v
        
        best_variant['_r4_similarity'] = round(best_similarity, 4)
        cleaned.append(best_variant)
        print(f"[{item_id}] 从 {len(variants)} 个变体中选取最佳: "
              f"R4={best_similarity:.4f}, strategy={best_variant['strategy'][:40]}...")

    # 去掉临时字段
    for item in cleaned:
        item.pop('_r4_similarity', None)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    
    print(f"\n清理完成: {len(cleaned)} 条 → {output_file}")


if __name__ == '__main__':
    pick_best_variant('attacks_v1.json', 'dataset/fiia_0427.json', 'attacks_v1_clean.json')
