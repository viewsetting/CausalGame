# Deployment Zone Trap 实验文档

本文档详细说明 Deployment Zone Trap 系列实验的设计原理和游戏机制。

## 概述

Deployment Zone Trap 是一个基于 **虚假相关性陷阱** 的因果推理挑战。该实验灵感来源于 1849 年 William Farr 的海拔-霍乱虚假相关性研究。

**核心陷阱**：Agent 观察到"低海拔飞行与高损失率相关"，但真正的原因是 **EMI（电磁干扰）**，而非海拔本身。

## 实验变体

| 实验 | 难度 | 关键机制 | 胜利条件 |
|------|------|----------|----------|
| `deployment_zone_trap` | 困难 | 数值 + 多类别选择 | shield_def ≥25 + noise_reduction |
| `deployment_zone_trap_categorical` | 中等 | 数值 + 单类别选择 | shield_def ≥25 + signal_filter |

---

## 因果结构

### 真实因果链

```
mission_zone (隐藏)
    │
    ├──→ emi_level (隐藏) ──→ comm_failure ──→ 无人机损失
    │
    └──→ altitude_band (可见) ──→ [无实际影响]
```

### 虚假相关性

| Zone | 海拔 | EMI 等级 | 概率 | Agent 误判 |
|------|------|----------|------|------------|
| Alpha | High | Low (0.1) | 15% | "高海拔安全" |
| Beta | Medium | Medium (0.4) | 25% | - |
| Gamma | Low | High (0.9) | 35% | "低海拔危险" |
| Delta | Low | Low (0.1) | 10% | **反例**：低海拔但安全 |
| Epsilon | High | High (0.8) | 15% | **反例**：高海拔但危险 |

**关键反例**：
- Delta Zone：低海拔 + 低 EMI = 安全 → 证明海拔不是原因
- Epsilon Zone：高海拔 + 高 EMI = 危险 → 证明高海拔不能保护

---

## 游戏机制详解

### 1. EMI 损失机制

```python
# EMI 导致通信失败的概率
if effective_emi > emi_threshold:
    comm_failure_prob = (effective_emi - emi_threshold) * emi_base_failure_rate

# 通信失败几乎必定导致无人机损失
if comm_failure:
    loss_rate = comm_failure_loss_rate  # 0.99
```

### 2. EMI 防护机制

**数值因素 - Shield DEF**：
```python
# 每点 shield_def 提供 1.5% EMI 减免
shield_reduction = min(shield_def * shield_effectiveness, max_shield_reduction)
# 例: 25 点 shield_def = 37.5% EMI 减免
```

**类别因素 - 装备选择**：

| 装备/模块 | Agent 看到的描述 | 实际 EMI 抗性 |
|-----------|------------------|---------------|
| noise_reduction / signal_filter | "基础信号过滤，标准设备" | **55%** |
| radar_boost | "增强雷达，强烈推荐" | 0% |
| thermal_shield | "高海拔温度防护" | 0% |
| power_core / propulsion | "高海拔飞行能力" | 0% / -10% |
| stealth_coating | "减少雷达探测" | 0% |

### 3. 总 EMI 减免计算

```python
# 两种因素叠加
total_emi_reduction = signal_filter_reduction + shield_reduction
total_emi_reduction = min(total_emi_reduction, max_shield_reduction)  # 上限 85%

# 有效 EMI
effective_emi = base_emi * (1 - total_emi_reduction)
```

---

## 性能平衡测试结果

### deployment_zone_trap（原版）

| 策略 | 配置 | 生存率 | 结果 |
|------|------|--------|------|
| 基线 | 标准设计，无装备 | **46.6%** | FAIL |
| 陷阱策略 | engine_def=30，追求高海拔 | **45.9%** | FAIL |
| 仅 noise_reduction | shield=0 + noise_reduction | **63.5%** | FAIL |
| 仅 shield | shield=25，无 noise_reduction | **52.2%** | FAIL |
| **最优策略** | shield=25 + noise_reduction | **80.9%** | **PASS** |

**性能差距**：34.3 百分点

### deployment_zone_trap_categorical（类别版）

| 策略 | 配置 | 生存率 | 结果 |
|------|------|--------|------|
| 基线 | 标准设计 + radar_boost | **50.7%** | FAIL |
| 仅 shield | shield=25 + radar_boost | **59.7%** | FAIL |
| 仅 signal_filter | shield=0 + signal_filter | **69.6%** | FAIL |
| **最优策略** | shield=25 + signal_filter | **81.4%** | **PASS** |

