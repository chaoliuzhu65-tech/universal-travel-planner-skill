#!/usr/bin/env python3
"""
generate_single_report.py - 生成单家酒店报告（按日期存档，支持日常监测）
用法:
python scripts/generate_single_report.py \
  --name "天津瑞湾开元名都大酒店" \
  --brand "开元名都" \
  --star "五星级/豪华型" \
  --weekday-price 443 \
  --target-date 2026-05-01 \
  --lat 39.000893 \
  --lon 117.710212 \
  --district "天津市滨海新区" \
  --output output \
  --api-key YOUR_AMAP_KEY

说明:
- 按酒店分目录存档，每个日期生成独立文件
- 保留历史版本方便对比价格变化
- latest 链接指向最新版本
- 适配日常每日监测使用场景
"""

import os
import json
import argparse
from datetime import datetime
from typing import Dict

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.amap_client import AmapClientWrapper as AmapClient
from core.competitor_filter_v2 import HotelPOI, filter_competitors_grouped, GroupedCompetitors
from algorithm.pricing_advisor import PricingAdvisor, CompetitorData, DemandLevel, PricingRecommendation
from scripts.generate_batch_reports import ReportGenerator  # 复用渲染逻辑


def main():
    parser = argparse.ArgumentParser(description="生成单家酒店报告（按日期存档）")
    parser.add_argument("--name", "-n", required=True, help="酒店名称")
    parser.add_argument("--brand", "-b", required=True, help="品牌")
    parser.add_argument("--star", "-s", required=True, help="星级")
    parser.add_argument("--weekday-price", "-p", required=True, type=int, help="平日基准价")
    parser.add_argument("--target-date", "-d", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--lat", required=True, type=float, help="纬度")
    parser.add_argument("--lon", required=True, type=float, help="经度")
    parser.add_argument("--district", required=False, default="", help="区域")
    parser.add_argument("--max-distance", "-m", type=float, default=5.0, help="最大搜索半径 km")
    parser.add_argument("--scenario", "-c", default="default", help="场景 downtown/resort/price_battle")
    parser.add_argument("--output", "-o", required=True, help="输出根目录")
    parser.add_argument("--api-key", "-k", required=True, help="高德地图API Key")
    args = parser.parse_args()

    # 构造酒店信息
    hotel_info = {
        "name": args.name,
        "brand": args.brand,
        "star": args.star,
        "weekday_price": args.weekday_price,
        "target_date": args.target_date,
        "lat": args.lat,
        "lon": args.lon,
        "district": args.district,
        "max_distance_km": args.max_distance,
        "scenario": args.scenario,
    }

    # 创建输出目录: output/{hotel-slug}/
    generator = ReportGenerator(args.api_key)
    hotel_slug = generator._slugify(args.name)
    hotel_output_dir = os.path.join(args.output, hotel_slug)
    os.makedirs(hotel_output_dir, exist_ok=True)

    print(f"🔍 开始生成 {args.name} 报告，目标日期 {args.target_date}")
    print(f"📁 输出目录: {hotel_output_dir}")

    # ===== 复用generate_report逻辑 =====
    lat = hotel_info["lat"]
    lon = hotel_info["lon"]
    radius_km = hotel_info.get("max_distance_km", 5)
    scenario = hotel_info.get("scenario", "default")

    # 1. 高德POI搜索
    nearby_pois = generator.amap.poi_around(
        keywords="酒店",
        location=(lon, lat),
        radius_km=radius_km,
        page_size=50
    )
    # 计算距离
    nearby_hotels = []
    center_lon, center_lat = lon, lat
    for poi in nearby_pois:
        if poi.lon and poi.lat:
            from math import radians, sin, cos, sqrt, atan2
            R = 6371
            dlon = radians(poi.lon - center_lon)
            dlat = radians(poi.lat - center_lat)
            a = sin(dlat/2)**2 + cos(radians(center_lat)) * cos(radians(poi.lat)) * sin(dlon/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            distance_km = R * c
            poi.distance_km = distance_km
            nearby_hotels.append(poi)
    nearby_hotels.sort(key=lambda x: x.distance_km if x.distance_km else 999)
    print(f"   找到 {len(nearby_hotels)} 家酒店")

    # 2. 转换HotelPOI
    target = HotelPOI(
        name=hotel_info["name"],
        location=f"{lon},{lat}",
        star=hotel_info["star"],
        brand=hotel_info["brand"],
        price=hotel_info["weekday_price"]
    )

    candidates = []
    for h in nearby_hotels:
        if h.name.strip() != hotel_info["name"].strip():
            poi = HotelPOI(
                name=h.name,
                location=f"{h.lon},{h.lat}",
                star=h.type if h.type else "高档型",
                brand=generator._extract_brand(h.name),
                distance_km=h.distance_km
            )
            candidates.append(poi)
    print(f"   排除自身后剩余 {len(candidates)} 家候选")

    # 3. v2.1分组筛选
    from core.competitor_filter_v2 import get_config_for_scenario, FilterConfig
    config = get_config_for_scenario(scenario) if scenario != "default" else FilterConfig()
    grouped = filter_competitors_grouped(candidates, target, hotel_info["weekday_price"], config=config)
    filtered_scores = grouped.strong_relevant
    print(f"   筛选出 {len(filtered_scores)} 家强相关有效竞品")

    # 4. 准备竞品数据
    competitor_data = []
    for s in filtered_scores[:8]:
        est_holiday = s.hotel.price * 1.5 if s.hotel.price else hotel_info["weekday_price"] * 1.5
        cd = CompetitorData(
            name=s.hotel.name,
            base_price=s.hotel.price if s.hotel.price else hotel_info["weekday_price"],
            holiday_price=est_holiday,
            star=s.hotel.star,
            brand=s.hotel.brand,
            distance_km=s.hotel.distance_km if s.hotel.distance_km else 0
        )
        competitor_data.append(cd)

    # 5. 调价分析
    demand = DemandLevel.HIGH  # 默认节假日
    if "weekday" in args.target_date.lower():
        demand = DemandLevel.LOW
    elif "weekend" in args.target_date.lower():
        demand = DemandLevel.MEDIUM

    advisor = PricingAdvisor(
        base_price=hotel_info["weekday_price"],
        competitors=competitor_data,
        demand_level=demand,
        target_date=hotel_info["target_date"]
    )
    recommendation = advisor.analyze()

    # 6. 生成markdown 和 html
    markdown = generator._render_markdown(hotel_info, recommendation, grouped)
    html = generator._render_html(hotel_info, recommendation, grouped)

    # 7. 按日期保存
    date_str = args.target_date
    base_name = f"{hotel_slug}-{date_str}"
    md_path = os.path.join(hotel_output_dir, f"{base_name}.md")
    html_path = os.path.join(hotel_output_dir, f"{base_name}.html")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 更新latest软链接
    latest_md = os.path.join(hotel_output_dir, f"{hotel_slug}-latest.md")
    latest_html = os.path.join(hotel_output_dir, f"{hotel_slug}-latest.html")
    try:
        os.remove(latest_md) if os.path.exists(latest_md) else None
        os.remove(latest_html) if os.path.exists(latest_html) else None
        os.symlink(f"{base_name}.md", latest_md)
        os.symlink(f"{base_name}.html", latest_html)
    except Exception:
        # Windows不支持软链接，跳过
        pass

    print(f"\n✅ 报告生成完成！")
    print(f"   Markdown: {md_path}")
    print(f"   HTML: {html_path}")
    print(f"   Latest: {latest_html}")

    # 更新根索引
    update_root_index(args.output, args.name, hotel_slug, date_str, recommendation)


def update_root_index(output_root: str, hotel_name: str, hotel_slug: str, date_str: str, rec):
    """更新根目录索引"""
    index_path = os.path.join(output_root, "README.md")
    entries = []

    # 如果已有索引，读取旧内容
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            header_done = False
            for line in lines:
                if line.startswith("| "):
                    entries.append(line)
                if not header_done and "| --------" in line:
                    header_done = True

    # 新条目
    rel_path = f"{hotel_slug}/{hotel_slug}-latest.html"
    price = rec.recommended_price
    new_entry = f"| [{hotel_name}]({hotel_slug}/{hotel_slug}-{date_str}.md) | [HTML]({rel_path}) | {date_str} | ¥{price} |\n"

    # 去重（同酒店保留最新）
    entries = [e for e in entries if hotel_name not in e]
    entries.insert(0, new_entry)

    # 写入
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(f"# 酒店竞品价格监测报告\n\n")
        f.write(f"**最后更新**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## 报告列表\n\n")
        f.write("| 酒店名称 | HTML最新 | 生成日期 | 推荐价格 |\n")
        f.write("| -------- | -------- | -------- | -------- |\n")
        f.writelines(entries)


if __name__ == "__main__":
    main()
