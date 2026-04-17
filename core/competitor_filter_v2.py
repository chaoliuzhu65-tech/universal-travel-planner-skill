#!/usr/bin/env python3
"""
多维竞品评分引擎 v2.1 - 优化版
改进点：
1. 软性分级筛选 → 不过度筛选，保留完整市场格局给决策者
2. 分组展示：强相关 / 外资竞品 / 内资竞品 / 价格区间分组
3. 自动半径扩展：竞品太少自动从5km→10km→15km
4. 每个价位区间最多选10家，保证决策者看到足够样本
5. 依然支持动态权重、异常值过滤、occupancy加分
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import math
import statistics


@dataclass
class HotelPOI:
    """酒店POI对象（来自高德/飞猪/Google搜索）"""
    name: str
    location: str           # "lon,lat"
    star: str                # 五星级/四星级/高档型...
    brand: str = ""          # 品牌名
    price: Optional[int] = None  # 平日价格
    distance_km: Optional[float] = None
    occupancy: Optional[str] = None  # 满房/high/medium/low
    rating: Optional[float] = None  # 用户评分（Google搜索获取）
    review_count: Optional[int] = None  # 评价数量
    source: str = "amap"     # amap | fliggy | manual | google


@dataclass
class CompetitorScore:
    """竞品评分结果"""
    hotel: HotelPOI
    distance_score: float     # 0-100
    star_score: float        # 0-100
    brand_score: float        # 0-100
    price_score: float       # 0-100
    occupancy_bonus: float   # 额外加分：竞品满房
    total_score: float        # 加权总分 0-100
    is_valid: bool            # 是否进入有效竞品集
    reason: str = ""          # 评分原因


@dataclass
class FilterConfig:
    """筛选配置 - 支持动态权重"""
    max_distance_km: float = 8.0
    min_score: float = 40.0
    top_n: int = 8  # 强相关保留Top N
    # 权重配置
    weight_distance: float = 0.30
    weight_star: float = 0.30
    weight_brand: float = 0.20
    weight_price: float = 0.20
    # 开关
    enable_outlier_filter: bool = True  # 异常值过滤
    require_same_star: bool = False  # v2.1改为默认False，不强制同星级排除
    # occupancy 加分
    bonus_occupancy_full: float = 10  # 竞品满房加多少分
    bonus_occupancy_high: float = 5


@dataclass
class GroupedCompetitors:
    """分组竞品结果，用于展示给决策者"""
    strong_relevant: List[CompetitorScore]      # 强相关（高分，直接用于AI调价）
    foreign_brands: List[CompetitorScore]       # 外资品牌竞品
    domestic_brands: List[CompetitorScore]       # 内资品牌竞品
    by_price_tier: Dict[str, List[CompetitorScore]]  # 价格区间分组: low/mid/high
    all_candidates: List[CompetitorScore]      # 所有候选（没被距离排除的）
    auto_expanded: bool = False                  # 是否自动扩大了搜索半径


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
        "凯悦", "君悦", "威斯汀", "万丽", "四季", "丽思卡尔顿"
    ],
    "upscale_brand": [
        "开元", "德胧", "华美达", "假日", "诺富特", "美居",
        "福朋", "戴斯", "智选假日", "万怡", "希尔顿花园"
    ],
    "local_brand": [
        "本土品牌", "区域品牌"
    ]
}

# ── 距离分计算 ─────────────────────────────────────────────

def calc_distance_score(distance_km: float) -> float:
    """距离分：≤1km=100, ≤3km=80, ≤5km=60, ≤10km=30, >10km=0"""
    if distance_km is None:
        return 50
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


# ── 星级分计算 ───────────────────────────────────────────

def get_star_tier(star: str) -> str:
    """获取星级档次"""
    if not star:
        return "unknown"
    for tier, keywords in STAR_TIERS.items():
        if any(k in star for k in keywords):
            return tier
    return "unknown"


def calc_star_score(star1: str, star2: str) -> float:
    """星级匹配分：同档=100, 相邻=60, 相差2档=20, 未知=50
    v2.1改进：不排除，只给低分，不删除
    """
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


# ── 品牌分计算 ─────────────────────────────────────────────

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
    tiers = ["luxury_brand", "upscale_brand", "local_brand"]
    if t1 in tiers and t2 in tiers:
        diff = abs(tiers.index(t1) - tiers.index(t2))
        return 70 if diff == 1 else 50
    return 50


# ── 价格分计算 ─────────────────────────────────────────────

def calc_price_score(price: Optional[int], base_price: int, tolerance_pct: float = 0.3) -> float:
    """
    价格分：与目标酒店价格带重叠=100, 相差≤30%=80, 相差≤50%=50, 相差>50%=20
    price=None时返回50（无价格数据）
    """
    if price is None:
        return 50
    if base_price <= 0:
        return 50
    ratio = price / base_price
    if 0.7 <= ratio <= 1.3:  # ±30%重叠
        return 100
    elif 0.5 <= ratio <= 1.5:  # ±50%
        return 60
    else:
        return 20


# ── occupancy 加分 ──────────────────────────────────────────

def calc_occupancy_bonus(occupancy: Optional[str], config: FilterConfig) -> float:
    """根据竞品入住率给额外加分"""
    if not occupancy:
        return 0
    occupancy = occupancy.lower()
    if "满" in occupancy or "full" in occupancy:
        return config.bonus_occupancy_full
    if "high" in occupancy:
        return config.bonus_occupancy_high
    return 0


# ── 用户评分加分 (Google搜索补充) ──────────────────────────

def calc_rating_bonus(rating: Optional[float], review_count: Optional[int]) -> float:
    """
    根据用户评分给额外加分：
    - 评分 ≥ 4.5 + 评价数 ≥ 100 → +5分
    - 评分 ≥ 4.0 + 评价数 ≥ 50 → +3分
    - 否则 → 0分
    """
    if rating is None or review_count is None:
        return 0
    if rating >= 4.5 and review_count >= 100:
        return 5.0
    if rating >= 4.0 and review_count >= 50:
        return 3.0
    return 0


# ── 异常值过滤 ─────────────────────────────────────────────

def filter_price_outliers(prices: List[float], iqr_factor: float = 1.5) -> List[bool]:
    """
    使用IQR方法检测价格异常值
    返回每个价格是否是正常值（True=正常，False=异常）
    """
    if len(prices) < 4:
        return [True] * len(prices)

    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    q1_idx = int(n * 0.25)
    q3_idx = int(n * 0.75)
    q1 = sorted_prices[q1_idx]
    q3 = sorted_prices[q3_idx]
    iqr = q3 - q1
    lower_bound = q1 - iqr_factor * iqr
    upper_bound = q3 + iqr_factor * iqr

    return [lower_bound <= p <= upper_bound for p in prices]


# ── 经纬度距离计算 ──────────────────────────────────────────

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


# ── 核心评分 ──────────────────────────────────────────────────

def score_competitor_v2(
    hotel: HotelPOI,
    target_hotel: HotelPOI,
    base_price: int,
    config: FilterConfig,
) -> CompetitorScore:
    """
    对单个竞品酒店进行多维评分（v2.1支持软性筛选）

    v2.1改进：
    - 只硬过滤超过最大距离的，其他都保留
    - 不对星级做硬性排除，只影响分数不删除
    - 让决策者看到完整市场格局
    """
    # 1. 距离硬过滤（只过滤超远的，近的都保留）
    if hotel.distance_km is not None:
        dist_score = calc_distance_score(hotel.distance_km)
        if hotel.distance_km > config.max_distance_km:
            return CompetitorScore(
                hotel=hotel, distance_score=dist_score,
                star_score=0, brand_score=0, price_score=0, occupancy_bonus=0,
                total_score=0,
                is_valid=False, reason=f"距离{hotel.distance_km}km超过{config.max_distance_km}km阈值"
            )
    else:
        dist_score = 50

    # 2. 星级评分（不硬性排除，只影响分数）
    star_score = calc_star_score(hotel.star, target_hotel.star)

    # 3. 品牌分
    brand_score = calc_brand_score(hotel.brand, target_hotel.brand)

    # 4. 价格分
    price_score = calc_price_score(hotel.price, base_price) if hotel.price else 50

    # 5. occupancy加分
    occ_bonus = calc_occupancy_bonus(hotel.occupancy, config)

    # 6. 用户评分加分（Google搜索补充）
    rating_bonus = calc_rating_bonus(hotel.rating, hotel.review_count)

    # 7. 加权总分（动态权重 + 各种加分）
    total = (
        dist_score * config.weight_distance +
        star_score * config.weight_star +
        brand_score * config.weight_brand +
        price_score * config.weight_price +
        occ_bonus +
        rating_bonus
    )

    # 8. 判断是否有效进入推荐（有效=进入AI调价精选）
    is_valid = (
        dist_score >= 30 and
        total >= config.min_score
    )

    reason = (f"综合得分{total:.1f}（距离{hotel.distance_km}km/星级{hotel.star}/品牌{hotel.brand}/occupancy+{occ_bonus}）")

    return CompetitorScore(
        hotel=hotel,
        distance_score=dist_score,
        star_score=star_score,
        brand_score=brand_score,
        price_score=price_score,
        occupancy_bonus=occ_bonus,
        total_score=round(total, 1),
        is_valid=is_valid,
        reason=reason
    )


# ── 分组函数 ─────────────────────────────────────────────────

def group_by_price_tier(results: List[CompetitorScore], target_price: float) -> Dict[str, List[CompetitorScore]]:
    """按价格区间分组：
    - low: 低于目标 × 0.7
    - mid: 目标 × 0.7 ~ × 1.3
    - high: 高于目标 × 1.3
    每个区间最多选10家，按得分降序
    """
    groups: Dict[str, List[CompetitorScore]] = {
        "low": [],
        "mid": [],
        "high": [],
    }
    for s in results:
        if not s.hotel.price:
            groups["mid"].append(s)
            continue
        ratio = s.hotel.price / target_price
        if ratio < 0.7:
            groups["low"].append(s)
        elif ratio > 1.3:
            groups["high"].append(s)
        else:
            groups["mid"].append(s)
    # 每个区间最多选10家，按得分降序
    for k in groups:
        groups[k].sort(key=lambda x: x.total_score, reverse=True)
        if len(groups[k]) > 10:
            groups[k] = groups[k][:10]
    return groups


def group_by_brand_origin(results: List[CompetitorScore]) -> Tuple[List[CompetitorScore], List[CompetitorScore]]:
    """按品牌来源分组：外资/内资，每组最多10家"""
    foreign = []
    domestic = []
    foreign_brands = ["洲际", "皇冠假日", "万豪", "希尔顿", "香格里拉", "凯悦", "君悦", "威斯汀", "万丽", "四季", "丽思卡尔顿"]
    for s in results:
        brand = s.hotel.brand
        is_foreign = any(f in brand for f in foreign_brands)
        if is_foreign:
            foreign.append(s)
        else:
            domestic.append(s)
    # 排序截断
    foreign.sort(key=lambda x: x.total_score, reverse=True)
    domestic.sort(key=lambda x: x.total_score, reverse=True)
    if len(foreign) > 10:
        foreign = foreign[:10]
    if len(domestic) > 10:
        domestic = domestic[:10]
    return foreign, domestic


# ── 自动半径扩展 ─────────────────────────────────────────────

def expand_search_radius_if_needed(
    hotels: List[HotelPOI],
    target_hotel: HotelPOI,
    base_price: int,
    current_radius: float,
    config: FilterConfig,
    min_required: int = 3,
) -> Tuple[List[CompetitorScore], List[CompetitorScore], bool]:
    """
    如果强相关竞品太少，自动向外扩展搜索半径
    5km → 10km → 15km

    返回：(all_candidates, strong_relevant, expanded)
    """
    current_config = FilterConfig(**config.__dict__)
    current_config.max_distance_km = current_radius

    # 统计当前半径
    all_candidates: List[CompetitorScore] = []
    strong_relevant: List[CompetitorScore] = []
    for h in hotels:
        if h.distance_km and h.distance_km <= current_config.max_distance_km:
            score = score_competitor_v2(h, target_hotel, base_price, current_config)
            all_candidates.append(score)
            if score.is_valid and score.total_score >= config.min_score:
                strong_relevant.append(score)

    if len(strong_relevant) >= min_required:
        return all_candidates, strong_relevant, False

    # 扩展到10km
    print(f"  ℹ️ 当前{current_radius}km仅找到{len(strong_relevant)}家有效竞品，自动扩展到10km...")
    current_config.max_distance_km = 10.0
    all_candidates = []
    strong_relevant = []
    for h in hotels:
        if h.distance_km and h.distance_km <= current_config.max_distance_km:
            score = score_competitor_v2(h, target_hotel, base_price, current_config)
            all_candidates.append(score)
            if score.is_valid and score.total_score >= config.min_score:
                strong_relevant.append(score)
    if len(strong_relevant) >= min_required:
        return all_candidates, strong_relevant, True

    # 扩展到15km
    print(f"  ℹ️ 10km仅找到{len(strong_relevant)}家有效竞品，自动扩展到15km...")
    current_config.max_distance_km = 15.0
    all_candidates = []
    strong_relevant = []
    for h in hotels:
        if h.distance_km and h.distance_km <= current_config.max_distance_km:
            score = score_competitor_v2(h, target_hotel, base_price, current_config)
            all_candidates.append(score)
            if score.is_valid and score.total_score >= config.min_score:
                strong_relevant.append(score)
    return all_candidates, strong_recent, True


# ── 核心入口 ───────────────────────────────────────────────

def filter_competitors_v2(
    hotels: List[HotelPOI],
    target_hotel: HotelPOI,
    base_price: int,
    config: Optional[FilterConfig] = None,
) -> List[CompetitorScore]:
    """
    v2筛选：分层筛选 → 异常值过滤 → TopN输出
    保持向后兼容
    """
    if config is None:
        config = FilterConfig()

    # Step 1: 初步评分筛选（只硬过滤超远距，其他都保留）
    results = []
    price_candidates = []
    for h in hotels:
        score = score_competitor_v2(
            hotel=h,
            target_hotel=target_hotel,
            base_price=base_price,
            config=config
        )
        if score.is_valid and score.total_score >= config.min_score:
            results.append(score)
            if h.price:
                price_candidates.append(h.price)

    # Step 2: 价格异常值过滤（如果开启）
    valid_results = results
    if config.enable_outlier_filter and len(price_candidates) >= 4:
        is_normal_map = {p: norm for p, norm in
                         zip(price_candidates, filter_price_outliers(price_candidates))}
        valid_results = [s for s in results
                   if s.hotel.price is None or
                   is_normal_map.get(s.hotel.price, True)]

    # Step 3: 按得分排序，取Top N
    valid_results.sort(key=lambda x: x.total_score, reverse=True)
    if config.top_n > 0 and len(valid_results) > config.top_n:
        valid_results = valid_results[:config.top_n]

    return valid_results


def filter_competitors_grouped(
    hotels: List[HotelPOI],
    target_hotel: HotelPOI,
    base_price: int,
    config: Optional[FilterConfig] = None,
    auto_expand_min: int = 3,
) -> GroupedCompetitors:
    """
    分组筛选竞品，满足决策者对完整市场格局的认知需求：
    - 强相关（Top得分，用于AI调价分析）
    - 外资品牌竞品 / 内资品牌竞品 → 分组展示，每组最多10家
    - 价格区间分组（低/中/高）→ 每个区间最多10家
    - 自动半径扩展（5→10→15km）如果竞品太少

    使用这个入口替代filter_competitors_v2，可以给决策者完整市场图景
    """
    if config is None:
        config = FilterConfig()

    original_radius = config.max_distance_km
    expanded = False

    # 第一步：评分得到所有候选
    all_candidates: List[CompetitorScore] = []
    strong_relevant: List[CompetitorScore] = []

    all_candidates, strong_relevant, expanded = expand_search_radius_if_needed(
        hotels, target_hotel, base_price, original_radius, config, auto_expand_min
    )

    # 异常值过滤只过滤强相关
    if config.enable_outlier_filter and len([s for s in strong_relevant if s.hotel.price]) >= 4:
        price_candidates = [s.hotel.price for s in strong_relevant if s.hotel.price]
        is_normal_map = {p: norm for p, norm in
                         zip(price_candidates, filter_price_outliers(price_candidates))}
        strong_relevant = [s for s in strong_relevant
                   if s.hotel.price is None or
                   is_normal_map.get(s.hotel.price, True)]

    # 强相关排序截断
    strong_relevant.sort(key=lambda x: x.total_score, reverse=True)
    if config.top_n > 0 and len(strong_relevant) > config.top_n:
        strong_relevant = strong_relevant[:config.top_n]

    # 分组：外资 / 内资
    foreign, domestic = group_by_brand_origin(all_candidates)

    # 分组：价格区间 low/mid/high
    price_groups = group_by_price_tier(all_candidates, base_price)

    # 恢复原配置半径
    config.max_distance_km = original_radius

    return GroupedCompetitors(
        strong_relevant=strong_relevant,
        foreign_brands=foreign,
        domestic_brands=domestic,
        by_price_tier=price_groups,
        all_candidates=all_candidates,
        auto_expanded=expanded,
    )


# ── 根据场景预设配置 ──────────────────────────────────────────

def get_config_for_scenario(scenario: str) -> FilterConfig:
    """
    根据不同场景返回预设权重配置
    - downtown: 市中心店 → 距离更重要
    - resort: 度假景区 → 星级品牌更重要
    - price_battle: 价格战区域 → 价格更重要
    """
    config = FilterConfig()
    if scenario == "downtown":
        config.weight_distance = 0.40
        config.weight_star = 0.25
        config.weight_brand = 0.15
        config.weight_price = 0.20
    elif scenario == "resort":
        config.weight_distance = 0.20
        config.weight_star = 0.40
        config.weight_brand = 0.25
        config.weight_price = 0.15
        config.max_distance_km = 8.0
    elif scenario == "price_battle":
        config.weight_distance = 0.25
        config.weight_star = 0.25
        config.weight_brand = 0.10
        config.weight_price = 0.40
        config.max_distance_km = 10.0
    return config


# ── 快速测试 ──────────────────────────────────────────────

if __name__ == "__main__":
    target = HotelPOI(
        name="天津瑞湾开元名都",
        location="117.745689,39.021567",
        star="高档型",
        brand="开元",
        price=443
    )

    candidates = [
        HotelPOI(name="天津于家堡洲际", location="117.701234,39.012345",
                 star="五星级", brand="洲际", price=916, distance_km=4.2, occupancy="满房"),
        HotelPOI(name="天津滨海皇冠假日", location="117.689012,39.023456",
                 star="五星级", brand="皇冠假日", price=848, distance_km=5.1),
        HotelPOI(name="天津泰达万豪", location="117.723456,39.034567",
                 star="五星级", brand="万豪", price=812, distance_km=2.8, occupancy="high"),
        HotelPOI(name="天津生态城希尔顿", location="117.744378,39.126655",
                 star="五星级", brand="希尔顿", price=558, distance_km=11.7),
        HotelPOI(name="天津泰达中心", location="117.690659,39.035478",
                 star="四星级", brand="泰达", price=333, distance_km=5.2),
        # 加入一个异常低价测试
        HotelPOI(name="促销特价酒店", location="117.710000,39.020000",
                 star="高档型", brand="test", price=199, distance_km=3.0),
        # 加入一个异常高价测试
        HotelPOI(name="节日天价酒店", location="117.715000,39.025000",
                 star="高档型", brand="test2", price=1999, distance_km=3.5),
    ]

    print("\n📍 默认配置测试:")
    filtered = filter_competitors_v2(candidates, target, base_price=443)
    print(f"有效竞品：{len(filtered)}家\n")
    for s in filtered:
        print(f"✅ {s.hotel.name:<15} | 总分:{s.total_score:>5} | +{s.occupancy_bonus}（{s.reason}）")

    print("\n📍 分组展示测试（downtown场景）:")
    config = get_config_for_scenario("downtown")
    grouped = filter_competitors_grouped(candidates, target, 443, config=config)
    print(f"\n强相关：{len(grouped.strong_relevant)}家")
    for s in grouped.strong_relevant:
        print(f"  ✅ {s.hotel.name}: {s.total_score}")
    print(f"\n外资品牌：{len(grouped.foreign_brands)}家")
    for s in grouped.foreign_brands[:5]:
        print(f"  {s.hotel.name}: {s.total_score}")
    print(f"\n内资品牌：{len(grouped.domestic_brands)}家")
    print(f"\n价格区间：")
    for k, v in grouped.by_price_tier.items():
        print(f"  {k}: {len(v)}家")
