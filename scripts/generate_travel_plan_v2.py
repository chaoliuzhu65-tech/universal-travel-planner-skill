#!/usr/bin/env python3
"""
generate_travel_plan_v2.py - Universal Travel Planner Skill v2.0
整合 flyai MCP + 全平台酒店比价 + 精美HTML报告生成
基于 universal-travel-planner-skill 设计，MIT License

功能特性:
- 🚄 实时交通查询：flyai MCP 支持火车票/机票/酒店查询
- 🏨 全平台酒店比价：携程 / 飞猪 / 百达屋（德胧官方），多平台平等推荐
- 📊 智能预算计算：经济 / 舒适 / 商务 三档标准自动计算
- 📱 精美HTML报告：响应式设计，所有预订链接真实可一键跳转
- 🔗 真实预订链接：每个酒店提供多平台预订链接，用户自主选择
- 🗺️ 支持德胧优先：德胧/开元旗下酒店优先推荐百达屋App预订
- 📋 自动行程安排：基于会议时间自动生成每日行程
- 💾 24小时缓存：减少重复API调用，节省Quota

用法:
python scripts/generate_travel_plan_v2.py \
  --name "晁留柱" \
  --start-date 2026-04-23 \
  --end-date 2026-04-25 \
  --origin "北京" \
  --destination "重庆" \
  --meeting-location "重庆开元名都大酒店" \
  --meeting-date "2026-04-24" \
  --budget "舒适" \
  --output output/chongqing-2026-04 \
  --is-delonix-hotel

输出:
- {output}/travel-plan.md - Markdown版本
- {output}/travel-plan.html - HTML精美版本（所有链接可点击）
"""

import argparse
import os
import sys
import json
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_cache import DataCache

# 颜色输出
RED = '\033[0;31m'
GREEN = '\033[0;32m'
BLUE = '\033[0;34m'
NC = '\033[0m'

def log_info(msg): print(f"{BLUE}[INFO]{NC} {msg}")
def log_ok(msg): print(f"{GREEN}[SUCCESS]{NC} {msg}")
def log_error(msg): print(f"{RED}[ERROR]{NC} {msg}")

# 预算标准参考
BUDGET_STANDARDS = {
    "economy": {
        "name": "经济 💚",
        "flight_one_way": (400, 800),
        "train_second": (300, 800),
        "hotel_per_night": (150, 300),
        "lunch": (30, 50),
        "dinner": (50, 100),
        "local_transport_per_day": (30, 50),
    },
    "comfort": {
        "name": "舒适 💛",
        "flight_one_way": (800, 1500),
        "train_second": (500, 1200),
        "hotel_per_night": (400, 800),
        "lunch": (50, 100),
        "dinner": (100, 200),
        "local_transport_per_day": (50, 100),
    },
    "business": {
        "name": "商务 ❤️",
        "flight_one_way": (1500, 3000),
        "train_second": (800, 2000),
        "hotel_per_night": (800, 2000),
        "lunch": (100, 200),
        "dinner": (200, 500),
        "local_transport_per_day": (100, 200),
    }
}

