#!/usr/bin/env python3
"""
多维竞品评分引擎 v1.0
竞品得分 = 距离分(30%) × 星级分(30%) × 品牌分(20%) × 价格分(20%)
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import math


@dataclass
class HotelPOI:
    """酒店POI对象（来自高德/飞猪）"""
    name: str
    location: str           # "lon,lat"
    star: str                # 五星级/四星级/高档型...
    brand: str = ""          # 品牌名
    price: Optional[int] = None
    distance_km: Optional[float] = None
    source: str = "amap"     # amap | fliggy | manual


@dataclass
class CompetitorScore:
    """竞品评分结果"""
    hotel: HotelPOI
    distance_score: float     # 0-100
    star_score: float        # 0-100
    brand_score: float        # 0-100
    price_score: float       # 0-100
    total_score: float        # 加权总分 0-100
    is_valid: bool            # 是否进入有效竞品集
    reason: str = ""          # 评分原因


# ── 星级档位映射 ──────────────────────────────────────────

STAR_TIERS = {
    "luxury":    ["五星级", "五星级宾馆", "豪华型", "luxury"],
    "upscale":   ["四星级", "四星级宾馆", "高档型", "upscale"],
    "midrange":  ["三星级", "三星级宾馆", "舒适型", "midrange"],
    "economy":   ["经济型", "客栈", "青年旅舍"],
}

BRAND_TIERS = {
    "luxury_brand": [
        "洲际", "皇冠假日", "万豪", "希尔顿", "香格里拉",
        "丽思卡尔顿", "四季", "柏悦", "君悦", "威斯汀"
    ],
    "upscale_brand": [
        "开元", "华美达", "假日", "诺富特", "美居",
        "福朋", "戴斯", "智选假日"
    ],
    "local_brand": [
        "泰达", "瑞湾", "滨海", "津利华", "友谊"
    ]
}

# ── 距离分计算（30%权重）───────────────────────────────────

def calc_distance_score(distance_km: float) -> float:
    """距离分：≤1km=100, ≤3km=80, ≤5km=60, ≤10km=30, >10km=0"""
    if distance_km is None:
        return 50  # 未知距离给中间分
    if distance_km <= 1:
        return 100
    elif distance_km <= 3:
        return 80
    elif distance_km <= 5:
        return 60
    elif distance_km <= 10:
        return 30
    else:
        return 0


# ── 星级分计算（30%权重）──────────────────────────────────

def get_star_tier(star: str) -> str:
    """获取星级档次"""
    if not star:
        return "unknown"
    for tier, keywords in STAR_TIERS.items():
        if any(k in star for k in keywords):
            return tier
    return "unknown"


def calc_star_score(star1: str, star2: str) -> float:
    """星级匹配分：同档=100, 相邻=60, 相差2档=20, 未知=50"""
    t1 = get_star_tier(star1)
    t2 = get_star_tier(star2)
    if t1 == "unknown" or t2 == "unknown":
        return 50
    if t1 == t2:
        return 100
    tiers = list(STAR_TIERS.keys())
    diff = abs(tiers.index(t1) - tiers.index(t2))
    if diff == 1:
        return 60
    return 20


# ── 品牌分计算（20%权重）──────────────────────────────────

def get_brand_tier(brand: str) -> str:
    """获取品牌档次"""
    if not brand:
        return "unknown"
    for tier, brands in BRAND_TIERS.items():
        if any(b in brand for b in brands):
            return tier
    return "other"


def calc_brand_score(brand1: str, brand2: str) -> float:
    """品牌分：同档次=100, 相邻=70, 其他=50, 未知=50"""
    if not brand1 or not brand2:
        return 50
    t1 = get_brand_tier(brand1)
    t2 = get_brand_tier(brand2)
    if t1 == t2:
        return 100
    if t1 == "other" or t2 == "other":
        return 50
    # luxury ↔ upscale = 70, upscale ↔ midrange = 70
    tiers = ["luxury_brand", "upscale_brand", "local_brand"]
    if t1 in tiers and t2 in tiers:
        diff = abs(tiers.index(t1) - tiers.index(t2))
        return 70 if diff == 1 else 50
    return 50


# ── 价格分计算（20%权重）──────────────────────────────────

def calc_price_score(price: Optional[int], base_price: int, tolerance_pct: float = 0.3) -> float:
    """
    价格分：与目标酒店价格带重叠=100, 相差≤30%=80, 相差≤50%=50, 相差>50%=20
    price=None时返回50（无价格数据）
    """
    if price is None:
        return 50
    ratio = price / base_price if base_price > 0 else 1
    if 0.7 <= ratio <= 1.3:  # ±30%重叠
        return 100
    elif 0.5 <= ratio <= 1.5:  # ±50%
        return 60
    else:
        return 20


# ── 解析经纬度字符串 ──────────────────────────────────────

def parse_location(loc: str) -> Tuple[float, float]:
    """解析 'lon,lat' 字符串，返回 (lon, lat)"""
    if not loc:
        return (0.0, 0.0)
    parts = loc.split(",")
    if len(parts) != 2:
        return (0.0, 0.0)
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return (0.0, 0.0)


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """计算两点间球面距离（km）"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


