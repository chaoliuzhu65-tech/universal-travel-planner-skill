#!/usr/bin/env python3
"""
data_cache.py - 飞猪数据缓存模块
减少重复API调用，节省Quota，提高速度

缓存策略：
- 按（目的地 + 关键词 + 入住日期 + 退房日期）生成缓存key
- 默认缓存有效期 24 小时（价格一天内不会大变）
- 可强制刷新绕过缓存
"""

import json
import os
from typing import Optional, Any
from datetime import datetime, timedelta


class DataCache:
    """飞猪API查询数据缓存"""

    def __init__(self, cache_dir: str = "./cache", ttl_hours: float = 24.0):
        self.cache_dir = cache_dir
        self.ttl_hours = ttl_hours
        os.makedirs(cache_dir, exist_ok=True)

    def _make_cache_key(self, dest_name: str, keywords: str,
                       check_in: str, check_out: str) -> str:
        """生成缓存key文件名"""
        # 简化处理，替换不安全字符
        key_parts = [
            dest_name.replace(" ", "_").replace("/", "_"),
            keywords.replace(" ", "_").replace("/", "_"),
            check_in,
            check_out
        ]
        return "__".join(key_parts) + ".json"

    def get(self, dest_name: str, keywords: str,
            check_in: str, check_out: str,
            force_refresh: bool = False) -> Optional[Any]:
        """从缓存获取数据，如果有效返回JSON，否则返回None"""

        if force_refresh:
            return None

        cache_file = self._make_cache_key(dest_name, keywords, check_in, check_out)
        cache_path = os.path.join(self.cache_dir, cache_file)

        if not os.path.exists(cache_path):
            return None

        # 检查过期
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
        age = datetime.now() - mtime
        age_hours = age.total_seconds() / 3600.0

        if age_hours > self.ttl_hours:
            # 过期
            return None

        # 读取缓存
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"[WARN] 缓存读取失败: {e}")
            return None

    def set(self, dest_name: str, keywords: str,
            check_in: str, check_out: str,
            data: Any) -> None:
        """写入缓存"""

        cache_file = self._make_cache_key(dest_name, keywords, check_in, check_out)
        cache_path = os.path.join(self.cache_dir, cache_file)

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] 缓存写入失败: {e}")

    def invalidate(self, dest_name: str, keywords: str,
                   check_in: str, check_out: str) -> bool:
        """删除指定缓存"""

        cache_file = self._make_cache_key(dest_name, keywords, check_in, check_out)
        cache_path = os.path.join(self.cache_dir, cache_file)

        if os.path.exists(cache_path):
            os.remove(cache_path)
            return True
        return False

    def clear_expired(self) -> int:
        """清理所有过期缓存，返回清理的数量"""

        cleared = 0
        for fname in os.listdir(self.cache_dir):
            fpath = os.path.join(self.cache_dir, fname)
            if not fname.endswith(".json"):
                continue
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            age = datetime.now() - mtime
            age_hours = age.total_seconds() / 3600.0
            if age_hours > self.ttl_hours:
                os.remove(fpath)
                cleared += 1
        return cleared

    def stats(self) -> dict:
        """获取缓存统计信息"""

        if not os.path.exists(self.cache_dir):
            return {"count": 0, "size_bytes": 0}

        count = 0
        size_bytes = 0
        for fname in os.listdir(self.cache_dir):
            fpath = os.path.join(self.cache_dir, fname)
            if fname.endswith(".json"):
                count += 1
                size_bytes += os.path.getsize(fpath)

        return {
            "count": count,
            "size_bytes": size_bytes,
            "size_kb": round(size_bytes / 1024, 2)
        }


# 单例实例
_default_cache = None

def get_default_cache() -> DataCache:
    """获取默认缓存实例"""
    global _default_cache
    if _default_cache is None:
        _default_cache = DataCache()
    return _default_cache