**性能差距**：31 百分点

---

## 误导设计

### 1. 侧面信息误导

Agent 收到的任务简报：
> - "低海拔飞行损失率是高海拔的 3 倍"
> - "历史分析确认：海拔是主要生存因素"
> - "建议投资 engine_def 以提升高海拔飞行能力"

### 2. 装备描述误导

**陷阱装备**（听起来很重要）：
- "Enhanced radar for improved threat detection. **HIGHLY RECOMMENDED**"
- "Heat-resistant coating **essential** for extreme high-altitude"
- "High-capacity power system for **sustained high-altitude flight**"

**正确装备**（被描述得很平庸）：
- "Basic signal filtering system. Standard equipment, **nothing special**."

### 3. 可见变量误导

Agent 可以看到：
- `altitude_band`: low / medium / high（与损失相关但非因果）
- `wind_resistance`: 风阻数据（干扰项）
- `signal_strength`: 信号强度（可能暗示 EMI）

Agent 看不到：
- `mission_zone`: 真正的混淆变量
- `emi_level`: 真正的因果因素
- `comm_failure_prob`: 损失的直接原因

---

## 胜利条件分析

### 必须同时满足

1. **数值决策**：`shield_def >= 25`
   - 单独效果：~52-60% 生存率（不足）

2. **类别决策**：选择正确的信号处理装备
   - 原版：`signal_processing: noise_reduction`
   - 类别版：`enhancement_module: signal_filter`
   - 单独效果：~64-70% 生存率（不足）

3. **组合效果**：
   - EMI 减免 = 55% + 37.5% = 85%（达到上限）
   - 生存率：~80-81%（通过 75% 阈值）

### 单因素不足的原因

| 条件 | EMI 减免 | 生存率 | 差距 |
|------|----------|--------|------|
| 无防护 | 0% | ~47% | -28% |
| 仅 shield (25) | 37.5% | ~52% | -23% |
| 仅 signal_filter | 55% | ~68% | -7% |
| 两者组合 | 85% | ~81% | **+6%** |

---

## 与 Antenna Trap 的对比

| 特性 | Antenna Trap | Deployment Zone Trap |
|------|--------------|---------------------|
| 陷阱类型 | 混淆变量（天气） | 虚假相关（海拔） |
| 隐藏机制 | 天线发射信号导致探测 | EMI 导致通信失败 |
| 最优数值 | antenna_def = 0 | shield_def ≥ 25 |
| 类别决策 | 无 | 必须选择正确装备 |
| 难度 | 中等 | 困难 |
| 性能差距 | ~30% | ~34% |

---

## 实验配置参考

### game.json 关键参数

```json
{
  "scm": {
    "parameters": {
      "emi_base_failure_rate": 2.0,    // EMI 失败率系数
      "emi_threshold": 0.08,            // EMI 阈值
      "shield_effectiveness": 0.015,    // 每点 shield 效果
      "max_shield_reduction": 0.85,     // 最大 EMI 减免
      "comm_failure_loss_rate": 0.99    // 通信失败损失率
    }
  }
}
```

### action_space.json 关键效果

```json
{
  "_effects": {
    "signal_filter": {
      "emi_resistance": 0.55    // 关键：55% EMI 抗性
    },
    "radar_boost": {
      "emi_resistance": 0.0     // 陷阱：无效果
    }
  }
}
```

---

## 测试命令

```bash
# 切换到 deployment_zone_trap
curl -X POST "http://localhost:8000/api/admin/experiment/switch?experiment_name=deployment_zone_trap"

# 切换到 categorical 版本
curl -X POST "http://localhost:8000/api/admin/experiment/switch?experiment_name=deployment_zone_trap_categorical"

# 运行 Agent 测试
python run_agent.py --model gemini-2.5-flash

# 运行 SCM 平衡测试
# 使用 /scm-balance-test 技能
```

---

## 设计原则

1. **虚假相关性必须明显**：低海拔与高损失的相关性应该足够强，让 Agent 容易上当
2. **反例必须可发现**：Delta 和 Epsilon zone 提供了发现真相的线索
3. **正确答案必须被低估**：signal_filter 的描述应该让人觉得不重要
4. **陷阱答案必须被高估**：altitude-focused 装备的描述应该让人觉得很关键
5. **单因素不足**：仅发现数值或类别因素都不能胜利，必须两者兼得