# ── 核心评分函数 ──────────────────────────────────────────

def score_competitor(
    hotel: HotelPOI,
    target_hotel: HotelPOI,
    base_price: int,
    max_distance_km: float = 5.0,
    require_same_star: bool = True,
) -> CompetitorScore:
    """
    对单个竞品酒店进行多维评分

    Args:
        hotel: 待评分酒店
        target_hotel: 目标酒店（用于对比）
        base_price: 目标酒店平日基准价
        max_distance_km: 最大有效距离（km）
        require_same_star: 是否强制同星级

    Returns:
        CompetitorScore
    """
    # 1. 距离分
    if hotel.distance_km is not None:
        dist_score = calc_distance_score(hotel.distance_km)
        if hotel.distance_km > max_distance_km:
            return CompetitorScore(
                hotel=hotel, distance_score=dist_score,
                star_score=0, brand_score=0, price_score=0, total_score=0,
                is_valid=False, reason=f"距离{hotel.distance_km}km超过{max_distance_km}km阈值"
            )
    else:
        dist_score = 50

    # 2. 星级分
    star_score = calc_star_score(hotel.star, target_hotel.star)
    if require_same_star and star_score < 60:
        return CompetitorScore(
            hotel=hotel, distance_score=dist_score,
            star_score=star_score, brand_score=0, price_score=0, total_score=0,
            is_valid=False, reason=f"星级不匹配（{hotel.star} vs {target_hotel.star}）"
        )

    # 3. 品牌分
    brand_score = calc_brand_score(hotel.brand, target_hotel.brand)

    # 4. 价格分
    price_score = calc_price_score(hotel.price, base_price) if hotel.price else 50

    # 5. 加权总分
    total = (
        dist_score * 0.30 +
        star_score * 0.30 +
        brand_score * 0.20 +
        price_score * 0.20
    )

    # 6. 判断是否有效
    is_valid = (
        dist_score >= 60 and
        star_score >= 60 and
        total >= 50
    )

    reason = f"综合得分{total:.0f}（距离{hotel.distance_km}km/星级{hotel.star}/品牌{hotel.brand}）"

    return CompetitorScore(
        hotel=hotel,
        distance_score=dist_score,
        star_score=star_score,
        brand_score=brand_score,
        price_score=price_score,
        total_score=round(total, 1),
        is_valid=is_valid,
        reason=reason
    )


def filter_competitors(
    hotels: List[HotelPOI],
    target_hotel: HotelPOI,
    base_price: int,
    max_distance_km: float = 5.0,
    min_score: float = 50.0,
) -> List[CompetitorScore]:
    """
    对一批候选酒店进行过滤+评分，返回有效竞品列表（按得分降序）
    """
    results = []
    for h in hotels:
        score = score_competitor(
            hotel=h,
            target_hotel=target_hotel,
            base_price=base_price,
            max_distance_km=max_distance_km
        )
        if score.is_valid and score.total_score >= min_score:
            results.append(score)

    results.sort(key=lambda x: x.total_score, reverse=True)
    return results


# ── 快速预览（供CLI调用）──────────────────────────────────

def preview_scores(hotels: List[HotelPOI], base_price: int) -> None:
    """打印竞品评分预览"""
    print(f"\n{'='*60}")
    print(f"{'竞品多维评分预览':^60}")
    print(f"{'='*60}")
    print(f"{'酒店名':<20} {'距离':>6} {'星级':>8} {'品牌':>8} {'价格':>6} {'总分':>6}")
    print(f"{'-'*60}")
    for h in hotels:
        d = f"{h.distance_km:.1f}km" if h.distance_km else "N/A"
        s = get_star_tier(h.star)
        p = f"¥{h.price}" if h.price else "N/A"
        print(f"{h.name:<20} {d:>6} {s:>8} {h.brand:<8} {p:>6}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    # 快速测试
    target = HotelPOI(
        name="天津瑞湾开元名都",
        location="117.745689,39.021567",
        star="高档型",
        brand="开元",
        price=443
    )

    candidates = [
        HotelPOI(name="天津于家堡洲际酒店", location="117.701234,39.012345", star="五星级", brand="洲际", price=916, distance_km=4.2),
        HotelPOI(name="天津滨海皇冠假日酒店", location="117.689012,39.023456", star="五星级", brand="皇冠假日", price=848, distance_km=5.1),
        HotelPOI(name="天津泰达万豪酒店", location="117.723456,39.034567", star="五星级", brand="万豪", price=812, distance_km=2.8),
        HotelPOI(name="天津生态城希尔顿酒店", location="117.744378,39.126655", star="五星级", brand="希尔顿", price=558, distance_km=11.7),
        HotelPOI(name="天津泰达中心酒店", location="117.690659,39.035478", star="四星级", brand="泰达", price=333, distance_km=5.2),
    ]

    filtered = filter_competitors(candidates, target, base_price=443, max_distance_km=5.0)
    print(f"有效竞品：{len(filtered)}家\n")
    for s in filtered:
        print(f"✅ {s.hotel.name} | 总分:{s.total_score} | {s.reason}")
