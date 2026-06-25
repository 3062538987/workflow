import json
import requests
import time
import os
import shutil
import csv
import re
from datetime import datetime
from PIL import Image
import torch
import clip
import optuna
import pandas as pd

# ===== 配置 =====
API_URL = "http://127.0.0.1:8188/prompt"
EXCEL_FILE = "提示词.xlsx"
SHEET_NAME = "Prompt生成表--卖点 原"
OUTPUT_DIR = "lora_tuning_results"
BEST_LORA_PARAMS_FILE = "best_lora_params.json"
HISTORY_FILE = "lora_optimization_history.csv"

# 节点ID配置
POSITIVE_NODE_ID = "9"
NEGATIVE_NODE_ID = "10"
KSAMPLER_NODE_ID = "4"
LORA_NODE_ID = "12"
SAVE_IMAGE_NODE_ID = "16"

# 优化参数范围
LORA_MODEL_RANGE = (0.1, 1.2)
LORA_CLIP_RANGE = (0.1, 1.2)
STEPS_RANGE = (20, 35)
CFG_RANGE = (6.0, 10.0)

# 停止条件
SIMILARITY_THRESHOLD = 0.75
MAX_TRIALS_PER_STYLE = 30

# ===== 1. 加载CLIP（可选）=====
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🔧 使用设备: {device}")

clip_model = None
preprocess = None
try:
    clip_model, preprocess = clip.load("ViT-B/32", device=device)
    print("✅ CLIP模型加载成功")
except Exception as e:
    print(f"⚠️ CLIP加载失败: {e}")
    print("   将使用基于参数范围的优化策略，不进行相似度评估")

# ===== 2. 工具函数 =====
def calculate_clip_similarity(img1_path, img2_path):
    if clip_model is None:
        return 0.0
    try:
        img1 = preprocess(Image.open(img1_path)).unsqueeze(0).to(device)
        img2 = preprocess(Image.open(img2_path)).unsqueeze(0).to(device)
        with torch.no_grad():
            emb1 = clip_model.encode_image(img1)
            emb2 = clip_model.encode_image(img2)
            emb1 = emb1 / emb1.norm(dim=1, keepdim=True)
            emb2 = emb2 / emb2.norm(dim=1, keepdim=True)
            similarity = (emb1 @ emb2.T).item()
        return similarity
    except Exception as e:
        print(f"⚠️ 相似度计算失败: {e}")
        return 0.0

