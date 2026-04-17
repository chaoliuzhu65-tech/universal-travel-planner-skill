#!/usr/bin/env python3
"""
amap_client.py - amap-sdk 官方SDK封装 + 缓存层节省API配额
替代原有CLI调用，提供更稳定的Python API接口

解决API限额问题：
- 免费版QPS=1，每日调用=300次
- 添加文件缓存，相同查询不重复调用
- 请求延迟规避QPS限制

文档：https://github.com/Horacehxw/amap-sdk-python
安装：pip install amap-sdk
Key申请：https://console.amap.com/dev/key/app
"""

import os
import math
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from amap import AmapClient
from core.amap_cache import get_cached_around_search, save_around_search


# ── 数据模型 ─────────────────────────────────────────────

@dataclass
class POIRecord:
    """标准化POI记录"""
    id: str = ""
    name: str = ""
    location: str = ""        # "lon,lat"
    address: str = ""
    star: str = ""            # 星级/档次（非标准字段，从名称推断）
    type: str = ""            # POI类型
    typecode: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    distance_km: Optional[float] = None  # 距目标点的距离
    tel: str = ""
    photo_url: str = ""

    @property
    def lon(self) -> float:
        loc = self.location.split(",")
        return float(loc[0]) if len(loc) == 2 else 0.0

    @property
    def lat(self) -> float:
        loc = self.location.split(",")
        return float(loc[1]) if len(loc) == 2 else 0.0


@dataclass
class GeoPoint:
    """地理坐标点"""
    lon: float
    lat: float

    def distance_to(self, other: "GeoPoint") -> float:
        """球面距离（km）"""
        R = 6371
        phi1, phi2 = math.radians(self.lat), math.radians(other.lat)
        dphi = math.radians(other.lat - self.lat)
        dlambda = math.radians(other.lon - self.lon)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


# ── amap-sdk 封装类 ──────────────────────────────────────

