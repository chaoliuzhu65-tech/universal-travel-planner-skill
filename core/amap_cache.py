#!/usr/bin/env python3
"""
amap_cache.py - 高德API调用缓存，节省API配额
解决：
- 免费版QPS=1，每日限额300次
- 重复查询相同位置直接用缓存，不耗API

缓存存储：
- JSON文件存储在 `.cache/amap/`
- 按关键词+坐标+半径hash命名
- 永不过期（POI不会经常变）
"""

import os
import json
import hashlib
from typing import List, Dict, Optional, Any

CACHE_DIR = ".cache/amap"

def _get_cache_key(keywords: str, location: tuple[float, float], radius_km: float) -> str:
    """生成缓存key"""
    loc_str = f"{location[0]:.6f},{location[1]:.6f}"
    key_str = f"{keywords}_{loc_str}_{radius_km:.1f}"
    return hashlib.md5(key_str.encode()).hexdigest()[:16]

def _ensure_cache_dir():
    """确保缓存目录存在"""
    os.makedirs(CACHE_DIR, exist_ok=True)

def get_cached_around_search(keywords: str, location: tuple[float, float], radius_km: float) -> Optional[List[Dict]]:
    """获取缓存的周边搜索结果"""
    _ensure_cache_dir()
    key = _get_cache_key(keywords, location, radius_km)
    cache_path = os.path.join(CACHE_DIR, f"{key}.json")
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None

def save_around_search(keywords: str, location: tuple[float, float], radius_km: float, data: List[Dict]):
    """保存周边搜索结果到缓存"""
    _ensure_cache_dir()
    key = _get_cache_key(keywords, location, radius_km)
    cache_path = os.path.join(CACHE_DIR, f"{key}.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_cache_stats() -> Dict[str, Any]:
    """获取缓存统计"""
    _ensure_cache_dir()
    files = os.listdir(CACHE_DIR)
    total = len([f for f in files if f.endswith(".json")])
    size = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) for f in files if f.endswith(".json"))
    return {
        "cached_entries": total,
        "total_size_bytes": size
    }
