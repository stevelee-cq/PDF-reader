import tkinter as tk
from tkinter import filedialog, messagebox
import fitz  # PyMuPDF
import os
import spacy
import threading
import time
from googletrans import Translator

# 初始化
nlp = spacy.load("en_core_web_sm")
translator = Translator()

# 加载词典
def load_vocab(filepath):
    vocab = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                parts = line.strip().split(" ", 1)
                word = parts[0].lower()
                vocab[word] = line.strip()
    return vocab

# 提取PDF正文
def extract_text_before_references(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        page_text = page.get_text()
        if "references" in page_text.lower():
            text += page_text.lower().split("references")[0]
            break
        text += page_text
    return text

# 提取合法单词（词形还原 + 英语词典交集）
def extract_valid_words(text, valid_words_set):
    doc = nlp(text)
    lemmatized = set()
    for token in doc:
        if token.is_alpha:
            lemma = token.lemma_.lower()
            if lemma in valid_words_set:
                lemmatized.add(lemma)
    return lemmatized

# 写文件函数们
def save_words(words, vocab, path):
    with open(path, "w", encoding="utf-8") as f:
        for w in sorted(words):
            f.write(vocab[w] + "\n")

def save_unknown(words, path):
    with open(path, "w", encoding="utf-8") as f:
        for w in sorted(words):
            f.write(w + "\n")

def save_translated_unknown(words, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, w in enumerate(sorted(words)):
            try:
                result = translator.translate(w, src='en', dest='zh-cn')
                f.write(f"{w} -> {result.text}\n")
            except Exception as e:
                f.write(f"{w} -> 翻译失败\n")
            if (i + 1) % 10 == 0:
                time.sleep(1)  # 限制翻译频率，防止 API 拒绝服务

def save_all_valid(words, path):
    with open(path, "w", encoding="utf-8") as f:
        for w in sorted(words):
            f.write(w + "\n")

# 主处理逻辑
def process(pdf_path, output_dir):
    try:
        with open("words_alpha.txt", "r", encoding="utf-8") as f:
            valid_words = set(w.strip().lower() for w in f if w.strip())
        cet4_6 = load_vocab("CET4_6_merged.txt")
        gre_toefl = load_vocab("GRE_TOEFL_OALD8_merged.txt")

        raw_text = extract_text_before_references(pdf_path)
        valid_tokens = extract_valid_words(raw_text, valid_words)

        familiar, unfamiliar, unknown = set(), set(), set()

        for word in valid_tokens:
            if word in cet4_6:
                familiar.add(word)
            elif word in gre_toefl:
                unfamiliar.add(word)
            else:
                unknown.add(word)

        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        save_words(familiar, cet4_6, os.path.join(output_dir, f"{base_name}_熟悉词.txt"))
        save_words(unfamiliar, gre_toefl, os.path.join(output_dir, f"{base_name}_待学词.txt"))
        save_unknown(unknown, os.path.join(output_dir, f"{base_name}_生词.txt"))
        save_translated_unknown(unknown, os.path.join(output_dir, f"{base_name}_生词翻译.txt"))
        save_all_valid(valid_tokens, os.path.join(output_dir, f"{base_name}_有效词.txt"))

        messagebox.showinfo("✅ 提取完成", f"""✅ 提取完成：
熟悉词数：{len(familiar)}
待学习词数：{len(unfamiliar)}
生词数：{len(unknown)}
有效词总数：{len(valid_tokens)}""")

    except Exception as e:
        messagebox.showerror("❌ 出错", f"处理出错：{e}")

# GUI线程封装
def threaded_process(pdf_path, output_dir):
    t = threading.Thread(target=process, args=(pdf_path, output_dir))
    t.start()

# GUI界面
def run_gui():
    def select_pdf():
        path = filedialog.askopenfilename(title="选择PDF文件", filetypes=[("PDF files", "*.pdf")])
        if path:
            pdf_path_var.set(path)

    def select_output_dir():
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            output_dir_var.set(path)

    def start():
        pdf_path = pdf_path_var.get()
        output_dir = output_dir_var.get()
        if not pdf_path or not output_dir:
            messagebox.showerror("错误", "请先选择PDF文件和输出路径！")
            return
        threaded_process(pdf_path, output_dir)

    root = tk.Tk()
    root.title("PDF英文单词分类提取器")
    root.geometry("600x220")

    pdf_path_var = tk.StringVar()
    output_dir_var = tk.StringVar()

    tk.Label(root, text="PDF 文件路径：").pack()
    tk.Entry(root, textvariable=pdf_path_var, width=80).pack()
    tk.Button(root, text="选择PDF文件", command=select_pdf).pack()

    tk.Label(root, text="输出目录：").pack()
    tk.Entry(root, textvariable=output_dir_var, width=80).pack()
    tk.Button(root, text="选择输出目录", command=select_output_dir).pack()

    tk.Button(root, text="开始提取", command=start, bg="lightblue").pack(pady=10)

    root.mainloop()

if __name__ == "__main__":
    run_gui()
