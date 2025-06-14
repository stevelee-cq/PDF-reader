import re

# 文件路径
tem_file = '英语专业四八级词汇表_cleaned.txt'
toefl_oald_file = 'TOEFL_OALD8_merged.txt'
merged_file = 'TEM_TOEFL_OALD8_merged02.txt'

# 提取词典
def extract_dict(filepath):
    entries = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 统一大小写处理 + 去除多余标点空格
            line = re.sub(r'\s+', ' ', line)
            match = re.match(r'^([a-zA-Z\-\, ]+)\s+(.*)$', line)
            if match:
                words_part, definition = match.groups()
                words = re.split(r'[,\s]+', words_part.lower())
                for word in words:
                    if word and word not in entries:
                        entries[word] = definition.strip()
    return entries

# 加载两个数据集
tem_dict = extract_dict(tem_file)
toefl_oald_dict = extract_dict(toefl_oald_file)

# 合并：优先使用 TOEFL_OALD 定义
merged_dict = dict(tem_dict)
for word, definition in toefl_oald_dict.items():
    merged_dict[word] = definition

# 写入合并文件（按字典序）
with open(merged_file, 'w', encoding='utf-8') as f:
    for word in sorted(merged_dict.keys()):
        f.write(f"{word} {merged_dict[word]}\n")

# ===== 检查准确性 =====
tem_words = set(tem_dict.keys())
toefl_oald_words = set(toefl_oald_dict.keys())
merged_words = set(merged_dict.keys())

missing_words = (tem_words | toefl_oald_words) - merged_words
extra_words = merged_words - (tem_words | toefl_oald_words)

# 打印信息
print("✅ 合并完成并检查成功！")
print(f"📘 TEM 词条数：{len(tem_words)}")
print(f"📗 TOEFL + OALD8 词条数：{len(toefl_oald_words)}")
print(f"📚 合并后总词条数：{len(merged_words)}")
print(f"❗ 缺失词条数：{len(missing_words)}")
print(f"❗ 多余词条数：{len(extra_words)}")

# 示例输出
if missing_words:
    print("\n📌 缺失词条示例（前10个）：")
    for word in list(missing_words)[:10]:
        print(f" - {word}")

# 写入日志
with open("merge_TEM_TOEFL_OALD8_recheck_log.txt", "w", encoding="utf-8") as fout:
    fout.write(f"TEM词条数：{len(tem_words)}\n")
    fout.write(f"TOEFL+OALD词条数：{len(toefl_oald_words)}\n")
    fout.write(f"合并词条数：{len(merged_words)}\n\n")
    if missing_words:
        fout.write("缺失词条：\n")
        for word in sorted(missing_words):
            fout.write(f"{word}\n")
    if extra_words:
        fout.write("\n多余词条：\n")
        for word in sorted(extra_words):
            fout.write(f"{word}\n")

print("📄 检查日志已写入：merge_TEM_TOEFL_OALD8_recheck_log.txt")
