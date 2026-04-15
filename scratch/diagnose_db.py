import sqlite3
import json

def diagnose():
    db_path = 'database/strain.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print("--- 数据库一致性诊断报告 ---")

    # 1. 获取样本数据
    c.execute('SELECT id, name, freezer_id, box_id, position FROM records')
    records = c.fetchall()
    print(f"待处理样本总数: {len(records)}")

    # 2. 获取冰箱数据
    c.execute('SELECT id, name, structure FROM freezers')
    freezer_rows = c.fetchall()
    print(f"冰箱总数: {len(freezer_rows)}")

    # 3. 建立盒子索引 Map (模拟前端 boxMap)
    box_map = {}
    for f_id, f_name, structure_json in freezer_rows:
        try:
            shelves = json.loads(structure_json)
            # 深度遍历
            for s in shelves:
                for cab in s.get('cabinets', []):
                    for dra in cab.get('drawers', []):
                        for box in dra.get('boxes', []):
                            key = f"{f_id}|{box['id']}"
                            box_map[key] = {
                                'box': box,
                                'freezer_name': f_name
                            }
        except Exception as e:
            print(f"解析冰箱 {f_id} 结构失败: {e}")

    print(f"系统内置盒子总索引数: {len(box_map)}")

    # 4. 执行模拟匹配
    match_count = 0
    fail_reasons = {
        'box_not_found': 0,
        'position_not_found': 0
    }

    for rid, rname, fid, bid, pos_label in records:
        ckey = f"{fid}|{bid}"
        if ckey in box_map:
            box_info = box_map[ckey]
            box = box_info['box']
            # 查找位置
            positions = box.get('positions', [])
            found_pos = False
            for p in positions:
                if str(p.get('label', '')).upper() == str(pos_label).upper():
                    found_pos = True
                    break
            
            if found_pos:
                match_count += 1
            else:
                fail_reasons['position_not_found'] += 1
                if fail_reasons['position_not_found'] < 3:
                    print(f"FAIL: 样本 {rname} 的格位 {pos_label} 在盒子 {bid} 中不存在")
        else:
            fail_reasons['box_not_found'] += 1
            if fail_reasons['box_not_found'] < 3:
                print(f"FAIL: 找不到复合索引键 {ckey} (样本: {rname}, 冰箱: {fid}, 盒子: {bid})")

    print("\n--- 诊断结果 ---")
    print(f"全库匹配成功率: {match_count}/{len(records)} ({match_count/len(records)*100:.1f}%)")
    print(f"失败明细: {fail_reasons}")
    
    if match_count == len(records):
        print("\n[结论] 数据结构在逻辑上是完全契合的。")
        print("[结论] 问题极大概率在于前端 Vue 响应式更新或保存到数据库时的异步覆盖。")
    else:
        print("\n[结论] 数据结构本身存在匹配断裂点。")

    conn.close()

if __name__ == "__main__":
    diagnose()