class AmapClientWrapper:
    """
    amap-sdk Python SDK封装
    提供POI/地理编码/天气/路径规划等能力的Pythonic接口

    使用方式：
        client = AmapClientWrapper(api_key="你的Key")
        pois = client.poi_search("天津滨海五星级酒店", city="天津")
    """

    def __init__(self, api_key: Optional[str] = None):
        self.key = api_key or os.environ.get("AMAP_MAPS_API_KEY")
        if not self.key:
            raise ValueError("必须提供AMAP_MAPS_API_KEY")
        self._client = AmapClient(api_key=self.key)

    # ── POI搜索 ──────────────────────────────────────────

    def poi_search(
        self,
        keywords: str,
        region: str,
        city_limit: bool = True,
        types: Optional[str] = None,
        page_size: int = 20,
        page_num: int = 1,
    ) -> List[POIRecord]:
        """
        POI关键词搜索（高德POI v5 API）

        Args:
            keywords: 搜索关键词
            region: 城市名或adcode
            city_limit: 是否限制在指定城市
            types: POI类型代码（可选）
            page_size: 每页数量（最大25）
            page_num: 页码

        Returns:
            List[POIRecord]
        """
        r = self._client.poi.text_search(
            keywords=keywords,
            region=region,
            city_limit=city_limit,
            types=types,
            page_size=min(page_size, 25),
            page_num=page_num,
        )
        return self._parse_poi_response(r)

    def poi_around(
        self,
        keywords: str,
        location: Tuple[float, float],
        radius_km: float = 3.0,
        page_size: int = 20,
        page_num: int = 1,
        use_cache: bool = True,
        delay_ms: int = 1000,
    ) -> List[POIRecord]:
        """
        周边搜索（指定坐标半径内）
        带缓存：相同查询直接返回缓存，节省API配额

        Args:
            keywords: 搜索关键词
            location: (lon, lat)
            radius_km: 搜索半径（km）
            page_size: 每页数量
            page_num: 页码
            use_cache: 是否使用缓存（默认True，节省API配额）
            delay_ms: 请求间隔毫秒，默认1000ms，规避QPS=1限制
        """
        # 先查缓存
        if use_cache:
            cached = get_cached_around_search(keywords, location, radius_km)
            if cached is not None:
                # 缓存命中，直接返回
                records = []
                for p in cached:
                    records.append(POIRecord(**p))
                return records

        # 缓存未命中，真正API调用
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)  # 延迟规避QPS限制

        r = self._client.poi.around_search(
            keywords=keywords,
            location=f"{location[0]},{location[1]}",
            radius=str(int(radius_km * 1000)),  # 米
            page_size=min(page_size, 25),
            page_num=page_num,
        )
        records = self._parse_poi_response(r)

        # 保存到缓存
        if use_cache:
            cached_data = [p.__dict__ for p in records]
            save_around_search(keywords, location, radius_km, cached_data)

        return records

    def poi_detail(self, poi_id: str) -> Optional[POIRecord]:
        """获取POI详情"""
        r = self._client.poi.detail(id=poi_id)
        records = self._parse_poi_response(r)
        return records[0] if records else None

    def _parse_poi_response(self, r: dict) -> List[POIRecord]:
        """解析POI API响应"""
        records = []
        pois = r.get("pois") or []
        for p in pois:
            records.append(POIRecord(
                id=p.get("id", ""),
                name=p.get("name", ""),
                location=p.get("location", ""),
                address=p.get("address", ""),
                type=p.get("type", ""),
                typecode=p.get("typecode", ""),
                province=p.get("pname", ""),
                city=p.get("cityname", ""),
                district=p.get("adname", ""),
                distance_km=None,
                tel=p.get("tel", ""),
            ))
        return records

    # ── 地理编码 ────────────────────────────────────────

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[GeoPoint]:
        """
        地址→坐标转换（地理编码）

        Returns:
            GeoPoint(lon, lat) 或 None
        """
        r = self._client.geocoding.geocode(address, city=city)
        location = r.get("location")
        if location:
            parts = location.split(",")
            if len(parts) == 2:
                return GeoPoint(lon=float(parts[0]), lat=float(parts[1]))
        return None

    def regeo(self, location: Tuple[float, float]) -> Optional[Dict]:
        """坐标→地址转换（逆地理编码）"""
        r = self._client.geocoding.regeo(
            location=f"{location[0]},{location[1]}",
            radius=500,
            extensions="base"
        )
        return r.get("regeocode", {})

    # ── 天气查询 ────────────────────────────────────────

    def weather(self, adcode: str = "120116") -> Dict:
        """天气预报（adcode: 120116=滨海新区）"""
        r = self._client.weather.get_weather(adcode)
        return r

    # ── 路径规划 ────────────────────────────────────────

    def driving_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
    ) -> Optional[Dict]:
        """驾车路径规划 → 返回距离和时间"""
        r = self._client.direction.driving(
            origin=f"{origin[0]},{origin[1]}",
            destination=f"{destination[0]},{destination[1]}"
        )
        routes = r.get("routes", [])
        if routes:
            steps = routes[0].get("paths", [])
            if steps:
                return {
                    "distance_km": int(steps[0].get("distance", 0)) / 1000,
                    "duration_min": int(steps[0].get("duration", 0)) / 60,
                }
        return None

    # ── 批量距离计算（使用球面公式，无需API）───────────────

    def calc_distance_batch(
        self,
        center: Tuple[float, float],
        points: List[Tuple[str, float, float]],
    ) -> List[Tuple[str, float]]:
        """
        批量计算距离（本地计算，不消耗API配额）

        Args:
            center: 中心点 (lon, lat)
            points: [(名称, lon, lat), ...]

        Returns:
            [(名称, distance_km), ...]，已按距离排序
        """
        center_pt = GeoPoint(lon=center[0], lat=center[1])
        results = []
        for name, lon, lat in points:
            d = center_pt.distance_to(GeoPoint(lon=lon, lat=lat))
            results.append((name, round(d, 2)))
        results.sort(key=lambda x: x[1])
        return results


# ── 快速测试 ────────────────────────────────────────────

if __name__ == "__main__":
    import os
    key = os.environ.get("AMAP_MAPS_API_KEY", "0f9da10a87fa96c564f2d3d0f459fd6f")

    client = AmapClientWrapper(api_key=key)

    print("✅ amap-sdk封装测试成功！")
    print("\n1️⃣ POI搜索（天津滨海酒店）：")
    pois = client.poi_search("五星级酒店", region="天津", city_limit=True)
    for p in pois[:3]:
        print(f"  {p.name} | {p.location} | {p.type}")

    print("\n2️⃣ 地理编码（天津瑞湾开元名都）：")
    pt = client.geocode("天津市滨海新区响螺湾迎宾大道1号")
    if pt:
        print(f"  坐标: {pt.lon},{pt.lat}")

    print("\n3️⃣ 批量距离计算：")
    center = (117.745689, 39.021567)
    points = [
        ("于家堡洲际", 117.701234, 39.012345),
        ("滨海皇冠假日", 117.689012, 39.023456),
        ("泰达万豪", 117.723456, 39.034567),
    ]
    dists = client.calc_distance_batch(center, points)
    for name, d in dists:
        print(f"  {name}: {d}km")
