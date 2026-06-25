import json
import requests
import time
import os
import re
import shutil
from datetime import datetime
from PIL import Image
import torch
import clip
import optuna
import pandas as pd
import numpy as np

# ===== 配置 =====
API_URL = "http://127.0.0.1:8188/prompt"
EXCEL_FILE = "提示词.xlsx"
SHEET_NAME = "Prompt生成表--卖点 原"
OUTPUT_DIR = "tuning_results"
BEST_PARAMS_FILE = "best_params.json"
HISTORY_FILE = "optimization_history.csv"

# 节点ID配置
POSITIVE_NODE_ID = "9"
NEGATIVE_NODE_ID = "10"
KSAMPLER_NODE_ID = "4"
LORA_NODE_ID = "12"
SAVE_IMAGE_NODE_ID = "16"

# 相似度阈值（达到这个值就停止优化）
SIMILARITY_THRESHOLD = 0.75
# 最大迭代次数
MAX_TRIALS = 50

# ===== 1. 加载CLIP模型 =====
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🔧 使用设备: {device}")

try:
    clip_model, preprocess = clip.load("ViT-B/32", device=device)
    print("✅ CLIP模型加载成功")
except Exception as e:
    print(f"❌ CLIP加载失败: {e}")
    exit(1)

# ===== 2. 工具函数 =====
def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def calculate_clip_similarity(img1_path, img2_path):
    """计算两张图片的CLIP相似度"""
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
    """从参考图提取风格关键词"""
    style_keywords = [
        "vintage", "retro", "aged paper", "warm tones",
        "watercolor", "illustration", "hand-drawn", "textured",
        "folk art", "rustic", "americana", "cozy",
        "cartoon", "cute", "stylized", "flat",
        "engraved", "etched", "ink", "sketch"
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
        top_style = [s[0] for s in scores[:4]]
        return ", ".join(top_style)
    except:
        return "vintage, retro, warm"

def generate_image(workflow_file, prompt_text, negative_text, label, params, trial_num):
    """用给定参数生成图片"""
    try:
        with open(workflow_file, 'r', encoding='utf-8') as f:
            workflow = json.load(f)
    except:
        print(f"❌ 找不到工作流文件: {workflow_file}")
        return None
    
    # 应用参数
    workflow[KSAMPLER_NODE_ID]['inputs']['steps'] = params['steps']
    workflow[KSAMPLER_NODE_ID]['inputs']['cfg'] = params['cfg']
    workflow[KSAMPLER_NODE_ID]['inputs']['seed'] = params['seed']
    
    if LORA_NODE_ID in workflow:
        workflow[LORA_NODE_ID]['inputs']['strength_model'] = params['lora_weight']
    
    workflow[POSITIVE_NODE_ID]['inputs']['text'] = prompt_text
    workflow[NEGATIVE_NODE_ID]['inputs']['text'] = negative_text
    
    # 设置文件名
    prefix = f"trial_{trial_num:03d}_s{params['steps']}_c{int(params['cfg']*10)}"
    workflow[SAVE_IMAGE_NODE_ID]['inputs']['filename_prefix'] = prefix
    
    payload = {"prompt": workflow}
    try:
        response = requests.post(API_URL, json=payload, timeout=180)
        if response.status_code != 200:
            print(f"❌ 提交失败: {response.status_code}")
            return None
        
        task_id = response.json().get('prompt_id')
        print(f"   📤 任务ID: {task_id}")
        
        # 等待生成完成
        time.sleep(10)
        
        # 查找生成的图片
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

def log_history(style, trial_num, params, similarity, image_path):
    """记录优化历史"""
    import csv
    file_exists = os.path.exists(HISTORY_FILE)
    
    with open(HISTORY_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['style', 'trial', 'steps', 'cfg', 'lora_weight', 'seed', 'similarity', 'image_path', 'timestamp'])
        
        writer.writerow([
            style, trial_num,
            params['steps'], params['cfg'], params['lora_weight'], params['seed'],
            similarity, image_path,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])

# ===== 3. 核心优化函数 =====
def optimize_style(style_name, style_cn, workflow_file, ref_image_path, prompt_text, negative_text):
    """对单个风格进行迭代优化"""
    print(f"\n{'='*70}")
    print(f"🎯 开始优化: {style_cn} ({style_name})")
    print(f"📸 参考图: {ref_image_path}")
    print(f"📝 提示词: {prompt_text[:80]}...")
    print(f"🎯 目标相似度: {SIMILARITY_THRESHOLD}")
    print(f"🔁 最大迭代次数: {MAX_TRIALS}")
    print('='*70)
    
    # 创建结果目录
    os.makedirs(f"{OUTPUT_DIR}/{style_name}", exist_ok=True)
    
    best_score = 0
    best_params = None
    best_image = None
    
    # 记录所有试验
    trials_history = []
    
    def objective(trial):
        nonlocal best_score, best_params, best_image
        
        # Optuna 建议参数
        steps = trial.suggest_int('steps', 20, 35, step=5)
        cfg = trial.suggest_float('cfg', 6.0, 10.0, step=0.5)
        lora_weight = trial.suggest_float('lora_weight', 0.4, 1.0, step=0.05)
        seed = trial.suggest_int('seed', 1, 999999999)
        
        params = {
            'steps': steps,
            'cfg': cfg,
            'lora_weight': lora_weight,
            'seed': seed
        }
        
        trial_num = len(trials_history) + 1
        print(f"\n🔄 第 {trial_num}/{MAX_TRIALS} 次迭代")
        print(f"   📊 参数: steps={steps}, cfg={cfg:.1f}, lora={lora_weight:.2f}, seed={seed}")
        
        # 生成图片
        generated_path = generate_image(
            workflow_file, prompt_text, negative_text, 
            f"{style_name}_{trial_num}", params, trial_num
        )
        
        if generated_path is None:
            return 0.0
        
        # 保存生成的图片到结果目录
        result_path = f"{OUTPUT_DIR}/{style_name}/trial_{trial_num:03d}_score_{best_score:.3f}.png"
        shutil.copy(generated_path, result_path)
        
        # 计算相似度
        similarity = calculate_clip_similarity(result_path, ref_image_path)
        print(f"   📊 相似度: {similarity:.4f}")
        
        # 记录历史
        trials_history.append({
            'trial': trial_num,
            'params': params,
            'similarity': similarity,
            'image_path': result_path
        })
        log_history(style_name, trial_num, params, similarity, result_path)
        
        # 更新最佳
        if similarity > best_score:
            best_score = similarity
            best_params = params.copy()
            best_image = result_path
            print(f"   🏆 新的最佳! 相似度: {best_score:.4f}")
            
            # 保存最佳结果
            best_path = f"{OUTPUT_DIR}/{style_name}/best.png"
            shutil.copy(result_path, best_path)
            
            # 保存最佳参数到JSON
            save_best_params(style_name, best_params, best_score)
        
        # 显示对比信息
        print(f"\n   📈 当前最佳: {best_score:.4f} | 目标: {SIMILARITY_THRESHOLD}")
        print(f"   💡 差距: {SIMILARITY_THRESHOLD - best_score:.4f}")
        print(f"   🔗 生成图: {os.path.basename(result_path)}")
        print(f"   📸 参考图: {os.path.basename(ref_image_path)}")
        
        # 如果达到目标，提前终止
        if similarity >= SIMILARITY_THRESHOLD:
            print(f"\n🎉 已达到目标相似度 {SIMILARITY_THRESHOLD}，停止优化!")
            trial.study.stop()
        
        return similarity
    
    # 创建 Optuna 研究
    study = optuna.create_study(
        direction='maximize',
        study_name=f'{style_name}_optimization',
        storage=None
    )
    
    # 运行优化
    study.optimize(objective, n_trials=MAX_TRIALS, show_progress_bar=True)
    
    # 输出最终结果
    print(f"\n{'='*70}")
    print(f"🏆 {style_cn} 优化完成!")
    print('='*70)
    print(f"   最佳相似度: {study.best_value:.4f}")
    print(f"   最佳参数:")
    print(f"      steps: {study.best_params['steps']}")
    print(f"      cfg: {study.best_params['cfg']:.1f}")
    print(f"      lora_weight: {study.best_params['lora_weight']:.2f}")
    print(f"      seed: {study.best_params['seed']}")
    print(f"   结果保存: {OUTPUT_DIR}/{style_name}/")
    print('='*70)
    
    return study

def save_best_params(style_name, params, score):
    """保存最佳参数到JSON"""
    params_with_score = params.copy()
    params_with_score['score'] = score
    
    if os.path.exists(BEST_PARAMS_FILE):
        with open(BEST_PARAMS_FILE, 'r', encoding='utf-8') as f:
            all_params = json.load(f)
    else:
        all_params = {}
    
    all_params[style_name] = params_with_score
    
    with open(BEST_PARAMS_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_params, f, indent=2, ensure_ascii=False)

# ===== 4. 主函数 =====
def main():
    print("="*70)
    print("  ComfyUI 自动化参数调优系统 v3.0")
    print("  迭代优化 + CLIP评分 + 自动停止")
    print("="*70)
    
    # 读取Excel
    df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
    
    # 风格映射
    style_configs = {
        "vintage": {
            "cn": "复古风格",
            "workflow": "workflow_复古_Funtik.json",
            "ref": "reference_images/vintage.png"
        },
        "watercolor": {
            "cn": "手绘水彩",
            "workflow": "workflow_水彩_SoftWatercolor.json",
            "ref": "reference_images/watercolor.png"
        },
        "minimalist": {
            "cn": "极简风格",
            "workflow": "workflow_极简_MinimalistLine.json",
            "ref": "reference_images/minimalist.png"
        },
        "cartoon": {
            "cn": "卡通手绘",
            "workflow": "workflow_卡通_CoolKids.json",
            "ref": "reference_images/cartoon.png"
        },
        "engraved": {
            "cn": "版画风格",
            "workflow": "workflow_版画_Pastoral.json",
            "ref": "reference_images/engraved.png"
        }
    }
    
    # 选择要优化的风格（可以循环全部，也可以只选一个）
    style_to_optimize = "vintage"  # 改成你要优化的风格，或循环所有
    
    config = style_configs[style_to_optimize]
    
    # 从Excel获取对应的提示词
    style_rows = df[df['风格'] == config['cn']]
    if style_rows.empty:
        print(f"❌ 找不到 {config['cn']} 风格的数据")
        return
    
    row = style_rows.iloc[0]
    prompt_text = row['参考提示词']
    
    # 清理提示词
    prompt_text = re.sub(r' --q\s+[\d.]+', '', prompt_text)
    prompt_text = re.sub(r' --v\s+[\d.]+', '', prompt_text)
    prompt_text = re.sub(r' --ar\s+[\d:]+', '', prompt_text)
    prompt_text = prompt_text.strip()
    
    # 添加风格关键词（从参考图提取）
    if os.path.exists(config['ref']):
        style_keywords = extract_style_from_ref(config['ref'])
        prompt_text = f"{prompt_text}, {style_keywords}"
        print(f"🎨 从参考图提取风格: {style_keywords}")
    
    # 负面提示词
    prohibited = row.get('禁止项', '')
    BASE_NEGATIVE = "worst quality, lowres, ugly, deformed, bad anatomy, blurry, photo, photorealistic, 3d, render"
    negative_text = f"{BASE_NEGATIVE}, {prohibited}" if prohibited else BASE_NEGATIVE
    
    # 运行优化
    study = optimize_style(
        style_name=style_to_optimize,
        style_cn=config['cn'],
        workflow_file=config['workflow'],
        ref_image_path=config['ref'],
        prompt_text=prompt_text,
        negative_text=negative_text
    )
    
    print(f"\n✅ 优化完成！最佳相似度: {study.best_value:.4f}")
    print(f"📁 最佳参数已保存到: {BEST_PARAMS_FILE}")
    print(f"📁 历史记录已保存到: {HISTORY_FILE}")

if __name__ == "__main__":
    main()