import csv
import os
import re


def rename_fasta_strict(csv_file, fasta_file, output_file):
    # 1. 读取 CSV 文件并建立映射
    id_mapping = {}

    print(f"正在读取 CSV: {csv_file}")
    try:
        # 尝试使用 utf-8 读取，如果 CSV 是 Excel 格式可能需要 gbk
        encoding = 'utf-8-sig'
        try:
            with open(csv_file, 'r', encoding=encoding) as f:
                csv.DictReader(f)
        except UnicodeDecodeError:
            encoding = 'gbk'

        with open(csv_file, mode='r', encoding=encoding) as f:
            reader = csv.DictReader(f)
            for row in reader:
                phage_id = row['Phage'].strip()
                species = row['Species'].strip()
                result = row['Result'].strip()

                # --- 构建新名字 ---
                # 原始拼接
                raw_name = f"{species}_{result}_{phage_id}"

                # --- 核心修复步骤 ---
                # 1. 将所有空白字符（空格、制表符等）替换为下划线
                safe_name = re.sub(r'\s+', '_', raw_name)

                # 2. 将所有非字母、非数字、非连字符(-)的字符替换为下划线
                # 这样可以去除括号 ()、冒号 :、逗号 , 等可能干扰软件的符号
                safe_name = re.sub(r'[^\w\-]', '_', safe_name)

                # 3. 把连续的下划线合并成一个 (例如 Clostridium__phage 变成 Clostridium_phage)
                safe_name = re.sub(r'_+', '_', safe_name)

                id_mapping[phage_id] = safe_name

    except Exception as e:
        print(f"读取 CSV 失败: {e}")
        return

    # 2. 处理 FASTA
    print(f"正在转换 FASTA，输出到: {output_file}")
    count = 0
    try:
        with open(fasta_file, 'r', encoding='utf-8') as infile, \
                open(output_file, 'w', encoding='utf-8') as outfile:

            for line in infile:
                if line.startswith('>'):
                    # 提取 ID (去掉 > 和换行，取第一个空格前的内容)
                    original_id = line[1:].strip().split()[0]

                    if original_id in id_mapping:
                        # 写入新的、清洗过的名字
                        outfile.write(f">{id_mapping[original_id]}\n")
                        count += 1
                    else:
                        # 如果没有在 CSV 里找到，为了安全，也把原标题的空格换掉
                        safe_header = re.sub(r'\s+', '_', line[1:].strip())
                        outfile.write(f">{safe_header}\n")
                else:
                    outfile.write(line)

        print(f"完成！已重命名 {count} 条序列。")
        print("所有空格和特殊符号都已替换为下划线。")

    except Exception as e:
        print(f"处理 FASTA 失败: {e}")


# --- 执行配置 ---
csv_path = '副本裂解酶比对.csv'
fasta_path = 'hit_sequences.fasta'
output_path = 'renamed_sequences_fixed.fasta'

if __name__ == '__main__':
    if os.path.exists(csv_path) and os.path.exists(fasta_path):
        rename_fasta_strict(csv_path, fasta_path, output_path)
    else:
        print("错误：未在当前目录下找到输入文件。")