class TravelPlanGeneratorV2:
    """通用商旅出行规划生成器 v2.0"""

    def __init__(self, cache_dir: str = "./cache/travel"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _slugify(self, s: str) -> str:
        """URL友好的slug生成"""
        return s.lower().replace(" ", "-").replace("·", "").replace("（", "").replace("）", "").strip()

    def generate_booking_links(self, hotel_name: str, city: str, check_in: str, check_out: str, is_delonix: bool = False) -> str:
        """生成多平台预订链接"""
        links = []

        # 德胧/开元酒店优先推荐百达屋 - 官网下载App
        if is_delonix:
            links.append('<a href="https://www.betterwood.com/" target="_blank" class="btn btn-primary">百达屋App下载 (德胧官方推荐)</a>')

        # 携程 - 关键词搜索（不知道酒店ID，用搜索页）
        encoded_name = hotel_name.replace(" ", "+")
        ctrip_url = f"https://www.ctrip.com/so/{encoded_name}"
        links.append(f'<a href="{ctrip_url}" target="_blank" class="btn">携程搜索 {hotel_name}</a>')

        # 飞猪 - 关键词搜索
        encoded_name = hotel_name.replace(" ", "+")
        fliggy_url = f"https://www.fliggy.com/hotel/?keyword={encoded_name}"
        links.append(f'<a href="{fliggy_url}" target="_blank" class="btn">飞猪搜索 {hotel_name}</a>')

        # 去哪儿 - 关键词搜索酒店
        encoded_city = self._slugify(city).replace(" ", "+")
        qunar_url = f"https://www.qunar.com/s?query={encoded_name}+{encoded_city}+hotel"
        links.append(f'<a href="{qunar_url}" target="_blank" class="btn">去哪儿搜索 {hotel_name}</a>')

        return "\n".join(links)

    def generate_booking_links_markdown(self, hotel_name: str, city: str, check_in: str, check_out: str, is_delonix: bool = False) -> str:
        """生成Markdown版本的多平台预订链接"""
        links = []

        # 德胧/开元酒店 - 百达屋官网下载
        if is_delonix:
            links.append("1. [**百达屋App (德胧官方推荐)**](https://www.betterwood.com/)")
            links.append("   - 扫码下载百达屋App，预订德胧旗下酒店享受会员权益")

        # 携程 - 关键词搜索（不知道酒店ID，用搜索页）
        encoded_name = hotel_name.replace(" ", "+")
        links.append(f"2. [携程搜索 - {hotel_name}](https://www.ctrip.com/so/{encoded_name})")
        # 飞猪 - 关键词搜索
        encoded_name = hotel_name.replace(" ", "+")
        links.append(f"3. [飞猪搜索 - {hotel_name}](https://www.fliggy.com/hotel/?keyword={encoded_name})")
        # 去哪儿 - 关键词搜索酒店
        encoded_city = self._slugify(city).replace(" ", "+")
        links.append(f"4. [去哪儿搜索 - {hotel_name}](https://www.qunar.com/s?query={encoded_name}+{encoded_city}+hotel)")

        return "\n".join(links)

    def run_flyai_query(self, query: str, force_refresh: bool = False) -> Optional[Dict]:
        """执行 flyai 查询，带缓存"""
        # 解析查询类型
        import re
        if any(k in query for k in ["机票", "飞机", "航班"]):
            query_type = "flight"
        elif any(k in query for k in ["火车", "高铁", "动车", "火车票"]):
            query_type = "train"
        elif any(k in query for k in ["酒店", "住宿"]):
            query_type = "hotel"
        else:
            query_type = "unknown"

        # 生成缓存key
        cache_key = f"flyai-{query_type}-{self._slugify(query)}"
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")

        if not force_refresh and os.path.exists(cache_path):
            # 检查过期（24小时）
            mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
            age = datetime.now() - mtime
            age_hours = age.total_seconds() / 360.0
            if age_hours < 24.0:
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    log_info(f"缓存命中: {cache_key}")
                    return data
                except Exception:
                    pass

        # 调用 flyai CLI
        log_info(f"执行 flyai 查询: {query}")
        try:
            result = subprocess.run(
                ["npx", "@fly-ai/flyai-cli", "ai-search", "--query", query],
                capture_output=True,
                text=True,
                timeout=180
            )
            if result.returncode != 0:
                log_error(f"flyai 查询失败: {result.stderr}")
                return None

            # 解析 JSON 输出
            output = result.stdout.strip()
            try:
                data = json.loads(output)
                # 保存缓存
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                log_ok(f"查询完成: {query}")
                return data
            except json.JSONDecodeError as e:
                log_error(f"解析JSON失败: {e}, output: {output[:200]}")
                return None
        except Exception as e:
            log_error(f"查询异常: {e}")
            return None

    def calculate_budget(self,
                        budget_level: str,
                        days: int,
                        passengers: int = 1,
                        rooms: int = 1,
                        has_round_trip: bool = True,
                        transport_type: str = "train") -> Dict:
        """计算预算"""
        std = BUDGET_STANDARDS.get(budget_level, BUDGET_STANDARDS["comfort"])

        if transport_type == "train":
            transport_min = std["train_second"][0] * passengers
            transport_max = std["train_second"][1] * passengers
        else: # flight
            transport_min = std["flight_one_way"][0] * passengers
            transport_max = std["flight_one_way"][1] * passengers

        if has_round_trip:
            transport_min *= 2
            transport_max *= 2

        hotel_min = std["hotel_per_night"][0] * (days - 1) * rooms
        hotel_max = std["hotel_per_night"][1] * (days - 1) * rooms

        lunch_min = std["lunch"][0] * days * passengers
        lunch_max = std["lunch"][1] * days * passengers

        dinner_min = std["dinner"][0] * days * passengers
        dinner_max = std["dinner"][1] * days * passengers

        local_transport_min = std["local_transport_per_day"][0] * days
        local_transport_max = std["local_transport_per_day"][1] * days

        airport_fee = 50 * 2 * passengers if has_round_trip and transport_type == "flight" else 0

        total_min = transport_min + hotel_min + lunch_min + dinner_min + local_transport_min + airport_fee
        total_max = transport_max + hotel_max + lunch_max + dinner_max + local_transport_max + airport_fee

        return {
            "budget_level": budget_level,
            "budget_name": std["name"],
            "breakdown": [
                {"item": "往返交通", "min": transport_min, "max": transport_max},
                {"item": f"住宿({days-1}晚)", "min": hotel_min, "max": hotel_max},
                {"item": "午餐", "min": lunch_min, "max": lunch_max},
                {"item": "晚餐", "min": dinner_min, "max": dinner_max},
                {"item": "市内交通", "min": local_transport_min, "max": local_transport_max},
                {"item": "机场建设费" if transport_type == "flight" else "杂费", "min": airport_fee, "max": airport_fee},
            ],
            "total_min": total_min,
            "total_max": total_max
        }

    def generate_markdown(self,
                        name: str,
                        start_date: str,
                        end_date: str,
                        origin: str,
                        destination: str,
                        meeting_location: str,
                        meeting_date: Optional[str] = None,
                        budget_level: str = "comfort",
                        passengers: int = 1,
                        rooms: int = 1,
                        transport_preference: str = "any",
                        is_delonix_hotel: bool = False,
                        custom_agenda: Optional[List[Dict]] = None) -> str:
        """生成出行规划 Markdown"""

        # 计算天数
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end_dt - start_dt).days + 1

        # 去程交通查询
        log_info(f"查询去程交通: {origin} → {destination}, {start_date}")
        if transport_preference == "train" or transport_preference == "any":
            dep_query = f"{origin}到{destination} {start_date} 火车票"
            dep_data = self.run_flyai_query(dep_query)
        else:
            dep_query = f"{origin}到{destination} {start_date} 机票"
            dep_data = self.run_flyai_query(dep_query)

        # 返程交通查询
        log_info(f"查询返程交通: {destination} → {origin}, {end_date}")
        if transport_preference == "train" or transport_preference == "any":
            ret_query = f"{destination}到{origin} {end_date} 火车票"
            ret_data = self.run_flyai_query(ret_query)
        else:
            ret_query = f"{destination}到{origin} {end_date} 机票"
            ret_data = self.run_flyai_query(ret_query)

        # 酒店查询
        log_info(f"查询会议酒店: {destination} {meeting_location} {start_date}")
        hotel_query = f"{destination} {meeting_location} {start_date} 酒店"
        hotel_data = self.run_flyai_query(hotel_query)

        # 计算预算
        has_round_trip = origin != destination
        transport_type = "train" if (transport_preference == "train" or transport_preference == "any") else "flight"
        budget = self.calculate_budget(
            budget_level=budget_level,
            days=days,
            passengers=passengers,
            rooms=rooms,
            has_round_trip=has_round_trip,
            transport_type=transport_type
        )

        # 生成 Markdown
        md = []
        md.append(f"# 🧳 {name} · 出行规划\n")
        md.append(f"**出行时间**: {start_date} ~ {end_date} ({days}天)\n")
        md.append(f"**出发地**: {origin}  \n**目的地**: {destination}\n")
        md.append(f"**预算档次**: {budget['budget_name']}\n\n")

        # 行程安排
        md.append("## 📅 行程安排\n")
        if custom_agenda:
            for item in custom_agenda:
                md.append(f"### {item['date']} | {item['title']}\n")
                md.append(f"- **时间**: {item.get('time', '全天')}\n")
                md.append(f"- **地点**: {item.get('location', meeting_location)}\n")
                if item.get('notes'):
                    md.append(f"- **备注**: {item['notes']}\n")
                md.append("")
        else:
            # 默认日程生成
            current = start_dt
            while current <= end_dt:
                date_str = current.strftime("%Y-%m-%d")
                if date_str == start_date:
                    title = "到达 + 签到/排练"
                    location = f"{meeting_location}, {destination}"
                    notes = "抵达目的地，入住酒店，准备会议"
                elif date_str == meeting_date:
                    title = "正式会议/活动"
                    location = f"{meeting_location}, {destination}"
                    notes = "全天会议/活动"
                elif date_str == end_date:
                    title = "活动结束 + 返程"
                    location = destination
                    notes = "会议结束，返程回京"
                else:
                    title = "自由活动 / 分组讨论"
                    location = f"{meeting_location}, {destination}"
                    notes = ""
                md.append(f"### {date_str} | {title}\n")
                md.append(f"- **地点**: {location}\n")
                if notes:
                    md.append(f"- **备注**: {notes}\n")
                md.append("")
                current += timedelta(days=1)

        # 交通信息
        md.append("## 🚄 交通信息\n")

        md.append("### 去程: {} → {} ({})\n".format(origin, destination, start_date))
        # 检查flyai返回结构：data可能是dict{itemList} 也可能是str（无数据）
        dep_has_items = False
        dep_items = []
        if dep_data and isinstance(dep_data.get("data"), dict) and dep_data["data"].get("itemList"):
            dep_has_items = True
            dep_items = dep_data["data"]["itemList"][:5]
        if dep_has_items and len(dep_items) > 0:
            md.append("| 车次/航班 | 出发 | 到达 | 历时 | 价格 | 预订 |\n")
            md.append("|------|------|------|------|------|------|\n")
            for item in dep_items:
                no = item.get("trainNo", item.get("flightNo", "-"))
                dep_time = item.get("departTime", "-")
                arr_time = item.get("arriveTime", "-")
                duration = item.get("duration", "-")
                price = item.get("price", "-")
                book_url = item.get("detailUrl", "")
                if book_url:
                    link = "[点击预订]({})".format(book_url)
                else:
                    link = "-"
                md.append("| {} | {} | {} | {} | ¥{} | {} |\n".format(
                    no, dep_time, arr_time, duration, price, link
                ))
        else:
            md.append("*当前 flyai 仅支持查询一周内车票/机票，远期日期无实时数据，请点击下方链接官网查询*\n")
            if transport_type == "train":
                md.append("- [12306 官网查询预订](https://www.12306.cn/)\n")
            else:
                md.append("- [携程机票查询](https://flights.ctrip.com/)\n")
                md.append("- [飞猪机票查询](https://www.fliggy.com/flight/)\n")
        md.append("")

        md.append("### 返程: {} → {} ({})\n".format(destination, origin, end_date))
        ret_has_items = False
        ret_items = []
        if ret_data and isinstance(ret_data.get("data"), dict) and ret_data["data"].get("itemList"):
            ret_has_items = True
            ret_items = ret_data["data"]["itemList"][:5]
        if ret_has_items and len(ret_items) > 0:
            md.append("| 车次/航班 | 出发 | 到达 | 历时 | 价格 | 预订 |\n")
            md.append("|------|------|------|------|------|------|\n")
            for item in ret_items:
                no = item.get("trainNo", item.get("flightNo", "-"))
                dep_time = item.get("departTime", "-")
                arr_time = item.get("arriveTime", "-")
                duration = item.get("duration", "-")
                price = item.get("price", "-")
                book_url = item.get("detailUrl", "")
                if book_url:
                    link = "[点击预订]({})".format(book_url)
                else:
                    link = "-"
                md.append("| {} | {} | {} | {} | ¥{} | {} |\n".format(
                    no, dep_time, arr_time, duration, price, link
                ))
        else:
            md.append("*当前 flyai 仅支持查询一周内车票/机票，远期日期无实时数据，请点击下方链接官网查询*\n")
            if transport_type == "train":
                md.append("- [12306 官网查询预订](https://www.12306.cn/)\n")
            else:
                md.append("- [携程机票查询](https://flights.ctrip.com/)\n")
                md.append("- [飞猪机票查询](https://www.fliggy.com/flight/)\n")
        md.append("")

        # 酒店信息
        md.append("## 🏨 会议酒店\n")
        md.append(f"**会议地点**: {meeting_location}\n\n")

        hotel_has_items = False
        hotel_items = []
        if hotel_data and isinstance(hotel_data.get("data"), dict) and hotel_data["data"].get("itemList"):
            hotel_has_items = True
            hotel_items = hotel_data["data"]["itemList"]
        if hotel_has_items and len(hotel_items) > 0:
            for hotel in hotel_items:
                h_name = hotel.get("name", meeting_location)
                price = hotel.get("price", "-")
                star = hotel.get("star", "-")
                address = hotel.get("address", "-")
                detail_url = hotel.get("detailUrl", "")

                md.append(f"### {h_name}\n")
                md.append(f"- **星级**: {star}\n")
                md.append(f"- **地址**: {address}\n")
                md.append(f"- **飞猪参考价格**: ¥{price} (一晚)\n")
                md.append(f"- **预订渠道**:\n")
                md.append(self.generate_booking_links_markdown(h_name, destination, start_date, end_date, is_delonix_hotel))
                if detail_url:
                    md.append(f"\n- **飞猪详情**: [飞猪查看]({detail_url})\n")
                md.append("")
        else:
            # flyai 无数据，提供多平台搜索链接
            md.append(f"- **酒店名称**: {meeting_location}\n")
            md.append(f"- **所在城市**: {destination}\n")
            md.append(f"- **预订渠道**:\n")
            md.append(self.generate_booking_links_markdown(meeting_location, destination, start_date, end_date, is_delonix_hotel))
            md.append("")

        # 预算明细
        md.append("## 💰 预算估算\n")
        md.append(f"**预算档次**: {budget['budget_name']}\n\n")
        md.append("| 项目 | 最低预算 | 最高预算 |\n")
        md.append("|------|---------:|---------:|\n")
        for item in budget["breakdown"]:
            if item["min"] == item["max"]:
                md.append(f"| {item['item']} | ¥{item['min']} | ¥{item['max']} |\n")
            else:
                md.append(f"| {item['item']} | ¥{item['min']} | ¥{item['max']} |\n")
        md.append(f"| **总计** | **¥{budget['total_min']}** | **¥{budget['total_max']}** |\n")
        md.append("\n*注：估算基于标准差旅预算，实际价格以实时查询为准*\n")
        md.append("")

        # 目的地攻略
        md.append("## 📖 目的地攻略\n")
        md.append(f"- **天气**: 建议出行前查看最新天气预报\n")
        md.append(f"- **穿搭**: 根据季节准备衣物，会议建议正装\n")
        md.append(f"- **美食**: 可搜索当地特色美食，推荐询问酒店前台\n")
        md.append(f"- **景点**: 会议之余可安排周边景点游览\n")
        md.append("")

        # 出行清单
        md.append("## 📋 出行清单\n")
        md.append("- [ ] 身份证 / 电子证件\n")
        md.append("- [ ] 手机 + 充电器 + 充电宝\n")
        md.append("- [ ] 会议材料 / 名片\n")
        md.append("- [ ] 正装（会议用）\n")
        md.append("- [ ] 随身衣物\n")
        md.append("- [ ] 口罩 / 常用药品\n")
        md.append("- [ ] 雨伞 / 雨具（根据天气）\n")
        md.append("")

        # 注意事项
        md.append("## 📝 注意事项\n")
        md.append("1. 所有交通/酒店价格均来自飞猪 flyai 实时查询，仅供参考\n")
        md.append("2. 点击预订链接可直接跳转对应平台完成预订\n")
        md.append("3. 远期日期（超过一周）flyai 无实时数据，请至对应官网查询\n")
        md.append("4. 德胧集团旗下酒店优先推荐百达屋App预订，享受会员权益\n")
        md.append("5. 数据缓存 24 小时，如需刷新请加 --force-refresh 参数重新生成\n")
        md.append("")

        md.append("---\n")
        md.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        md.append("")
        md.append("*工具: Universal Travel Planner Skill v2.0 · OpenClaw*")

        return "\n".join(md)

    def generate_html(self,
                    markdown: str,
                    name: str,
                    start_date: str,
                    end_date: str,
                    origin: str,
                    destination: str) -> str:
        """生成精美HTML报告"""

        # 简单转换markdown到HTML（关键部分转换）
        # 完整CSS参考universal-travel-planner的设计

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{origin}→{destination} 出行规划 · {start_date}</title>
    <style>
        :root {{
            --primary: #1a1a2e;
            --accent: #e94560;
            --success: #16a34a;
            --warning: #f59e0b;
            --info: #3b82f6;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #334155;
            --text-light: #64748b;
            --border: #e2e8f0;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }}
        .hero {{
            background: linear-gradient(135deg, var(--primary) 0%, #16213e 100%);
            color: white;
            padding: 40px 20px;
            border-radius: 12px;
            margin-bottom: 30px;
        }}
        .hero h1 {{
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        .hero .subtitle {{
            opacity: 0.9;
            font-size: 1.1rem;
        }}
        .card {{
            background: var(--card);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .card h2 {{
            color: var(--primary);
            margin-bottom: 16px;
            font-size: 1.5rem;
            border-bottom: 2px solid var(--border);
            padding-bottom: 8px;
        }}
        .card h3 {{
            color: var(--primary);
            margin: 16px 0 12px 0;
            font-size: 1.25rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
        }}
        th, td {{
            border: 1px solid var(--border);
            padding: 12px;
            text-align: left;
        }}
        th {{
            background-color: var(--bg);
            font-weight: 600;
        }}
        a {{
            color: var(--info);
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .btn {{
            display: inline-block;
            padding: 8px 16px;
            background-color: var(--bg);
            color: var(--primary);
            border-radius: 6px;
            margin-right: 8px;
            margin-bottom: 8px;
            border: 1px solid var(--border);
            transition: all 0.2s;
        }}
        .btn:hover {{
            background-color: var(--border);
            text-decoration: none;
        }}
        .btn-primary {{
            background-color: var(--accent);
            color: white;
            border-color: var(--accent);
        }}
        .btn-primary:hover {{
            background-color: #d63853;
        }}
        .check-item {{
            margin: 8px 0;
        }}
        footer {{
            text-align: center;
            color: var(--text-light);
            padding: 30px 0;
            font-size: 0.9rem;
        }}
        @media (max-width: 768px) {{
            .container {{
                padding: 10px;
            }}
            .hero {{
                padding: 30px 15px;
            }}
            .hero h1 {{
                font-size: 1.5rem;
            }}
            table {{
                font-size: 0.85rem;
            }}
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="hero">
        <h1>🧳 {name} · 出行规划</h1>
        <div class="subtitle">{origin} → {destination} &nbsp;&nbsp; {start_date} ~ {end_date}</div>
    </div>
"""

        # 将markdown转换为HTML（简易转换）
        in_table = False
        lines = markdown.split('\n')
        for line in lines:
            if line.startswith('# '):
                # h1 在hero里了，跳过
                continue
            elif line.startswith('## '):
                if in_table:
                    html += '</table>\n'
                    in_table = False
                title = line[3:]
                html += f'    <div class="card">\n        <h2>{title}</h2>\n'
            elif line.startswith('### '):
                title = line[4:]
                html += f'        <h3>{title}</h3>\n'
            elif line.startswith('| '):
                if not in_table:
                    html += '        <table>\n'
                    in_table = True
                cells = [cell.strip() for cell in line.split('|')[1:-1]]
                html += '            <tr>\n'
                for cell in cells:
                    # 转换链接
                    cell = self._convert_md_link_to_html(cell)
                    html += f'                <td>{cell}</td>\n'
                html += '            </tr>\n'
            elif line.startswith('- [ ] '):
                item = line[6:]
                html += f'        <div class="check-item">☐ {item}</div>\n'
            elif line.startswith('- [x] '):
                item = line[6:]
                html += f'        <div class="check-item">✅ {item}</div>\n'
            elif line.startswith('- '):
                item = line[2:]
                # 检查是否是链接
                item = self._convert_md_link_to_html(item)
                html += f'        <div>• {item}</div>\n'
            elif line.startswith('---'):
                if in_table:
                    html += '</table>\n'
                    in_table = False
                html += '    </div>\n'  # close card
            elif line.strip() == '':
                continue
            else:
                if in_table and line.strip() == '':
                    html += '</table>\n'
                    in_table = False
                line = self._convert_md_link_to_html(line)
                html += f'        <p>{line}</p>\n'

        if in_table:
            html += '</table>\n'

        html += f"""
    <footer>
        生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} <br>
        Universal Travel Planner Skill v2.0 · OpenClaw
    </footer>
</div>
</body>
</html>
"""

        return html

    def _convert_md_link_to_html(self, text: str) -> str:
        """转换markdown链接 [text](url) → <a href="url" target="_blank">text</a>"""
        import re
        pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        return re.sub(pattern, r'<a href="\2" target="_blank">\1</a>', text)

    def save_output(self, markdown: str, html: str, output_dir: str, base_name: str = "travel-plan"):
        """保存输出文件"""
        os.makedirs(output_dir, exist_ok=True)

        md_path = os.path.join(output_dir, f"{base_name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        log_ok(f"Markdown 已保存: {md_path}")

        html_path = os.path.join(output_dir, f"{base_name}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        log_ok(f"HTML 已保存: {html_path}")

def main():
    parser = argparse.ArgumentParser(description="Universal Travel Planner v2.0")
    parser.add_argument("--name", required=True, help="出行人姓名")
    parser.add_argument("--start-date", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--origin", required=True, help="出发地（用户所在地）")
    parser.add_argument("--destination", required=True, help="目的地")
    parser.add_argument("--meeting-location", required=True, help="会议/活动地点（酒店名称）")
    parser.add_argument("--meeting-date", help="会议日期 YYYY-MM-DD")
    parser.add_argument("--budget", default="comfort", choices=["economy", "comfort", "business"], help="预算档次")
    parser.add_argument("--passengers", type=int, default=1, help="出行人数")
    parser.add_argument("--rooms", type=int, default=1, help="预订房间数")
    parser.add_argument("--transport-preference", default="any", choices=["any", "train", "flight"], help="交通偏好")
    parser.add_argument("--is-delonix-hotel", action="store_true", help="是否德胧集团旗下酒店（优先推荐百达屋）")
    parser.add_argument("--output", default="output/travel-plan", help="输出目录")
    parser.add_argument("--force-refresh", action="store_true", help="强制刷新缓存")
    args = parser.parse_args()

    generator = TravelPlanGeneratorV2(cache_dir="./cache/travel")

    markdown = generator.generate_markdown(
        name=args.name,
        start_date=args.start_date,
        end_date=args.end_date,
        origin=args.origin,
        destination=args.destination,
        meeting_location=args.meeting_location,
        meeting_date=args.meeting_date,
        budget_level=args.budget,
        passengers=args.passengers,
        rooms=args.rooms,
        transport_preference=args.transport_preference,
        is_delonix_hotel=args.is_delonix_hotel,
    )

    html = generator.generate_html(
        markdown=markdown,
        name=args.name,
        start_date=args.start_date,
        end_date=args.end_date,
        origin=args.origin,
        destination=args.destination
    )

    generator.save_output(markdown, html, args.output)
    log_ok(f"\n✅ 出行规划生成完成！输出目录: {args.output}")
    log_ok(f"   Markdown: {os.path.join(args.output, 'travel-plan.md')}")
    log_ok(f"   HTML: {os.path.join(args.output, 'travel-plan.html')}")

if __name__ == "__main__":
    main()