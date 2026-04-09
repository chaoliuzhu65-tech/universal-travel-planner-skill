# Universal Travel Planner Skill 🌍

> **面向所有商务出差人士的AI出行规划技能** · MIT License

一句话描述：一站式AI商旅出行规划 + 全平台酒店比价 + 精美HTML报告生成。

## ✨ 功能特性

- 🚄 **实时交通查询**：12306 MCP 实时查票 + 高德路径规划 + 航班搜索
- 🏨 **全平台酒店比价**：携程 / 飞猪 / 去哪儿 / Booking / Agoda，多平台平等推荐
- 📊 **智能预算计算**：经济 / 舒适 / 商务 三档标准自动计算
- 📱 **HTML报告生成**：实时生成精美响应式HTML页面
- 🔗 **真实跳转链接**：所有预订链接真实可一键跳转
- 🗺️ **地图集成**：高德地图 POI 搜索 + 路径规划 + 天气查询
- 📋 **出行清单**：自动生成携带物品清单

## 🚀 快速开始

### 1. 安装到 WorkBuddy / OpenClaw

```bash
# 克隆仓库
git clone https://github.com/YOUR_USERNAME/universal-travel-planner-skill.git

# 复制 Skill 文件
cp SKILL.md ~/.openclaw/skills/universal-travel-planner/
# 或复制到项目目录
cp SKILL.md .workbuddy/skills/universal-travel-planner/
```

### 2. 配置 MCP 服务器

在 `~/.workbuddy/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "12306-mcp": {
      "command": "npx",
      "args": ["-y", "12306-mcp"]
    }
  }
}
```

### 3. 配置环境变量（可选，提升体验）

```bash
# 高德地图 API Key（免费申请：https://lbs.amap.com/）
export AMAP_WEB_KEY="your_amap_web_service_key"
export AMAP_JSAPI_KEY="your_amap_jsapi_key"        # 可选，用于交互地图
export AMAP_SECURITY_CODE="your_security_js_code"  # 可选，前端安全密钥
```

### 4. 开始使用

```
"帮我规划北京到上海出差，5月15-17日，预算舒适档"
"从广州到深圳怎么走？帮我看看高铁和飞机"
"帮我找杭州西湖附近的酒店，下周五入住"
```

## 📁 项目结构

```
universal-travel-planner/
├── SKILL.md                    # 核心 Skill 文件
├── README.md                   # 本文件
├── clawhub.json               # ClawHub 发布配置
├── .gitignore                 # Git 忽略规则
├── demo_beijing_travel.html   # 演示页面（北京出差）
├── scripts/                   # 辅助脚本（预留）
└── templates/                 # HTML 模板（预留）
```

## 🛠️ 技术栈

| 技术 | 用途 |
|------|------|
| 12306 MCP Server | 火车票实时查询 |
| 高德地图 API | 地图/路径规划/POI/天气 |
| Web Search | 航班/酒店价格搜索 |
| HTML/CSS | 报告生成 |
| Python | 预算计算模块 |

## 🔗 预订链接平台

| 平台 | 用途 |
|------|------|
| 12306.cn | 火车票查询/购买 |
| 携程 | 国内酒店/机票 |
| 飞猪 | 阿里系酒店/机票 |
| 去哪儿 | 酒店比价 |
| Booking.com | 国际酒店 |
| Agoda | 亚洲酒店 |
| 高德地图 | 路线规划/导航 |

## 📋 使用示例

**输入**：
```
帮我规划4月23-24日重庆出差，我是公司管理层，
4月24日全天在会展中心有行业会议。
从北京出发，帮我看看飞机和高铁。
```

**输出**：
1. 北京→重庆交通方案对比（航班+高铁）
2. 全平台酒店推荐（含多平台价格对比）
3. 详细行程时间线
4. 预算明细表
5. 目的地攻略（天气/美食/景点）
6. HTML报告文件（所有链接可点击跳转）

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License - 自由使用、修改、分发。

---

**作者**: AI Travel Planner Community
**版本**: 1.0.0
**更新**: 2026-04-09
