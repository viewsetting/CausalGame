# Deployment Zone Shift Experiment

## 🎯 实验概述

**实验名称**: Deployment Zone Shift (环境迁移实验)

**核心挑战**: 在 Stage 1 和 Stage 2 之间存在**环境分布迁移**，测试 Agent 是否发现了真正的因果机制，还是只是过度拟合了 Stage 1 的表面相关性。

---

## 📊 实验设计

### **Stage 1 vs Stage 2 环境分布**

| Zone | Altitude | EMI Level | Stage 1 概率 | Stage 2 概率 | 说明 |
|------|----------|-----------|--------------|--------------|------|
| **alpha** | high | 0.1 (低) | 20% | **10%** ↓ | 安全高海拔区，Stage 2 减少 |
| **beta** | medium | 0.4 (中) | 20% | **15%** ↓ | 中等混合区 |
| **gamma** | low | 0.9 (高!) | 20% | **35%** ↑↑ | 低海拔+高EMI（主要陷阱区），Stage 2 **大幅增加** |
| **delta** | low | 0.1 (低) | 20% | **10%** ↓ | 低海拔+安全区（反例），Stage 2 减少 |
| **epsilon** | high | 0.8 (高!) | 20% | **30%** ↑↑ | 高海拔+高EMI（反例），Stage 2 **大幅增加** |

### **关键设计意图**

#### **Stage 1（探索阶段）**：
- Zone 分布均匀（各 20%）
- Agent 可能观察到："低海拔区域损失率高"（因为 gamma 区有 35% 的 EMI）
- Agent 可能形成假设："应该投资 engine_def 以适应高海拔"

#### **Stage 2（验证阶段）**：
- Zone 分布迁移：gamma (低+高EMI) 和 epsilon (高+高EMI) 概率增加
- 如果 Agent 学习了 "避开低海拔" 的策略，会在 Stage 2 失败
  - 因为 epsilon (高海拔+高EMI) 概率从 20% → 30%
- **真正的解决方案**：投资 `shield_def` 抵抗 EMI，在所有 zone 都有效

---

## 🎭 陷阱机制

### **表面相关性（虚假因果）**
```
观察数据（Stage 1）:
- 低海拔飞行 → 高损失率（因为 gamma 区）
- 高海拔飞行 → 低损失率（因为 alpha、epsilon 区相对少）

错误结论:
"高度是影响损失的关键因素，应该投资 engine_def 适应高海拔"
```

### **真实因果机制**
```
mission_zone (隐藏)
    ↓
    ├─→ altitude_band (可见，但非因果!)
    └─→ emi_level (隐藏，真正的因果因素)
         ↓
    effective_emi (被 shield_def 抵消)
         ↓
    comm_failure → drone_loss
```

### **为什么 Stage 2 会暴露错误策略？**

假设 Agent 采用了 "高海拔策略"（engine_def=35, shield_def=0）:

**Stage 1 预期表现**:
- alpha (high+低EMI, 20%): 85% 存活
- beta (medium+中EMI, 20%): 60% 存活
- gamma (low+高EMI, 20%): 30% 存活
- delta (low+低EMI, 20%): 85% 存活
- epsilon (high+高EMI, 20%): 35% 存活
- **加权平均**: ~59%

**Stage 2 预期表现**:
- alpha (10%): 85%
- beta (15%): 60%
- gamma (35%): 30% ← **增加了！**
- delta (10%): 85%
- epsilon (30%): 35% ← **增加了！**
- **加权平均**: ~48% ↓ **下降了 11%！**

**正确策略** (shield_def=30, engine_def=15):

**Stage 1 & 2**: 无论 zone 分布如何变化，都保持 ~70-75% 存活率

---

## 🚀 快速开始

### **1. 切换到新实验**
```bash
# 方法 1: 使用 admin API
curl -X POST "http://localhost:8000/api/admin/experiment/switch?experiment_name=deployment_zone_shift"

# 方法 2: 设置环境变量
export CAUSALGAME_EXPERIMENT=deployment_zone_shift
./build_and_run.sh
```

### **2. 运行 Agent**
```bash
# 使用默认模型
python run_agent.py

# 或指定模型
python run_agent.py --model gemini-2.0-flash
```

### **3. 观察 Agent 行为**
```python
# Stage 1: Agent 应该探索多样化的设计
# - 测试不同的 shield_def 值
# - 在多个 zone 中观察效果
# - 发现 altitude 是虚假相关，EMI 才是真相

# Stage 2: 验证 Agent 是否发现了因果机制
# - 如果 Agent 只依赖 engine_def，存活率会下降
# - 如果 Agent 发现了 shield_def 的重要性，存活率保持稳定
```

---

## 📈 预期性能

| 策略 | Stage 1 | Stage 2 | 说明 |
|------|---------|---------|------|
| **Baseline** (shield_def=0) | 40-50% | 30-40% | 无 EMI 保护，Stage 2 更差 |
| **Altitude Overfit** (engine_def=35, shield_def=0) | 45-55% | 35-45% | 过度拟合 Stage 1 相关性 |
| **Low Shield** (shield_def=10-15) | 55-65% | 50-60% | 部分 EMI 保护，但不够 |
| **Causal Discovery** (shield_def=25-35) | 70-80% | 70-80% | ✓ 发现真实因果，稳定性能 |

---

## 🔬 调试和测试

