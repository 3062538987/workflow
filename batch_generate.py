import json
import requests
import time
import os
import re
import pandas as pd
from datetime import datetime

API_URL = "http://127.0.0.1:8188/prompt"
EXCEL_FILE = "提示词.xlsx"
SHEET_NAME = "Prompt生成表--卖点 原"
DELAY_BETWEEN_REQUESTS = 3
LOG_FILE = f"batch_generate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

def log_print(message):
    """同时打印到控制台和日志文件"""
    print(message)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(message + '\n')

BEST_PARAMS_FILE = "best_lora_params.json"

def load_best_params():
    """从 JSON 文件加载最佳参数，如果不存在则使用默认值"""
    default_params = {
        "vintage": {"steps": 25, "cfg": 8.0, "lora_weight": 0.7},
        "watercolor": {"steps": 25, "cfg": 7.0, "lora_weight": 0.8},
        "minimalist": {"steps": 20, "cfg": 9.0, "lora_weight": 0.6},
        "cartoon": {"steps": 25, "cfg": 8.0, "lora_weight": 0.7},
        "engraved": {"steps": 30, "cfg": 9.0, "lora_weight": 0.8},
    }
    
    if not os.path.exists(BEST_PARAMS_FILE):
        log_print(f"⚠️ 未找到 {BEST_PARAMS_FILE}，使用默认参数")
        return default_params
    
    try:
        with open(BEST_PARAMS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for style in data:
            if 'lora_model' in data[style]:
                data[style]['lora_weight'] = data[style]['lora_model']
            elif 'lora_weight' not in data[style]:
                data[style]['lora_weight'] = 0.7
        
        for style in default_params:
            if style not in data:
                data[style] = default_params[style]
        
        log_print("✅ 已加载最佳参数:")
        for style, params in data.items():
            log_print(f"   {style}: steps={params.get('steps', 25)}, cfg={params.get('cfg', 8.0)}, lora={params.get('lora_weight', 0.7)}")
        return data
    except Exception as e:
        log_print(f"⚠️ 加载最佳参数失败: {e}，使用默认参数")
        return default_params

BEST_PARAMS = load_best_params()

POSITIVE_NODE_ID = "9"
NEGATIVE_NODE_ID = "10"
SAVE_IMAGE_NODE_ID = "16"

STYLE_WORKFLOW_MAP = {
    "vintage": "workflow_复古_Funtik.json",
    "watercolor": "workflow_水彩_SoftWatercolor.json",
    "minimalist": "workflow_极简_MinimalistLine.json",
    "cartoon": "workflow_卡通_CoolKids.json",
    "engraved": "workflow_版画_Pastoral.json",
    "vector": "workflow_极简_MinimalistLine.json",
}

STYLE_KEYWORDS = [
    ("vintage", ["vintage", "retro", "aged paper", "rustic", "americana", "folk art"]),
    ("watercolor", ["gouache", "watercolor", "canvas texture", "brushstrokes", "impasto"]),
    ("minimalist", ["minimalist", "fine line", "geometric", "flat design", "clean lines"]),
    ("cartoon", ["cartoon", "hand-drawn", "cute", "ink texture", "stylized", "handcrafted"]),
    ("engraved", ["engraved", "etched", "ink sketch", "sepia", "retro engraved"]),
    ("vector", ["vector", "flat design", "solid color", "graphic design"]),
]

BASE_NEGATIVE = "worst quality, lowres, ugly, deformed, bad anatomy, blurry, photo, photorealistic, 3d, render"


def clean_filename(label):
    """清理非法字符，使字符串可用作文件名"""
    if not label or not str(label).strip():
        return "untitled"
    label = str(label).strip()
    label = re.sub(r'[\\/*?:"<>|]', '_', label)
    label = re.sub(r'\s+', '_', label)
    return label


def detect_style(prompt_text):
    """根据提示词内容检测风格"""
    prompt_lower = prompt_text.lower()
    for style, keywords in STYLE_KEYWORDS:
        for kw in keywords:
            if kw in prompt_lower:
                return style
    return "vector"


def get_workflow_file(prompt_text):
    """根据提示词获取对应的工作流文件"""
    style = detect_style(prompt_text)
    return STYLE_WORKFLOW_MAP.get(style, "workflow_minimalist.json")


def submit_prompt(workflow_file, prompt_text, negative_text, label, idx, total, style, example_image=""):
    """提交一个提示词到 ComfyUI"""
    try:
        with open(workflow_file, 'r', encoding='utf-8') as f:
            workflow = json.load(f)
    except FileNotFoundError:
        log_print(f"❌ 找不到工作流文件: {workflow_file}")
        return False

    workflow[POSITIVE_NODE_ID]['inputs']['text'] = prompt_text
    workflow[NEGATIVE_NODE_ID]['inputs']['text'] = negative_text

    if style in BEST_PARAMS:
        params = BEST_PARAMS[style]
        if "4" in workflow:
            workflow["4"]['inputs']['steps'] = params.get('steps', 25)
            workflow["4"]['inputs']['cfg'] = params.get('cfg', 8.0)
        if "12" in workflow:
            lora_w = params.get('lora_weight', 0.7)
            workflow["12"]['inputs']['strength_model'] = lora_w
            workflow["12"]['inputs']['strength_clip'] = lora_w
        log_print(f"   ⚙️  参数: steps={params.get('steps', 25)}, cfg={params.get('cfg', 8.0)}, lora={params.get('lora_weight', 0.7)}")

    if SAVE_IMAGE_NODE_ID in workflow:
        safe_label = clean_filename(label)
        workflow[SAVE_IMAGE_NODE_ID]['inputs']['filename_prefix'] = safe_label
        log_print(f"   📁 文件名: {safe_label}")

    payload = {"prompt": workflow}
    try:
        response = requests.post(API_URL, json=payload, timeout=120)
        if response.status_code == 200:
            log_print(f"✅ [{idx}/{total}] 成功提交: {label}")
            return True
        else:
            log_print(f"❌ [{idx}/{total}] 提交失败 (HTTP {response.status_code})")
            return False
    except Exception as e:
        log_print(f"❌ [{idx}/{total}] 请求异常: {e}")
        return False


def main():
    log_print("=" * 60)
    log_print("  ComfyUI 批量生成器")
    log_print("=" * 60)
    log_print(f"📝 日志文件: {LOG_FILE}")
    log_print("")

    if not os.path.exists(EXCEL_FILE):
        log_print(f"❌ 找不到 Excel 文件: {EXCEL_FILE}")
        return

    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
    except Exception as e:
        log_print(f"❌ 读取 Excel 失败: {e}")
        return

    if df.empty:
        log_print("❌ Excel 中没有数据")
        return

    data = []
    for idx, row in df.iterrows():
        prompt_text = str(row.get('参考提示词', '')).strip() if pd.notna(row.get('参考提示词')) else ''
        
        if not prompt_text:
            continue

        label_raw = row.get('卖点变量标签', '')
        if pd.notna(label_raw) and str(label_raw).strip():
            label = str(label_raw).strip()
        else:
            label_parts = prompt_text.split()[:4]
            label = "-".join(label_parts)

        prohibited = str(row.get('禁止项', '')).strip() if pd.notna(row.get('禁止项')) else ''
        example_image = row.get('示例图片', '') if '示例图片' in df.columns and pd.notna(row.get('示例图片')) else ''

        data.append({
            'prompt_text': prompt_text,
            'label': label,
            'prohibited': prohibited,
            'example_image': example_image,
        })

    total = len(data)
    log_print(f"✅ 从 Excel 加载了 {total} 条数据")
    log_print("")

    if total == 0:
        log_print("❌ 没有有效的提示词数据")
        return

    style_count = {}
    for item in data:
        style = detect_style(item['prompt_text'])
        style_count[style] = style_count.get(style, 0) + 1

    log_print("📊 风格分布：")
    for style, count in style_count.items():
        log_print(f"   - {style}: {count} 条")
    log_print("")

    for idx, item in enumerate(data):
        prompt_text = item['prompt_text']
        label = item['label']
        prohibited = item['prohibited']
        example_image = item['example_image']

        if prohibited:
            negative_text = f"{BASE_NEGATIVE}, {prohibited}"
        else:
            negative_text = BASE_NEGATIVE

        workflow_file = get_workflow_file(prompt_text)
        style = detect_style(prompt_text)

        log_print(f"🔄 [{idx+1}/{total}] 风格: {style}")
        log_print(f"   🏷️  标签: {label}")
        if example_image:
            log_print(f"   🖼️  示例图片: {example_image}")
        log_print(f"   🚫 负面词: {negative_text[:80]}...")

        success = submit_prompt(workflow_file, prompt_text, negative_text, label, idx+1, total, style, example_image)
        if not success:
            log_print(f"⚠️ 第 {idx+1} 条提交失败，继续...")

        time.sleep(DELAY_BETWEEN_REQUESTS)

    log_print("\n🎉 所有提示词已提交完毕！")


if __name__ == "__main__":
    main()
