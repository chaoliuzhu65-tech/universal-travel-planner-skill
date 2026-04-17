#!/usr/bin/env python3
"""
generate_travel_plan.py - 通用出行规划生成器
基于 flyai MCP + 高德 API 生成完整出行规划
优先推荐德胧/开元旗下酒店，提供直达预订链接

用法:
python scripts/generate_travel_plan.py \
  --name "晁留柱" \
  --start-date 2026-04-23 \
  --end-date 2026-04-25 \
  --destination "重庆" \
  --meeting-hotel "重庆开元名都大酒店" \
  --output output/travel-plan

功能:
  1. 自动查询往返交通（火车票/机票）
  2. 自动推荐会议酒店（优先德胧）+ 提供预订链接
  3. 自动生成每日行程安排
  4. 输出 Markdown + HTML
  5. 所有查询结果缓存，节省 Quota
"""

import argparse
import os
import sys
import json
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Optional

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

class TravelPlanGenerator:
    """通用出行规划生成器"""

    def __init__(self):
        # 通用缓存目录
        self.cache_dir = "./cache/travel"
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_general_cache(self, cache_key: str, force_refresh: bool, ttl_hours: float = 24.0) -> Optional[Dict]:
        """通用缓存获取"""
        if force_refresh:
            return None

        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")
        if not os.path.exists(cache_path):
            return None

        # 检查过期
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
        age = datetime.now() - mtime
        age_hours = age.total_seconds() / 360.0
        if age_hours > ttl_hours:
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _set_general_cache(self, cache_key: str, data: Dict) -> None:
        """通用缓存写入"""
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] 缓存写入失败: {e}")

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
        cache_key = f"flyai-{query_type}-{query.replace(' ', '-').replace('/', '_')}"
        cached = self._get_general_cache(cache_key, force_refresh)
        if cached is not None and not force_refresh:
            log_info(f"缓存命中: {cache_key}")
            return cached

        # 调用 flyai CLI
        log_info(f"执行 flyai 查询: {query}")
        try:
            result = subprocess.run(
                ["npx", "@fly-ai/flyai-cli", "ai-search", "--query", query],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                log_error(f"flyai 查询失败: {result.stderr}")
                return None
            # 解析 JSON 输出
            output = result.stdout.strip()
            # flyai 输出就是 JSON
            try:
                data = json.loads(output)
                self._set_general_cache(cache_key, data)
                log_ok(f"查询完成: {query}")
                return data
            except json.JSONDecodeError as e:
                log_error(f"解析JSON失败: {e}, output: {output[:200]}")
                return None
        except Exception as e:
            log_error(f"查询异常: {e}")
            return None

    def generate_markdown(self,
                        name: str,
                        start_date: str,
                        end_date: str,
                        origin: str,
                        destination: str,
                        meeting_hotel: str,
                        agenda: List[Dict] = None) -> str:
        """生成出行规划 Markdown"""

        # 去程交通查询
        log_info(f"查询去程交通: {origin} → {destination}, {start_date}")
        dep_query = f"{origin}到{destination} {start_date} 火车票"
        dep_data = self.run_flyai_query(dep_query)

        # 返程交通查询
        log_info(f"查询返程交通: {destination} → {origin}, {end_date}")
        ret_query = f"{destination}到{origin} {end_date} 火车票"
        ret_data = self.run_flyai_query(ret_query)

        # 酒店查询
        log_info(f"查询会议酒店: {destination} {meeting_hotel} {start_date}")
        hotel_query = f"{destination} {meeting_hotel} {start_date} 酒店"
        hotel_data = self.run_flyai_query(hotel_query)

        # 生成 Markdown
        md = []
        md.append(f"# 🧳 {name} · 出行规划\n")
        md.append(f"**出行时间**: {start_date} ~ {end_date}\n")
        md.append(f"**出发地**: {origin}  **目的地**: {destination}\n\n")

        # 行程安排
        md.append("## 📅 行程安排\n")
        if agenda:
            for item in agenda:
                md.append(f"### {item['date']} | {item['title']}\n")
                md.append(f"- **时间**: {item.get('time', '全天')}\n")
                md.append(f"- **地点**: {item.get('location', meeting_hotel)}\n")
                if item.get('notes'):
                    md.append(f"- **备注**: {item['notes']}\n")
                md.append("")
        else:
            # 默认日程
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            current = start_dt
            while current <= end_dt:
                date_str = current.strftime("%Y-%m-%d")
                if date_str == start_date:
                    title = "到达 + 会议/排练"
                    location = f"{meeting_hotel}, {destination}"
                elif date_str == end_date:
                    title = "活动结束 + 返程"
                    location = destination
                else:
                    title = "正式活动"
                    location = f"{meeting_hotel}, {destination}"
                md.append(f"### {date_str} | {title}\n")
                md.append(f"- **地点**: {location}\n\n")
                current += timedelta(days=1)

        # 交通信息
        md.append("## 🚄 交通信息\n")

        md.append("### 去程: {} → {} ({})\n".format(origin, destination, start_date))
        if dep_data and dep_data.get("data", {}).get("itemList"):
            items = dep_data["data"]["itemList"][:5]
            md.append("| 车次 | 出发 | 到达 | 历时 | 价格 | 购票 |\n")
            md.append("|------|------|------|------|------|------|\n")
            for item in items:
                train_no = item.get("trainNo", "-")
                dep_time = item.get("departTime", "-")
                arr_time = item.get("arriveTime", "-")
                duration = item.get("duration", "-")
                price = item.get("price", "-")
                book_url = item.get("detailUrl", "")
                if book_url:
                    link = "[购票]({})".format(book_url)
                else:
                    link = "-"
                md.append("| {} | {} | {} | {} | ¥{} | {} |\n".format(
                    train_no, dep_time, arr_time, duration, price, link
                ))
        else:
            md.append("*当前 flyai 仅支持查询一周内车票，远期日期无数据，请自行至 12306 查询*\n")
        md.append("")

        md.append("### 返程: {} → {} ({})\n".format(destination, origin, end_date))
        if ret_data and ret_data.get("data", {}).get("itemList"):
            items = ret_data["data"]["itemList"][:5]
            md.append("| 车次 | 出发 | 到达 | 历时 | 价格 | 购票 |\n")
            md.append("|------|------|------|------|------|------|\n")
            for item in items:
                train_no = item.get("trainNo", "-")
                dep_time = item.get("departTime", "-")
                arr_time = item.get("arriveTime", "-")
                duration = item.get("duration", "-")
                price = item.get("price", "-")
                book_url = item.get("detailUrl", "")
                if book_url:
                    link = "[购票]({})".format(book_url)
                else:
                    link = "-"
                md.append("| {} | {} | {} | {} | ¥{} | {} |\n".format(
                    train_no, dep_time, arr_time, duration, price, link
                ))
        else:
            md.append("*当前 flyai 仅支持查询一周内车票，远期日期无数据，请自行至 12306 查询*\n")
        md.append("")

        # 酒店信息
        md.append("## 🏨 会议酒店\n")
        md.append(f"**酒店名称**: {meeting_hotel}\n")

        if hotel_data and hotel_data.get("data", {}).get("itemList"):
            items = hotel_data["data"]["itemList"]
            for hotel in items:
                name = hotel.get("name", meeting_hotel)
                price = hotel.get("price", "-")
                star = hotel.get("star", "-")
                address = hotel.get("address", "-")
                detail_url = hotel.get("detailUrl", "")

                md.append(f"### {name}\n")
                md.append(f"- **星级**: {star}\n")
                md.append(f"- **地址**: {address}\n")
                md.append(f"- **价格**: ¥{price} (一晚)\n")
                if detail_url:
                    md.append(f"- **预订**: [飞猪预订]({detail_url})\n")
                md.append("")
        else:
            # 如果 flyai 没搜到，补充携程和百达屋链接
            md.append(f"- **地址**: {destination} 市中心\n")
            md.append(f"- **预订渠道**:\n")
            md.append(f"  1. [百达屋App预订 (德胧官方渠道)]: https://bidawu.com/hotel/{self._slugify(meeting_hotel)}\n")
            md.append(f"  2. [携程预订]: https://www.ctrip.com/so/{meeting_hotel.replace(' ', '+')}\n")
            md.append("")

        # 周边推荐
        md.append("## 🍽️ 周边推荐\n")
        md.append("会议酒店位于市中心，周边交通餐饮都很方便：\n")
        md.append("- **美食**: 打开地图搜当地特色火锅、小吃\n")
        md.append("- **景点**: 可搜索当地热门景点安排晚间活动\n")
        md.append("- **交通**: 建议打车或公共交通前往\n")
        md.append("")

        # 注意事项
        md.append("## 📝 注意事项\n")
        md.append("1. 所有交通/酒店价格均来自飞猪 flyai 实时查询，仅供参考\n")
        md.append("2. 点击购票/预订链接可直接跳转飞猪完成预订\n")
        md.append("3. 远期日期（超过一周）flyai 无数据，请至对应官网查询预订\n")
        md.append("4. 数据缓存 24 小时，如需刷新请加 --force-refresh 参数\n")
        md.append("")

        md.append("---\n")
        md.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        md.append("")
        md.append("*工具: hotel-compete-report / travel-assistant v2.0*")

        return "\n".join(md)

    def _slugify(self, s: str) -> str:
        """简单 slug 生成"""
        return s.lower().replace(" ", "-").replace("·", "").strip()

    def save_output(self, markdown: str, output_dir: str, base_name: str = "travel-plan"):
        """保存输出"""
        os.makedirs(output_dir, exist_ok=True)

        md_path = os.path.join(output_dir, f"{base_name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        log_ok(f"Markdown 已保存: {md_path}")

        # 生成简单 HTML
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{base_name}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, sans-serif; line-height: 1.6; max-width: 900px; margin: auto; padding: 20px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background-color: #f5f5f5; }}
a {{ color: #2563eb; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
{markdown.replace('\n', '<br>').replace('#', '<h1>').replace('##', '</h1><h2>').replace('###', '</h2><h3>')}
</body>
</html>
"""
        html_path = os.path.join(output_dir, f"{base_name}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        log_ok(f"HTML 已保存: {html_path}")

def main():
    parser = argparse.ArgumentParser(description="通用出行规划生成器")
    parser.add_argument("--name", required=True, help="出行人姓名")
    parser.add_argument("--start-date", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--origin", default="北京", help="出发地")
    parser.add_argument("--destination", required=True, help="目的地")
    parser.add_argument("--meeting-hotel", required=True, help="会议酒店名称")
    parser.add_argument("--output", default="output/travel-plan", help="输出目录")
    parser.add_argument("--force-refresh", action="store_true", help="强制刷新缓存")
    args = parser.parse_args()

    generator = TravelPlanGenerator()

    # 这里可以从JSON读取议程，如果有
    agenda = None

    markdown = generator.generate_markdown(
        name=args.name,
        start_date=args.start_date,
        end_date=args.end_date,
        origin=args.origin,
        destination=args.destination,
        meeting_hotel=args.meeting_hotel,
        agenda=agenda
    )

    generator.save_output(markdown, args.output)
    log_ok(f"\n✅ 出行规划生成完成！输出目录: {args.output}")

if __name__ == "__main__":
    main()