def extract_style_from_ref(ref_image_path):
    if not os.path.exists(ref_image_path) or clip_model is None:
        return "vintage, retro"
    style_keywords = [
        "vintage", "retro", "aged paper", "warm tones",
        "watercolor", "illustration", "hand-drawn", "textured",
        "folk art", "rustic", "americana", "cartoon",
        "cute", "stylized", "flat", "engraved", "etched", "ink"
    ]
    scores = []
    try:
        ref_img = preprocess(Image.open(ref_image_path)).unsqueeze(0).to(device)
        with torch.no_grad():
            ref_emb = clip_model.encode_image(ref_img)
            ref_emb = ref_emb / ref_emb.norm(dim=1, keepdim=True)
            for kw in style_keywords:
                text = clip.tokenize([f"a {kw} style illustration"]).to(device)
                with torch.no_grad():
                    text_emb = clip_model.encode_text(text)
                    text_emb = text_emb / text_emb.norm(dim=1, keepdim=True)
                    score = (ref_emb @ text_emb.T).item()
                    scores.append((kw, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return ", ".join([s[0] for s in scores[:4]])
    except:
        return "vintage, retro, warm"

def generate_image(workflow_file, prompt_text, negative_text, params, trial_num, style_name):
    try:
        with open(workflow_file, 'r', encoding='utf-8') as f:
            workflow = json.load(f)
    except:
        print(f"❌ 找不到工作流文件: {workflow_file}")
        return None
    
    workflow[KSAMPLER_NODE_ID]['inputs']['steps'] = params['steps']
    workflow[KSAMPLER_NODE_ID]['inputs']['cfg'] = params['cfg']
    workflow[KSAMPLER_NODE_ID]['inputs']['seed'] = params['seed']
    
    if LORA_NODE_ID in workflow:
        workflow[LORA_NODE_ID]['inputs']['strength_model'] = params['lora_model']
        workflow[LORA_NODE_ID]['inputs']['strength_clip'] = params['lora_clip']
    
    workflow[POSITIVE_NODE_ID]['inputs']['text'] = prompt_text
    workflow[NEGATIVE_NODE_ID]['inputs']['text'] = negative_text
    
    prefix = f"{style_name}_trial_{trial_num:03d}_s{params['steps']}_c{int(params['cfg']*10)}"
    workflow[SAVE_IMAGE_NODE_ID]['inputs']['filename_prefix'] = prefix
    
    payload = {"prompt": workflow}
    try:
        response = requests.post(API_URL, json=payload, timeout=180)
        if response.status_code != 200:
            print(f"❌ 提交失败: {response.status_code}")
            return None
        time.sleep(10)
        output_dir = "../ComfyUI/output"
        if not os.path.exists(output_dir):
            output_dir = "D:/ComfyUI-aki-v3.7/ComfyUI-aki-v3.7/ComfyUI/output"
        files = [f for f in os.listdir(output_dir) if f.startswith(prefix)]
        if files:
            files.sort(key=lambda x: os.path.getmtime(os.path.join(output_dir, x)), reverse=True)
            return os.path.join(output_dir, files[0])
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        return None

def save_best_params(style_name, params, score):
    params_with_score = params.copy()
    params_with_score['score'] = score
    if os.path.exists(BEST_LORA_PARAMS_FILE):
        with open(BEST_LORA_PARAMS_FILE, 'r', encoding='utf-8') as f:
            all_params = json.load(f)
    else:
        all_params = {}
    all_params[style_name] = params_with_score
    with open(BEST_LORA_PARAMS_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_params, f, indent=2, ensure_ascii=False)

def log_history(style_name, trial_num, params, similarity, image_path):
    file_exists = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['style', 'trial', 'lora_model', 'lora_clip', 'steps', 'cfg', 'seed', 'similarity', 'image_path', 'timestamp'])
        writer.writerow([
            style_name, trial_num,
            params['lora_model'], params['lora_clip'],
            params['steps'], params['cfg'], params['seed'],
            similarity, image_path,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])

# ===== 3. 优化单个风格 =====
def optimize_style(style_name, style_cn, workflow_file, ref_image_path, prompt_text, negative_text):
    print(f"\n{'='*70}")
    print(f"🎯 优化风格: {style_cn} ({style_name})")
    print(f"📸 参考图: {ref_image_path}")
    print(f"📝 提示词: {prompt_text[:60]}...")
    print('='*70)
    
    os.makedirs(f"{OUTPUT_DIR}/{style_name}", exist_ok=True)
    best_score = 0
    best_params = None
    
    def objective(trial):
        nonlocal best_score, best_params
        lora_model = trial.suggest_float('lora_model', LORA_MODEL_RANGE[0], LORA_MODEL_RANGE[1], step=0.05)
        lora_clip = trial.suggest_float('lora_clip', LORA_CLIP_RANGE[0], LORA_CLIP_RANGE[1], step=0.05)
        steps = trial.suggest_int('steps', STEPS_RANGE[0], STEPS_RANGE[1], step=5)
        cfg = trial.suggest_float('cfg', CFG_RANGE[0], CFG_RANGE[1], step=0.5)
        seed = trial.suggest_int('seed', 1, 99999999)
        
        params = {
            'lora_model': lora_model,
            'lora_clip': lora_clip,
            'steps': steps,
            'cfg': cfg,
            'seed': seed
        }
        
        trial_num = trial.number + 1
        print(f"\n🔄 试验 {trial_num}/{MAX_TRIALS_PER_STYLE}")
        print(f"   🔧 LoRA: model={lora_model:.2f}, clip={lora_clip:.2f}, steps={steps}, cfg={cfg:.1f}")
        
        generated_path = generate_image(workflow_file, prompt_text, negative_text, params, trial_num, style_name)
        if generated_path is None:
            return 0.0
        
        result_path = f"{OUTPUT_DIR}/{style_name}/trial_{trial_num:03d}_m{int(lora_model*100)}_c{int(lora_clip*100)}.png"
        shutil.copy(generated_path, result_path)
        similarity = calculate_clip_similarity(result_path, ref_image_path)
        
        if clip_model is None:
            score = params['lora_model'] * 0.4 + params['lora_clip'] * 0.4 + (params['steps'] / 35) * 0.2
            print(f"   📊 综合评分: {score:.4f} (LoRA权重 + 步数)")
        else:
            score = similarity
            print(f"   📊 相似度: {similarity:.4f}")
        
        log_history(style_name, trial_num, params, score, result_path)
        
        if score > best_score:
            best_score = score
            best_params = params.copy()
            print(f"   🏆 新的最佳! 评分: {best_score:.4f}")
            shutil.copy(result_path, f"{OUTPUT_DIR}/{style_name}/best.png")
            save_best_params(style_name, best_params, best_score)
        
        print(f"   📈 当前最佳: {best_score:.4f}")
        if clip_model is not None and similarity >= SIMILARITY_THRESHOLD:
            print(f"\n🎉 达到目标! 停止优化")
            trial.study.stop()
        return score
    
    study = optuna.create_study(direction='maximize', study_name=f'{style_name}_lora_opt', storage=None)
    study.optimize(objective, n_trials=MAX_TRIALS_PER_STYLE, show_progress_bar=True)
    
    print(f"\n🏆 {style_cn} 优化完成! 最佳相似度: {study.best_value:.4f}")
    print(f"   最佳参数: steps={study.best_params['steps']}, cfg={study.best_params['cfg']:.1f}, lora_model={study.best_params['lora_model']:.2f}, lora_clip={study.best_params['lora_clip']:.2f}")
    return study

# ===== 4. 主函数 - 优化所有风格 =====
def main():
    print("="*70)
    print("  ComfyUI 全风格 LoRA 参数自动化调优系统")
    print("  将优化所有工作流的 strength_model, strength_clip, steps, cfg")
    print("="*70)
    
    # 读取Excel
    df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
    
    # 定义所有风格（确保与Excel中的"风格"列匹配）
    style_configs = {
        "vintage": {
            "cn": "复古风格",
            "workflow": "workflow_复古_Funtik.json",
            "ref": "reference_images/vintage.png",
            "excel_style": "复古风格"
        },
        "watercolor": {
            "cn": "手绘水彩",
            "workflow": "workflow_水彩_SoftWatercolor.json",
            "ref": "reference_images/watercolor.png",
            "excel_style": "手绘水彩风格"
        },
        "minimalist": {
            "cn": "极简风格",
            "workflow": "workflow_极简_MinimalistLine.json",
            "ref": "reference_images/minimalist.png",
            "excel_style": "极简风格"
        },
        "cartoon": {
            "cn": "卡通手绘",
            "workflow": "workflow_卡通_CoolKids.json",
            "ref": "reference_images/cartoon.png",
            "excel_style": "卡通手绘风格"
        },
        "engraved": {
            "cn": "版画风格",
            "workflow": "workflow_版画_Pastoral.json",
            "ref": "reference_images/engraved.png",
            "excel_style": "版画风格"
        }
    }
    
    # 检查参考图（可选）
    missing_ref = []
    for style, config in style_configs.items():
        if not os.path.exists(config['ref']):
            missing_ref.append(config['cn'])
    if missing_ref:
        print(f"⚠️ 以下风格的参考图不存在: {', '.join(missing_ref)}")
        print("   将使用默认风格关键词进行优化")
    
    # 确认
    print("\n📋 将要优化的风格:")
    for style, config in style_configs.items():
        print(f"   ✅ {config['cn']} ({style})")
    print(f"\n⏱️ 每个风格最多 {MAX_TRIALS_PER_STYLE} 次试验，预计总时间较长，请耐心等待...\n")
    
    # 循环优化所有风格
    results = {}
    for style_name, config in style_configs.items():
        # 从Excel获取对应风格的提示词
        style_rows = df[df['风格'] == config['excel_style']]
        if style_rows.empty:
            print(f"\n⏭️ 跳过 {config['cn']}: Excel 中无对应数据")
            continue
        
        row = style_rows.iloc[0]
        prompt_text = row['参考提示词']
        # 清理提示词
        prompt_text = re.sub(r' --q\s+[\d.]+', '', prompt_text)
        prompt_text = re.sub(r' --v\s+[\d.]+', '', prompt_text)
        prompt_text = re.sub(r' --ar\s+[\d:]+', '', prompt_text)
        prompt_text = prompt_text.strip()
        # 提取风格关键词
        style_keywords = extract_style_from_ref(config['ref'])
        prompt_text = f"{prompt_text}, {style_keywords}"
        
        # 负面提示词
        prohibited = row.get('禁止项', '')
        BASE_NEGATIVE = "worst quality, lowres, ugly, deformed, bad anatomy, blurry, photo, photorealistic, 3d, render"
        negative_text = f"{BASE_NEGATIVE}, {prohibited}" if prohibited else BASE_NEGATIVE
        
        # 执行优化
        study = optimize_style(
            style_name=style_name,
            style_cn=config['cn'],
            workflow_file=config['workflow'],
            ref_image_path=config['ref'],
            prompt_text=prompt_text,
            negative_text=negative_text
        )
        
        results[style_name] = {
            'best_score': study.best_value,
            'best_params': study.best_params
        }
        
        # 每完成一个风格，保存一次汇总
        with open(BEST_LORA_PARAMS_FILE, 'r', encoding='utf-8') as f:
            all_params = json.load(f)
        print(f"✅ {config['cn']} 完成，当前已保存最佳参数到 {BEST_LORA_PARAMS_FILE}")
    
    # 最终汇总
    print("\n" + "="*70)
    print("🎉 所有风格优化完成!")
    print("="*70)
    print("\n📊 汇总结果:")
    for style, result in results.items():
        params = result['best_params']
        print(f"   {style}:")
        print(f"      steps: {params['steps']}")
        print(f"      cfg: {params['cfg']:.1f}")
        print(f"      lora_model: {params['lora_model']:.2f}")
        print(f"      lora_clip: {params['lora_clip']:.2f}")
        print(f"      相似度: {result['best_score']:.4f}")
        print()
    
    print(f"📁 所有结果保存在:")
    print(f"   - 最佳参数: {BEST_LORA_PARAMS_FILE}")
    print(f"   - 历史记录: {HISTORY_FILE}")
    print(f"   - 生成图片: {OUTPUT_DIR}/")

if __name__ == "__main__":
    main()