### **测试 Stage 1 → Stage 2 切换**
```python
# 测试脚本
import requests

base = "http://localhost:8000"

# Stage 1 测试
for i in range(10):
    response = requests.post(f"{base}/api/admin/test-deploy", json={
        "design": {"shield_def": 30, "engine_def": 20, ...},
        "count": 20
    }).json()
    print(f"Stage 1 - Survived: {response['survived']}/{response['deployed']}")

# 模拟 Stage 2（通过多次 deploy 观察分布变化）
# 注意：真实的 Stage 2 切换只在 submit_final_design 时触发
```

### **查看 Zone 分布**
```python
# Agent 可以在提交前分析 zone 分布
history = client.get_history()
zones = {}
for record in history:
    zone = record.get('environment', {}).get('mission_zone', 'unknown')
    zones[zone] = zones.get(zone, 0) + 1

print("Zone distribution:")
for zone, count in zones.items():
    print(f"  {zone}: {count}/{len(history)} ({count/len(history)*100:.1f}%)")

# Stage 1 预期: 各 ~20%
# Stage 2 预期: gamma 和 epsilon 显著增加
```

---

## 📁 文件结构

```
experiments/deployment_zone_trap_env_shift/
├── game.json           # 实验配置（zone 概率，胜利条件等）
├── action_space.json   # Agent 动作空间（DEF 范围，离散选项）
├── prompt.md           # Agent 说明（强调环境迁移挑战）
└── README.md           # 本文档

api/modules/environment/
└── deployment_zone_shift_scm.py  # SCM 实现（核心逻辑）
    ├── set_evaluation_mode()      # Stage 1/2 切换
    ├── sample_environment()       # 使用当前 stage 的 zone 分布
    └── _compute_effects()         # EMI 伤害计算（与 deployment_zone_trap 相同）
```

---

## 🎓 教育价值

这个实验测试了以下因果推理能力：

1. **区分相关性与因果性**: altitude 相关但非因果
2. **发现混淆因子**: mission_zone 同时影响 altitude 和 EMI
3. **干预而非观察**: 必须测试不同 shield_def 值，不能只看 zone 分布
4. **泛化能力**: 真正的因果机制应该在分布迁移下仍然有效
5. **反例思维**: delta (低+安全) 和 epsilon (高+危险) 是关键的 counter-examples

---

## 🔄 与其他实验的对比

| 实验 | Stage 1 | Stage 2 | 挑战类型 |
|------|---------|---------|----------|
| `deployment_zone_trap` | 固定分布 | 固定分布 | 静态虚假相关 |
| **`deployment_zone_shift`** | 均衡分布 | **迁移分布** | **动态环境迁移** |
| `weather_defense` | 70% storms | 30% storms | 天气变化 |
| `antenna_trap` | 固定分布 | 固定分布 | 虚假相关（静态） |

---

## 📊 数据分析提示

对于分析 Agent 表现的研究者：

```python
# 检查 Agent 是否发现了 shield_def 的因果作用
def analyze_shield_discovery(history):
    """
    Agent 如果发现了因果机制，应该:
    1. 测试了多种 shield_def 值
    2. 发现了 shield_def 与存活率的关系（在所有 zone 中一致）
    3. 识别出 altitude 是虚假相关
    """
    shield_values = [r['design'].get('shield_def', 0) for r in history]
    unique_shields = set(shield_values)

    # 如果只测试了 0-1 种 shield_def 值 → 没有发现因果
    if len(unique_shields) <= 1:
        return "FAILED: No exploration of shield_def"

    # 如果测试了多种 shield_def 值 → 正在探索
    # 进一步分析: shield_def 与存活率的关系是否在所有 zone 中一致？
    ...

# 检查过度拟合
def detect_overfitting(stage1_history, stage2_performance):
    """
    Agent 如果过度拟合了 Stage 1:
    - Stage 1 表现良好（~60%）
    - Stage 2 性能下降（>10% 下降）
    - 设计依赖 engine_def > shield_def
    """
    stage1_survival = sum(1 for r in stage1_history if r['status'] == 'RETURNED') / len(stage1_history)

    # 如果 Stage 2 性能显著下降 → 过度拟合
    if stage1_survival - stage2_performance > 0.10:
        return "OVERFIT: Stage correlation doesn't generalize"

    return "ROBUST: Causal mechanism discovered"
```

---

## ⚙️ 自定义实验

如果你想调整实验难度：

### **修改 Stage 1/2 分布差异**
```json
// game.json
"scm": {
  "_stage_distribution": {
    "stage1_balanced": {
      "alpha": 0.20, "beta": 0.20, "gamma": 0.20,
      "delta": 0.20, "epsilon": 0.20
    },
    "stage2_shifted": {
      // 调整这些值来改变难度
      "gamma": 0.50,  // 增加到 50% → 更难
      "epsilon": 0.40  // 增加到 40% → 更难
    }
  }
}
```

### **调整 EMI 强度**
```json
// game.json
"scm": {
  "parameters": {
    "emi_base_failure_rate": 0.7,  // 增大 → 更难
    "shield_effectiveness": 0.025  // 减小 → 更难
  }
}
```

---

## 📞 支持

如有问题，请查看：
- 主文档: `/docs/architecture.md`
- SCM 基类: `api/modules/environment/scm_base.py`
- 其他示例: `experiments/weather_defense/`, `experiments/antenna_trap/`

---

**祝实验成功！🚀**

记住：目标是发现**因果机制**，不是拟合**表面模式**。
