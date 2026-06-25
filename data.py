import pandas as pd
import re

# 1. 读取 Excel（请确认文件名和 sheet 名是否一致）
df = pd.read_excel('提示词.xlsx', sheet_name='Prompt生成表--卖点 原')

# 2. 提取“参考提示词”列，并删除空行
raw_prompts = df['参考提示词'].dropna().tolist()

clean_prompts = []

for p in raw_prompts:
    # 3. 移除 Midjourney 参数（--q, --v, --ar）
    p = re.sub(r' --q\s+[\d.]+', '', p)      # 去掉 --q 2
    p = re.sub(r' --v\s+[\d.]+', '', p)      # 去掉 --v 6.1
    p = re.sub(r' --ar\s+[\d:]+', '', p)     # 去掉 --ar 2:1
    
    # 4. 去除首尾空格
    p = p.strip()
    
    # 5. 【关键】追加家纺/插画风格关键词，强制“非照片感”
    #    如果提示词里已经包含 illustration 或 hand-drawn，就不再重复加
    if 'illustration' not in p.lower() and 'hand-drawn' not in p.lower():
        p = p + ', illustration style, hand-drawn texture, fabric print design, non-photorealistic'
    
    clean_prompts.append(p)

# 6. 输出为 prompts.txt，每行一条
with open('prompts.txt', 'w', encoding='utf-8') as f:
    for p in clean_prompts:
        f.write(p + '\n')

print(f"✅ 处理完成！共生成 {len(clean_prompts)} 条提示词，已保存到 prompts.txt")
print("前3条预览（如有）：")
for i, p in enumerate(clean_prompts[:3]):
    print(f"{i+1}. {p[:150]}...")