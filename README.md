# ComfyUI 批量生成自动化工作流

本项目提供一套完整的 ComfyUI 图片批量生成自动化解决方案，支持多风格 LoRA 切换、参数自动调优、中文文件名输出等功能。

## 📁 项目结构

```
工作流/
├── py.bat                    # 一键启动脚本
├── batch_generate.py         # 批量生成主脚本
├── optimize_all_lora.py      # LoRA参数自动调优
├── extract_reference_images.py # 从Excel导出参考图片
├── data.py                   # 提示词预处理（已弃用，保留兼容）
├── auto_tune.py              # 另一个调优工具
├── best_lora_params.json     # 调优后最佳参数（自动生成）
├── lora_optimization_history.csv # 调优历史记录
├── reference_images/         # 参考图片目录（自动生成）
├── lora_tuning_results/      # 调优结果目录（自动生成）
├── venv/                     # Python虚拟环境
├── 提示词.xlsx               # 数据源（需自行准备）
└── workflow_*.json           # ComfyUI工作流文件
```

## 🚀 快速开始

### 1. 环境准备

确保已安装 Python 3.8+，然后创建虚拟环境：

```bash
python -m venv venv
```

激活虚拟环境并安装依赖：

```bash
# Windows
venv\Scripts\activate
pip install pandas requests pillow openpyxl openpyxl_image_loader optuna -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 准备数据

将 `提示词.xlsx` 放入项目根目录，Excel 需包含以下列：

| 列名 | 说明 | 示例 |
|------|------|------|
| 参考提示词 | 正向提示词（英文） | Halloween, vintage Americana... |
| 卖点变量标签 | 中文文件名标签 | 万圣-复古风格-橙色-南瓜 |
| 禁止项 | 负面提示词 | text, watermark |
| 生成图片参考图 | 参考图片（可选） | [内嵌图片] |

### 3. 启动 ComfyUI

确保 ComfyUI 已启动并运行在端口 `8188`。

### 4. 一键运行

双击 `py.bat` 即可执行完整流程：

```
步骤：1.导出参考图 → 2.参数调优 → 3.批量生成
```

## 📋 详细说明

### py.bat - 一键启动脚本

自动执行以下步骤：

1. **检测环境**：检查虚拟环境和 ComfyUI 服务
2. **导出参考图片**：从 Excel 提取参考图到 `reference_images/`
3. **参数调优**：运行 `optimize_all_lora.py` 自动优化参数
4. **批量生成**：运行 `batch_generate.py` 生成所有图片

### batch_generate.py - 批量生成主脚本

**核心功能：**
- 从 Excel 读取 `参考提示词`、`卖点变量标签`、`禁止项` 等数据
- 根据提示词自动检测风格并切换对应工作流
- 加载 `best_lora_params.json` 中的最佳参数（steps, cfg, lora_weight）
- 使用中文 `卖点变量标签` 作为输出文件名
- 支持批量提交到 ComfyUI API

**风格映射：**
| 风格代码 | 工作流文件 | 关键词 |
|----------|-----------|--------|
| vintage | workflow_复古_Funtik.json | vintage, retro, folk art |
| watercolor | workflow_水彩_SoftWatercolor.json | watercolor, brushstrokes |
| minimalist | workflow_极简_MinimalistLine.json | minimalist, fine line |
| cartoon | workflow_卡通_CoolKids.json | cartoon, hand-drawn |
| engraved | workflow_版画_Pastoral.json | engraved, etched |

### optimize_all_lora.py - LoRA 参数调优

使用 Optuna 进行超参数优化：
- 优化参数：`strength_model`, `strength_clip`, `steps`, `cfg`
- 每个风格最多 30 次试验
- 使用 CLIP 相似度评估（可选）
- 结果保存到 `best_lora_params.json`

### extract_reference_images.py - 参考图片导出

从 Excel 的 `生成图片参考图` 列提取内嵌图片，保存到 `reference_images/` 目录。

## 🎨 工作流文件

需准备以下工作流文件（放置在项目根目录）：

- `workflow_复古_Funtik.json`
- `workflow_水彩_SoftWatercolor.json`
- `workflow_极简_MinimalistLine.json`
- `workflow_卡通_CoolKids.json`
- `workflow_版画_Pastoral.json`

## 📝 配置说明

### batch_generate.py 关键配置

```python
API_URL = "http://127.0.0.1:8188/prompt"  # ComfyUI地址
EXCEL_FILE = "提示词.xlsx"                # Excel文件名
SHEET_NAME = "Prompt生成表--卖点 原"      # 工作表名
DELAY_BETWEEN_REQUESTS = 3               # 请求间隔（秒）
```

### 节点 ID 配置

| 节点 | ID | 说明 |
|------|-----|------|
| 正向 CLIP 文本编码 | 9 | 正向提示词 |
| 负向 CLIP 文本编码 | 10 | 负向提示词 |
| KSampler | 4 | steps, cfg |
| LoRA Loader | 12 | strength_model, strength_clip |
| SaveImage | 16 | filename_prefix |

## 📊 输出文件

- **生成的图片**：保存在 ComfyUI 的 `output` 文件夹，文件名格式：`卖点变量标签_00001_.png`
- **调优参数**：`best_lora_params.json`
- **参考图片**：`reference_images/`
- **调优历史**：`lora_optimization_history.csv`
- **日志文件**：`batch_generate_YYYYMMDD_HHMMSS.log`

## 🔧 常见问题

### Q: 提示虚拟环境不存在？
A: 运行 `python -m venv venv` 创建虚拟环境。

### Q: ComfyUI 连接失败？
A: 确保 ComfyUI 已启动，端口为 8188。

### Q: 文件名是英文不是中文？
A: 确保 Excel 中 `卖点变量标签` 列有值，代码会优先使用该列。

### Q: 参数调优耗时太长？
A: 可修改 `optimize_all_lora.py` 中的 `MAX_TRIALS` 减少试验次数。

## 📄 许可证

MIT License

---

**提示**：首次运行建议先单独测试 `batch_generate.py`，确认流程正常后再使用 `py.bat` 一键执行。
