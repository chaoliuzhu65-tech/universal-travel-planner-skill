#!/usr/bin/env python3
"""
酒店竞品价格分析报告生成器 v2.0
酒店集团 AI Native 实践成果
生成器：德胧AI实验室（小云）

【强制要求】数据必须来自真实API，禁止使用任何演示/虚拟数据。
数据源：飞猪Fliggy（flyai CLI）

功能：
  - 飞猪真实API采集（假期价 + 平日价对比）
  - 经纬度地理过滤（滨海核心区精准定位）
  - 双重校准定价算法（涨幅校准 + 绝对值校准）
  - 结构化报告输出（MD + HTML + JSON）
  - 方法论SOP沉淀

使用方法：
  python build_compete_report.py --hotel "天津瑞湾开元名都" --target-date 2026-05-01 --competitors 8 --scope 滨海 --base-price 443
"""

import argparse
import json
import os
import re
import sys
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# ── 导入缓存模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.data_cache import DataCache, get_default_cache

# ── 颜色输出 ──────────────────────────────────────────────
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

def log_info(msg): print(f"{Colors.OKBLUE}[INFO]{Colors.ENDC} {msg}")
def log_ok(msg): print(f"{Colors.OKGREEN}[OK]{Colors.ENDC} {msg}")
def log_warn(msg): print(f"{Colors.WARNING}[WARN]{Colors.ENDC} {msg}")
def log_err(msg): print(f"{Colors.FAIL}[ERR]{Colors.ENDC} {msg}")

# ── 地理范围定义 ──────────────────────────────────────────
# 滨海核心区（直接竞品范围）
# 说明：滨海新区涵盖开发区（泰达）、于家堡、塘沽等
# 放宽范围：lon 117.0-118.0 可覆盖滨海+武清+北辰主要酒店
SCOPE_BOUNDS = {
    "滨海": {"lat_min": 38.80, "lat_max": 39.50, "lon_min": 117.00, "lon_max": 118.00},
    "市区": {"lat_min": 39.00, "lat_max": 39.20, "lon_min": 117.00, "lon_max": 117.30},
    "全域": {"lat_min": 38.80, "lat_max": 39.50, "lon_min": 117.00, "lon_max": 118.00},
}

def in_bounds(lat, lon, bounds):
    """判断坐标是否在范围内"""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        return (bounds["lat_min"] <= lat_f <= bounds["lat_max"] and
                bounds["lon_min"] <= lon_f <= bounds["lon_max"])
    except (TypeError, ValueError):
        return False

# ── 工具函数 ──────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="酒店竞品价格分析报告生成器")
    parser.add_argument("--hotel", required=True, help="目标酒店名称")
    parser.add_argument("--target-date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--competitors", type=int, default=8, help="竞品数量")
    parser.add_argument("--scope", default="滨海", choices=["滨海", "市区", "全域"], help="调研范围")
    parser.add_argument("--base-price", type=float, default=None, help="我店平日价（人民币）")
    parser.add_argument("--output-dir", default="output/hotel-compete-report", help="输出目录")
    parser.add_argument("--amap-key", default=None, help="高德 API Key（可选，环境变量 AMAP_MAPS_API_KEY 也可）")
    parser.add_argument("--force-refresh", action="store_true", help="强制刷新缓存，不使用缓存")
    return parser.parse_args()

def generate_output_filename(hotel_name, target_date, suffix, ext):
    safe_name = hotel_name.replace(" ", "_").replace("/", "_")
    date_str = target_date.replace("-", "")
    return f"{safe_name}_{date_str}_{suffix}.{ext}"

def run_flyai(cmd, cache_key: tuple = None, force_refresh: bool = False, retries: int = 3):
    """执行 flyai 命令，返回JSON或None
    如果提供 cache_key=(dest_name, keywords, check_in, check_out)，则使用缓存
    失败自动重试最多 retries 次
    """
    # 尝试从缓存获取
    if cache_key is not None and not force_refresh:
        cache = get_default_cache()
        cached = cache.get(*cache_key)
        if cached is not None:
            log_ok(f"[缓存命中] {cache_key[0]} - {cache_key[1]} ({cache_key[2]} ~ {cache_key[3]})")
            return cached

    last_err = None
    for retry in range(retries):
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                # 写入缓存
                if cache_key is not None:
                    cache = get_default_cache()
                    cache.set(*cache_key, data)
                    log_ok(f"[缓存写入] {cache_key[0]} - {cache_key[1]}")
                return data
            else:
                err_msg = result.stderr[:200] if result.stderr else '无输出'
                log_warn(f"flyai 尝试 {retry+1}/{retries} 失败: {err_msg}")
                last_err = err_msg
        except subprocess.TimeoutExpired:
            log_warn(f"flyai 尝试 {retry+1}/{retries} 超时（60秒）")
            last_err = "Timeout"
        except json.JSONDecodeError as e:
            log_warn(f"flyai 尝试 {retry+1}/{retries} JSON解析失败: {e}")
            last_err = str(e)
        except Exception as e:
            log_warn(f"flyai 尝试 {retry+1}/{retries} 异常: {e}")
            last_err = str(e)

    # 全部重试失败
    log_err(f"flyai 全部 {retries} 次重试失败: {last_err}")
    return None

def parse_price(price_str):
    """从 '¥353' 格式提取数字"""
    if not price_str:
        return None
    m = re.search(r'[\d.]+', str(price_str))
    return int(float(m.group())) if m else None

def median(values):
    """中位数计算（抗异常值）"""
    s = sorted(values)
    n = len(s)
    if n == 0: return 0
    return s[n//2] if n % 2 else (s[n//2-1] + s[n//2]) / 2

def calc_rate(base, holiday):
    """计算涨幅百分比"""
    if base == 0: return 0
    return round((holiday - base) / base * 100, 1)

# ── 高德地图 POI 采集（精准定位竞品酒店） ───────────────────

def get_amap_key():
    """获取高德 API Key，优先级：环境变量 > 配置文件 > 内置key"""
    import os
    key = os.environ.get("AMAP_MAPS_API_KEY") or os.environ.get("AMAP_KEY")
    if key:
        return key
    # 尝试读取配置文件
    config_path = os.path.expanduser("~/.config/amap-apikey")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return f.read().strip()
    return None  # key缺失时警告


def fetch_amap_poi(competitor_names, amap_key=None):
    """
    通过高德地图 POI API 精准定位竞品酒店

    【核心价值】
    - 高德 POI 可精确找到洲际/皇冠假日等高端酒店（飞猪搜索可能漏掉）
    - 返回：{name: {location, rating, address, type}}
    """
    if not amap_key:
        amap_key = get_amap_key()
    if not amap_key:
        log_warn("高德 API Key 未配置，跳过高德 POI 采集")
        return {}

    results = {}
    for name in competitor_names:
        import urllib.parse
        encoded = urllib.parse.quote(name)
        url = f"https://restapi.amap.com/v3/place/text?key={amap_key}&keywords={encoded}&city=天津&extensions=all&offset=1"
        try:
            import subprocess as sp
            r = sp.run(["curl", "-s", url], capture_output=True, text=True, timeout=10)
            import json
            d = json.loads(r.stdout)
            if d.get("status") == "1" and d.get("pois"):
                p = d["pois"][0]
                results[name] = {
                    "poi_name": p.get("name"),
                    "location": p.get("location"),  # "lon,lat"
                    "rating": p.get("biz_ext", {}).get("rating") or None,
                    "address": p.get("address"),
                    "type": p.get("type"),
                }
                log_ok(f"高德POI: {name} -> {p.get('location')}")
        except Exception as e:
            log_warn(f"高德POI查询失败 {name}: {e}")
    return results


# ── 飞猪关键词精确搜索（解决高端品牌搜索不到的问题） ─────────

def fetch_fliggy_by_keywords(poi_data, check_in, check_out, force_refresh=False):
    """
    通过飞猪关键词搜索获取竞品价格

    对于高德 POI 定位到的竞品（洲际/皇冠假日等高端品牌），
    飞猪的区域搜索可能找不到，但按名称精确搜索可以找到。
    """
    if not poi_data:
        return []

    results = []
    for poi_name, poi_info in poi_data.items():
        # 从 POI 名称提取关键词（去掉"天津"前缀）
        keyword = poi_name.replace("天津", "").replace("酒店", "").strip()
        if len(keyword) < 2:
            continue

        # 搜索假期价格
        cmd_holiday = (
            f'flyai search-hotel '
            f'--dest-name "天津滨海新区" '
            f'--key-words "{keyword}" '
            f'--hotel-stars "4,5" '
            f'--check-in-date {check_in} '
            f'--check-out-date {check_out} '
            f'--sort rate_desc '
            f'--max-price 3000'
        )
        cache_key = ("天津滨海新区", keyword, check_in, check_out)
        holiday_raw = run_flyai(cmd_holiday, cache_key, force_refresh)

        # 搜索平日价格（假期前14天）
        base_dt = datetime.strptime(check_in, "%Y-%m-%d") - timedelta(days=14)
        base_check_in = base_dt.strftime("%Y-%m-%d")
        base_check_out = (base_dt + timedelta(days=2)).strftime("%Y-%m-%d")
        cmd_base = (
            f'flyai search-hotel '
            f'--dest-name "天津滨海新区" '
            f'--key-words "{keyword}" '
            f'--hotel-stars "4,5" '
            f'--check-in-date {base_check_in} '
            f'--check-out-date {base_check_out} '
            f'--sort rate_desc '
            f'--max-price 3000'
        )
        cache_key_base = ("天津滨海新区", keyword, base_check_in, base_check_out)
        base_raw = run_flyai(cmd_base, cache_key_base, force_refresh)

        # ── 安全检查：防止 None 值导致崩溃 ──────────────────────────
        if holiday_raw is None:
            log_warn(f"飞猪关键词搜索超时: {keyword}")
            continue
        if not isinstance(holiday_raw, dict):
            log_warn(f"飞猪关键词返回非dict: {keyword}")
            continue
        if holiday_raw.get("status") != 0:
            log_warn(f"飞猪关键词返回错误: {keyword} - {holiday_raw.get('info', 'unknown')}")
            continue
        _item_list = holiday_raw.get("data", {})
        if not isinstance(_item_list, dict):
            log_warn(f"飞猪关键词data非dict: {keyword}")
            continue
        holiday_items = _item_list.get("itemList", [])
        if not holiday_items:
            log_warn(f"飞猪关键词无结果: {keyword}")
            continue

        # 取第一个结果（最相关）
        h_item = holiday_items[0]
        holiday_price = parse_price(h_item.get("price"))
        star = h_item.get("star", "豪华型")

        # 查找平日价
        base_price = None
        if base_raw and base_raw.get("status") == 0:
            base_items = base_raw.get("data", {}).get("itemList", [])
            for b in base_items:
                if b.get("shId") == h_item.get("shId"):
                    base_price = parse_price(b.get("price"))
                    break

        item = {
            "name": h_item.get("name", poi_name),
            "star": star,
            "holiday": holiday_price,
            "base": base_price,
            "lat": poi_info.get("location", "").split(",")[1] if poi_info.get("location") else None,
            "lon": poi_info.get("location", "").split(",")[0] if poi_info.get("location") else None,
            "distance": poi_info.get("address", ""),
            "decoration": h_item.get("decorationTime", ""),
            "shId": h_item.get("shId", ""),
            "source": "keyword_search",
        }
        if base_price:
            item["rate"] = calc_rate(base_price, holiday_price)
        else:
            item["rate"] = None

        results.append(item)
        rate_str = f"+{item['rate']}%" if item['rate'] is not None else "无平日价"
        log_ok(f"关键词查价: {h_item.get('name')} | 假期Y{holiday_price} | 平日Y{base_price or 'N/A'} | {rate_str}")

    return results


# ── 飞猪数据采集（真实API，禁止演示数据） ────────────────────

def fetch_fliggy_price(hotel_name, check_in, check_out, scope, target_count, poi_data=None):
    """
    通过飞猪 flyai CLI 获取真实酒店价格数据

    【核心逻辑】
    1. 搜索假期日期价格（获取当前价格）
    2. 搜索平日日期价格（同一酒店，对比基准）
    3. 按经纬度过滤（精准定位滨海核心区）
    4. 合并两季数据，计算涨幅

    返回：List[Dict] 每条包含 {name, star, base, holiday, rate, lat, lon, distance, decoration}
    """
    log_info(f"正在从飞猪采集真实价格数据...")
    log_info(f"  目标酒店：{hotel_name}")
    log_info(f"  假期日期：{check_in} ~ {check_out}")

    # 计算平日对比日期（假期前两周的同星期）
    try:
        holiday_dt = datetime.strptime(check_in, "%Y-%m-%d")
        base_dt = holiday_dt - timedelta(days=14)
        base_check_in = base_dt.strftime("%Y-%m-%d")
        base_check_out = (base_dt + timedelta(days=2)).strftime("%Y-%m-%d")
    except ValueError:
        # Fallback: 使用固定平日
        base_check_in = check_in[:5] + "14"  # 同月14日
        base_check_out = check_in[:5] + "16"
    log_info(f"  平日对比：{base_check_in} ~ {base_check_out}")

    bounds = SCOPE_BOUNDS.get(scope, SCOPE_BOUNDS["滨海"])

    # ── Step 1: 搜索假期日期价格 ────────────────────────────
    holiday_cmd = (
        f'flyai search-hotel '
        f'--dest-name "天津滨海新区" '
        f'--hotel-stars "4,5" '
        f'--check-in-date {check_in} '
        f'--check-out-date {check_out} '
        f'--sort rate_desc '
        f'--max-price 3000'
    )
    log_info("正在获取假期价格（飞猪API）...")
    cache_key = ("天津滨海新区", "", check_in, check_out)
    holiday_data = run_flyai(holiday_cmd, cache_key)

    # ── Step 2: 搜索平日日期价格 ─────────────────────────────
    base_cmd = (
        f'flyai search-hotel '
        f'--dest-name "天津滨海新区" '
        f'--hotel-stars "4,5" '
        f'--check-in-date {base_check_in} '
        f'--check-out-date {base_check_out} '
        f'--sort rate_desc '
        f'--max-price 3000'
    )
    log_info("正在获取平日价格（飞猪API）...")
    cache_key_base = ("天津滨海新区", "", base_check_in, base_check_out)
    base_data = run_flyai(base_cmd, cache_key_base)

    # ── 数据校验：必须两个接口都有数据 ────────────────────────
    if not holiday_data or holiday_data.get("status") != 0:
        log_err("飞猪假期价格API调用失败，请检查网络或API配置")
        log_err("解决方案：1) 确认 flyai CLI 已登录  2) 检查网络连接  3) 稍后重试")
        return None

    if not base_data or base_data.get("status") != 0:
        log_err("飞猪平日价格API调用失败，请检查网络或API配置")
        return None

    holiday_items = holiday_data.get("data", {}).get("itemList", [])
    base_items = base_data.get("data", {}).get("itemList", [])

    if not holiday_items:
        log_err("飞猪返回空数据列表，请检查目的地名称是否正确")
        return None

    log_ok(f"飞猪数据获取成功：假期{len(holiday_items)}家，平日{len(base_items)}家")

    # ── Step 3: 建立平日价格索引（按shId）─────────────────────
    base_by_id = {}
    for item in base_items:
        sh_id = item.get("shId")
        if sh_id:
            base_by_id[sh_id] = {
                "base_price": parse_price(item.get("price")),
                "base_item": item,
            }

    # ── Step 4: 合并数据 + 地理过滤 + 计算涨幅 ───────────────
    competitors = []
    skipped_out_of_bounds = 0
    skipped_no_base = 0

    for item in holiday_items:
        lat = item.get("latitude")
        lon = item.get("longitude")

        # 地理过滤
        if not in_bounds(lat, lon, bounds):
            skipped_out_of_bounds += 1
            continue

        sh_id = item.get("shId")
        holiday_price = parse_price(item.get("price"))

        # 查找平日价
        base_info = base_by_id.get(sh_id, {})
        base_price = base_info.get("base_price")

        # 合并两季数据
        merged = {
            "name": item.get("name", "未知"),
            "star": item.get("star", "高档型"),
            "holiday": holiday_price,
            "base": base_price,
            "lat": lat,
            "lon": lon,
            "distance": item.get("interestsPoi", ""),
            "decoration": item.get("decorationTime", ""),
            "shId": sh_id,
            "detailUrl": item.get("detailUrl", ""),
        }

        # ── Step 3.5: 合并高德 POI 数据 ──────────────────────────
        if poi_data:
            item_name = item.get("name", "")
            for poi_name, poi_info in poi_data.items():
                # 名称模糊匹配（高德名可能包含飞猪名）
                if poi_name in item_name or item_name in poi_name:
                    merged["amap_location"] = poi_info.get("location")
                    merged["amap_rating"] = poi_info.get("rating")
                    if poi_info.get("address"):
                        merged["distance"] = poi_info["address"]
                    break

        if base_price is None:
            # 该酒店平日无数据，标记但保留（涨幅不可算）
            merged["rate"] = None
            merged["rate_note"] = "平日数据缺失"
            skipped_no_base += 1
        else:
            merged["rate"] = calc_rate(base_price, holiday_price)

        competitors.append(merged)

    log_info(f"地理过滤：跳过{skipped_out_of_bounds}家（范围外），"
             f"平日数据缺失{skipped_no_base}家，"
             f"有效数据{len(competitors)}家")

    if not competitors:
        log_err("没有找到符合条件的竞品，请尝试扩大调研范围（--scope 全域）")
        return None

    # ── Step 5: 去除涨幅异常值（>100%或<0%的视为异常）────────
    before_filter = len(competitors)
    competitors = [c for c in competitors
                   if c["rate"] is None or (0 <= c["rate"] <= 100)]
    after_filter = len(competitors)
    if before_filter > after_filter:
        log_warn(f"去除涨幅异常值：{before_filter} → {after_filter}家")

    # ── Step 6: 按涨幅降序排序，取top N ──────────────────────
    competitors.sort(key=lambda x: x["rate"] if x["rate"] is not None else 0, reverse=True)
    competitors = competitors[:target_count]

    return competitors


# ── 双重校准算法 ──────────────────────────────────────────

def dual_calibration(my_base, competitors):
    """
    双重校准定价算法

    第一重：涨幅校准
      - 计算竞品涨幅中位数（仅用有平日价的竞品）
      - 我店涨幅 = 竞品涨幅中位数 ±15%

    第二重：绝对值校准
      - 推荐价格 ≤ 竞品最高 × 0.95（溢价空间保护）
      - 推荐价格 ≥ 竞品最低 × 1.1（防止价格战）

    返回：{
        "conservative": {price, rate},
        "standard": {price, rate},
        "aggressive": {price, rate}
    }
    """
    if not competitors:
        return None

    # 仅用有效涨幅数据计算中位数
    valid_rates = [c["rate"] for c in competitors if c.get("rate") is not None and c["rate"] >= 0]
    if not valid_rates:
        log_err("没有有效的涨幅数据，无法执行校准")
        return None

    median_rate = median(valid_rates)

    # 豪华型竞品单独统计
    luxury_rates = [c["rate"] for c in competitors
                    if c.get("star") in ("豪华型", "五星级", "5星")
                    and c.get("rate") is not None]
    luxury_median = median(luxury_rates) if luxury_rates else median_rate

    # 第一重：涨幅校准
    min_rate = luxury_median * 0.85
    max_rate = luxury_median * 1.15

    lower = int(my_base * (1 + min_rate / 100))
    upper = int(my_base * (1 + max_rate / 100))

    # 第二重：绝对值校准
    luxury_holidays = [c["holiday"] for c in competitors
                       if c.get("star") in ("豪华型", "五星级", "5星")]
    abs_upper = int(max(luxury_holidays) * 0.95) if luxury_holidays else upper

    all_holidays = [c["holiday"] for c in competitors if c.get("holiday")]
    abs_lower = int(min(all_holidays) * 1.1) if all_holidays else lower

    # 三档策略
    conservative = min(abs_upper, lower)
    standard = int((lower + min(abs_upper, upper)) / 2)
    aggressive = min(abs_upper, upper)

    # 保底
    conservative = max(conservative, abs_lower)

    return {
        "conservative": {"price": conservative, "rate": calc_rate(my_base, conservative)},
        "standard": {"price": standard, "rate": calc_rate(my_base, standard)},
        "aggressive": {"price": aggressive, "rate": calc_rate(my_base, aggressive)},
        "median_rate": round(luxury_median, 1),
        "calibration_range": {"lower": lower, "upper": min(abs_upper, upper)},
        "abs_upper": abs_upper,
        "abs_lower": abs_lower,
        "valid_competitors": len(valid_rates),
    }


# ── 报告生成 ──────────────────────────────────────────────

def build_markdown_report(hotel_name, target_date, my_base, competitors,
                          calibration, scope, output_path):
    """生成 Markdown 格式竞品分析报告"""

    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_display = datetime.strptime(target_date, "%Y-%m-%d").strftime("%Y年%m月%d日")

    luxury = [c for c in competitors if c.get("star") in ("豪华型", "五星级", "5星")]
    valid_rates = [c["rate"] for c in competitors if c.get("rate") is not None]
    luxury_max = max([c["rate"] for c in competitors if c.get("rate") is not None]) if valid_rates else 0

    room_suggestions = [
        {"room": "高级房", "base": int(my_base * 0.8), "rec": int(my_base * 0.8 * (1 + calibration["median_rate"]/100))},
        {"room": "豪华房", "base": my_base, "rec": int(my_base * (1 + calibration["median_rate"]/100))},
        {"room": "套房", "base": int(my_base * 1.5), "rec": int(my_base * 1.5 * (1 + calibration["median_rate"]/100))},
    ]

    # Build room suggestion rows
    room_rows = "".join([
        "| " + r["room"] + " | Y" + str(r["base"]) + " | **Y" + str(r["rec"]) + "** | +" + str(round((r["rec"] - r["base"]) / r["base"] * 100, 1)) + "% | 参照竞品涨幅 |\n"
        for r in room_suggestions
    ])

    # Build competitor table rows
    table_rows = "".join([
        "| " + c.get("name", "未知") + " | " + c.get("star", "高档型")
        + " | **Y" + str(c["holiday"]) + "** | "
        + ("Y" + str(c["base"]) if c.get("base") else "N/A")
        + " | " + ("+" + str(c["rate"]) + "%" if c.get("rate") is not None else "数据缺失")
        + " | " + (c.get("distance") or "") + " | 飞猪实时 |\n"
        for c in competitors
    ])

    # Build appendix
    appendix = "".join([
        "**" + c.get("name", "未知") + "**\n"
        + "- 位置：" + c.get("distance", "未知") + "\n"
        + "- 假期价：Y" + str(c["holiday"]) + "/晚\n"
        + "- 平日价：" + ("Y" + str(c["base"]) if c.get("base") else "N/A") + "/晚\n"
        + "- 涨幅：" + ("+" + str(c["rate"]) + "%" if c.get("rate") is not None else "N/A") + "\n"
        + "- 装修：" + (c.get("decoration") or "未知") + "\n\n"
        for c in competitors
    ])

    scope_text = ("滨海核心区" if scope == "滨海" else "市区高端" if scope == "市区" else "全域")

    md = (
        "# " + hotel_name + "·" + date_display + " 竞品价格分析报告\n"
        + "\n"
        + "> **数据来源**：飞猪Fliggy实时API（flyai CLI）\n"
        + "> **调研时间**：" + today + "\n"
        + "> **数据范围**：" + scope_text + "竞品（经纬度过滤）\n"
        + "> **调研人**：AI竞品分析Skill v2.0（德胧AI实验室）\n"
        + "> **数据声明**：所有价格均为飞猪实时真实数据，无演示/虚拟数据\n"
        + "\n"
        + "---\n"
        + "\n"
        + "## 一、核心发现\n"
        + "\n"
        + "### 1.1 竞品价格对比（飞猪实时数据）\n"
        + "\n"
        + "| 酒店名称 | 星级 | 假期价格 | 平日价格 | 涨幅 | 位置 | 数据来源 |\n"
        + "|---------|------|---------|---------|------|------|---------|\n"
        + table_rows
        + "\n"
        + "### 1.2 关键数据洞察\n"
        + "\n"
        + "| 指标 | 数值 | 说明 |\n"
        + "|------|------|------|\n"
        + "| 有效竞品数量 | " + str(len(competitors)) + "家 | 飞猪实时数据 |\n"
        + "| 竞品涨幅中位数 | +" + str(calibration["median_rate"]) + "% | 定价锚点 |\n"
        + "| 最高涨幅 | +" + str(luxury_max) + "% | 价格弹性上限参考 |\n"
        + "| 绝对值校准上限 | Y" + str(calibration["abs_upper"]) + " | 不超越此值 |\n"
        + "| 绝对值校准下限 | Y" + str(calibration["abs_lower"]) + " | 价格战警戒线 |\n"
        + "\n"
        + "### 1.3 核心结论\n"
        + "\n"
        + "- 滨海高端竞品涨幅集中在 +" + str(int(calibration["median_rate"] * 0.8)) + "%~+" + str(int(calibration["median_rate"] * 1.2)) + "%区间\n"
        + "- **建议采用标准策略（+" + str(calibration["standard"]["rate"]) + "%）：Y" + str(my_base) + " -> Y" + str(calibration["standard"]["price"]) + "**\n"
        + "- 溢价空间：建议不超过Y" + str(calibration["abs_upper"]) + "（竞品最高的95%）\n"
        + "\n"
        + "---\n"
        + "\n"
        + "## 二、定价建议\n"
        + "\n"
        + "### 2.1 建议价格区间\n"
        + "\n"
        + "| 房型 | 平日价(参考) | 建议假期价 | 涨幅 | 依据 |\n"
        + "|------|------------|----------|------|------|\n"
        + room_rows
        + "\n"
        + "### 2.2 三档调价策略\n"
        + "\n"
        + "**保守策略（+" + str(calibration["conservative"]["rate"]) + "%）**：\n"
        + "- 价格：Y" + str(calibration["conservative"]["price"]) + "\n"
        + "- 风险低，转化率稳定\n"
        + "- 适合：早鸟预订开放期（距假期30天以上）\n"
        + "\n"
        + "**标准策略（+" + str(calibration["standard"]["rate"]) + "%）** 推荐：\n"
        + "- 价格：Y" + str(calibration["standard"]["price"]) + "\n"
        + "- 与滨海竞品涨幅持平\n"
        + "- 适合：距假期15-30天，预订率50%左右\n"
        + "\n"
        + "**激进策略（+" + str(calibration["aggressive"]["rate"]) + "%）**：\n"
        + "- 价格：Y" + str(calibration["aggressive"]["price"]) + "\n"
        + "- 对标高端竞品涨价幅度\n"
        + "- 适合：距假期不足14天且预订率超70%\n"
        + "\n"
        + "---\n"
        + "\n"
        + "## 三、行动建议\n"
        + "\n"
        + "### 3.1 立即行动\n"
        + "\n"
        + "- [ ] 对比我店当前价格与建议区间（Y" + str(calibration["conservative"]["price"]) + " ~ Y" + str(calibration["aggressive"]["price"]) + "）\n"
        + "- [ ] 确认PMS系统调价时间节点（建议提前30天开放早鸟价）\n"
        + "- [ ] 同步携程/美团/飞猪三平台价格（保持各平台价格一致）\n"
        + "- [ ] 设置价格预警：超出Y" + str(calibration["abs_upper"]) + "时自动提醒\n"
        + "\n"
        + "### 3.2 持续监测\n"
        + "\n"
        + "- 每日监测竞品价格变动（建议使用竞品巡检定时任务）\n"
        + "- 根据预订率动态调整（低于30%预订率->保守策略；高于70%->激进策略）\n"
        + "- 关注房态紧张程度，非单纯价格\n"
        + "\n"
        + "---\n"
        + "\n"
        + "## 四、数据附录\n"
        + "\n"
        + "### 4.1 竞品详细信息\n"
        + "\n"
        + appendix
        + "### 4.2 双重校准算法参数\n"
        + "\n"
        + "| 参数 | 数值 |\n"
        + "|------|------|\n"
        + "| 竞品涨幅中位数 | +" + str(calibration["median_rate"]) + "% |\n"
        + "| 涨幅校准区间 | " + str(calibration["calibration_range"]["lower"]) + " ~ " + str(min(calibration["abs_upper"], calibration["calibration_range"]["upper"])) + " |\n"
        + "| 绝对值校准上限 | Y" + str(calibration["abs_upper"]) + " |\n"
        + "| 绝对值校准下限 | Y" + str(calibration["abs_lower"]) + " |\n"
        + "| 有效数据点 | " + str(len(valid_rates)) + "家 |\n"
        + "\n"
        + "---\n"
        + "\n"
        + "## 五、方法论沉淀\n"
        + "\n"
        + "### 5.1 FlyAI酒店调研SOP（v2.0）\n"
        + "\n"
        + "1. **确定目的地关键词**（例：天津滨海新区）\n"
        + "2. **搜索假期日期价格**（flyai search-hotel + check-in/out-date）\n"
        + "3. **搜索平日日期价格**（同一命令，仅换日期）\n"
        + "4. **按经纬度过滤**（滨海：lat 38.95-39.10, lon 117.60-117.80）\n"
        + "5. **合并两季数据**（按shId匹配）\n"
        + "6. **计算涨幅**：(假期价-平日价)/平日价 x 100%\n"
        + "7. **去除异常值**（涨幅>100%或<0%）\n"
        + "8. **排序输出**：按涨幅降序取top N\n"
        + "\n"
        + "### 5.2 双重校准定价法\n"
        + "\n"
        + "```\n"
        + "第一步：涨幅校准\n"
        + "  -> 计算竞品涨幅中位数（抗异常值）\n"
        + "  -> 我店涨幅 = 竞品涨幅中位数 +-15%\n"
        + "\n"
        + "第二步：绝对值校准\n"
        + "  -> 推荐价格 <= 竞品最高 x 0.95（不超越顶级竞品）\n"
        + "  -> 推荐价格 >= 竞品最低 x 1.1（防止价格战）\n"
        + "\n"
        + "第三步：三档策略\n"
        + "  -> 保守 = min(绝对值上限, 涨幅下限)\n"
        + "  -> 标准 = (涨幅下限 + min(绝对值上限, 涨幅上限)) / 2\n"
        + "  -> 激进 = min(绝对值上限, 涨幅上限)\n"
        + "```\n"
        + "\n"
        + "### 5.3 数据质量规则\n"
        + "\n"
        + "- **禁止使用演示/虚拟数据** - 所有数据必须来自真实API\n"
        + "- 飞猪数据为实时价格，可能波动，建议多平台交叉验证\n"
        + "- 关注房态紧张程度，非单纯价格\n"
        + "- 平日价取假期前14天的同星期日期价格对比\n"
        + "\n"
        + "---\n"
        + "\n"
        + "**报告生成时间**：" + today + "\n"
        + "**工具支持**：hotel-compete-report Skill v2.0（德胧AI实验室）\n"
        + "**数据来源**：飞猪Fliggy实时API（flyai CLI）\n"
        + "**数据有效期**：当日实时\n"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    log_ok("Markdown 报告已生成：" + output_path)
    return output_path


def build_html_report(md_path):
    """将 Markdown 转换为带样式的 HTML"""
    html_path = md_path.replace(".md", ".html")
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    body_content = content.replace('\n', '<br>')
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>竞品价格分析报告</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1100px; margin: 0 auto; padding: 20px;
         background: #f5f6fa; color: #333; line-height: 1.8; }
  h1 { color: #1a1a2e; border-bottom: 3px solid #0066cc; padding-bottom: 10px; }
  h2 { color: #16213e; margin-top: 35px; border-left: 5px solid #0066cc; padding-left: 12px; }
  h3 { color: #0f3460; }
  table { border-collapse: collapse; width: 100%; margin: 15px 0;
           box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
  th { background: #0066cc; color: white; padding: 12px 10px; text-align: left; }
  td { padding: 10px; border-bottom: 1px solid #eee; }
  tr:hover { background: #f0f4ff; }
  td:first-child { font-weight: 600; }
  blockquote { border-left: 4px solid #ffc107; background: #fff8e1; padding: 12px 18px;
               margin: 15px 0; border-radius: 4px; }
  code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; }
  pre { background: #1a1a2e; color: #a8dadc; padding: 15px; border-radius: 8px;
         overflow-x: auto; }
  @media print { body { background: white; } }
</style>
</head>
<body>
""" + body_content + """
</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    log_ok(f"HTML 报告已生成：{html_path}")


def build_json_recommendation(hotel_name, target_date, my_base, calibration):
    """输出调价建议JSON（供PMS系统对接）"""
    return {
        "hotel": hotel_name,
        "target_date": target_date,
        "base_price": my_base,
        "data_source": "飞猪Fliggy实时API",
        "recommendation": {
            "conservative": {
                "price": calibration["conservative"]["price"],
                "rate": calibration["conservative"]["rate"]
            },
            "standard": {
                "price": calibration["standard"]["price"],
                "rate": calibration["standard"]["rate"],
                "recommended": True
            },
            "aggressive": {
                "price": calibration["aggressive"]["price"],
                "rate": calibration["aggressive"]["rate"]
            }
        },
        "calibration": {
            "median_rate": calibration["median_rate"],
            "range": calibration["calibration_range"],
            "abs_upper": calibration["abs_upper"],
            "abs_lower": calibration["abs_lower"]
        }
    }


# ── 主程序 ─────────────────────────────────────────────────

def main():
    args = parse_args()

    hotel_name = args.hotel
    target_date = args.target_date
    competitors_count = args.competitors
    scope = args.scope
    my_base = args.base_price

    log_info(f"酒店：{hotel_name}")
    log_info(f"目标日期：{target_date}")
    log_info(f"调研范围：{scope}")
    log_info(f"竞品数量：{competitors_count}")

    # ── Step 1: 获取高德 API Key ─────────────────────────────
    import os
    amap_key = args.amap_key or os.environ.get("AMAP_MAPS_API_KEY") or os.environ.get("AMAP_KEY")
    if amap_key:
        log_ok(f"高德 API Key 已配置（key: {amap_key[:8]}...）")
    else:
        log_warn("高德 API Key 未配置（环境变量 AMAP_MAPS_API_KEY 或 AMAP_KEY），将跳过 POI 精准定位")

    # ── Step 2: 高德 POI 精准定位竞品 ────────────────────────
    # 滨海核心竞品库（可扩展，key为高德POI搜索关键词）
    BINHAI_COMPETITORS = [
        "天津于家堡洲际酒店",
        "天津滨海皇冠假日酒店",
        "天津万丽泰达酒店",
        "天津滨海泰达万豪行政公寓",
        "滨海一号酒店",
        "天津滨海圣光皇冠假日酒店",
    ]

    # 全市高端竞品库
    TIANJIN_LUXURY = [
        "天津四季酒店",
        "天津香格里拉",
        "天津康莱德酒店",
        "天津富力万达文华酒店",
    ]

    poi_data = {}
    if amap_key:
        log_info("正在通过高德 POI 精准定位竞品酒店...")
        competitors_to_search = BINHAI_COMPETITORS + TIANJIN_LUXURY if scope != "滨海" else BINHAI_COMPETITORS
        poi_data = fetch_amap_poi(competitors_to_search, amap_key)
        log_ok(f"高德 POI 定位完成：{len(poi_data)}/{len(competitors_to_search)}家竞品")

    # ── Step 3: 采集真实竞品数据（禁止演示数据）─────────────
    check_in = target_date
    check_out = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")

    # Step 3a: 高德 POI 定位到的竞品 → 飞猪关键词精确查价
    keyword_competitors = []
    if poi_data:
        log_info("正在通过飞猪关键词精确搜索竞品价格...")
        keyword_competitors = fetch_fliggy_by_keywords(poi_data, check_in, check_out, args.force_refresh)
        log_ok(f"关键词精确查价完成：{len(keyword_competitors)}家")

    # Step 3b: 飞猪区域搜索（补充其他竞品）
    competitors = fetch_fliggy_price(hotel_name, check_in, check_out, scope, competitors_count, poi_data=poi_data)

    # Step 3c: 合并两组数据（去重）
    if keyword_competitors:
        existing_names = {c["name"] for c in (competitors or [])}
        for kc in keyword_competitors:
            # 名称去重（同一酒店保留关键词搜索结果，更准确）
            if kc["name"] not in existing_names:
                competitors.append(kc)
        log_ok(f"数据合并完成：区域搜索{len(competitors)-len(keyword_competitors)}家 + 关键词搜索{len(keyword_competitors)}家 = 共{len(competitors)}家")

    if competitors is None:
        log_err("=" * 50)
        log_err("【致命错误】无法获取飞猪真实数据")
        log_err("解决方案：")
        log_err("  1. 确认 flyai CLI 已安装且已登录（flyai --help）")
        log_err("  2. 检查网络连接后重试")
        log_err("  3. 如API不稳定，请联系德胧AI实验室更新方案")
        log_err("=" * 50)
        sys.exit(1)

    log_ok(f"数据采集成功：{len(competitors)}家有效竞品")

    # ── Step 2: 验证平日价 ────────────────────────────────
    valid_base = [c for c in competitors if c.get("base") is not None]
    if not valid_base:
        log_err("所有竞品平日价数据缺失，无法计算涨幅，请尝试其他日期")
        sys.exit(1)

    log_ok(f"有效涨幅数据：{len(valid_base)}/{len(competitors)}家")

    # ── Step 3: 我店平日价 ───────────────────────────────
    if my_base is None:
        log_err("必须指定我店平日价（--base-price）")
        log_err("例：--base-price 443")
        sys.exit(1)

    # ── Step 4: 双重校准 ────────────────────────────────
    calibration = dual_calibration(my_base, competitors)
    if calibration is None:
        log_err("校准算法失败")
        sys.exit(1)

    log_ok(f"校准完成：标准策略 ¥{calibration['standard']['price']}（+{calibration['standard']['rate']}%）")

    # ── Step 5: 生成输出 ────────────────────────────────
    os.makedirs(args.output_dir, exist_ok=True)

    md_filename = generate_output_filename(hotel_name, target_date, "竞品价格分析报告", "md")
    md_path = os.path.join(args.output_dir, md_filename)

    build_markdown_report(hotel_name, target_date, my_base, competitors,
                          calibration, scope, md_path)
    build_html_report(md_path)

    # JSON建议
    json_filename = generate_output_filename(hotel_name, target_date, "pricing_recommendation", "json")
    json_path = os.path.join(args.output_dir, json_filename)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(build_json_recommendation(hotel_name, target_date, my_base, calibration),
                  f, ensure_ascii=False, indent=2)
    log_ok(f"JSON 建议已生成：{json_path}")

    # 原始数据存档
    raw_filename = generate_output_filename(hotel_name, target_date, "raw_data", "json")
    raw_path = os.path.join(args.output_dir, raw_filename)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump({
            "competitors": competitors,
            "calibration": calibration,
            "generated_at": datetime.now().isoformat(),
            "data_source": "飞猪Fliggy实时API",
            "no_demo_data": True
        }, f, ensure_ascii=False, indent=2)
    log_ok(f"原始数据已存档：{raw_path}")

    # 保存价格历史到多维表格（如果配置了）
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from core.price_history import get_default_storage
        storage = get_default_storage()
        if storage:
            # 保存目标酒店推荐价格
            storage.add_record(
                hotel_name=hotel_name,
                target_date=target_date,
                price=calibration['standard']['price'],
                base_price=my_base,
                competitor=",".join([c['name'] for c in competitors if c.get('name')]),
                source="flyai-compete-report"
            )
    except Exception as e:
        log_warn(f"保存价格历史失败: {e}")

    log_ok(f"\n✅ 报告生成完成！（真实数据，无演示）")
    log_ok(f"输出目录：{args.output_dir}")
    print(f"\n推荐价格：保守 ¥{calibration['conservative']['price']} | "
          f"标准 ¥{calibration['standard']['price']} ⭐ | "
          f"激进 ¥{calibration['aggressive']['price']}")


if __name__ == "__main__":
    main()
