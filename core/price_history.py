#!/usr/bin/env python3
"""
price_history.py - 价格历史存储模块
将每次飞猪价格查询存储到飞书多维表格，跟踪价格趋势

存储内容：
- 酒店ID/名称
- 日期
- 价格
- 采集时间

需要飞书APP ID/Secret授权，多维表格 URL
"""

import os
import json
import requests
from datetime import datetime
from typing import Optional, List, Dict

class PriceHistoryStorage:
    """价格历史存储到飞书多维表格"""

    def __init__(self, app_id: str = None, app_secret: str = None,
                 app_token: str = None, table_id: str = None):
        self.app_id = app_id or os.environ.get("FEISHU_APP_ID")
        self.app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET")
        self.app_token = app_token or os.environ.get("PRICE_HISTORY_APP_TOKEN")
        self.table_id = table_id or os.environ.get("PRICE_HISTORY_TABLE_ID")
        self._token = None

    def get_access_token(self) -> Optional[str]:
        """获取飞书tenant access token"""
        if self._token:
            return self._token
        if not self.app_id or not self.app_secret:
            print("[WARN] FEISHU_APP_ID 或 FEISHU_APP_SECRET 未配置")
            return None

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            self._token = data.get("tenant_access_token")
            return self._token
        print(f"[ERROR] 获取token失败: {data}")
        return None

    def add_record(self, hotel_name: str, target_date: str, price: int,
                  base_price: int = None, competitor: str = None,
                  source: str = "flyai") -> bool:
        """添加一条价格记录

        字段:
        - 酒店名称
        - 目标日期
        - 当前价格
        - 平日基准价
        - 竞品名称（多个用逗号分隔）
        - 采集时间
        - 数据源
        """
        token = self.get_access_token()
        if not token:
            return False

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"

        now = datetime.now().isoformat()

        fields = {
            "酒店名称": hotel_name,
            "目标日期": target_date,
            "当前价格": price,
            "平日基准价": base_price if base_price else "",
            "竞品": competitor if competitor else "",
            "采集时间": now,
            "数据源": source,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        body = {"fields": fields}
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            print(f"[OK] 价格记录已保存到多维表格: {hotel_name} {target_date} ¥{price}")
            return True
        else:
            print(f"[ERROR] 保存失败: {data.get('msg')}")
            return False

    def query_records(self, hotel_name: str, target_date: str = None):
        """查询酒店历史价格"""
        token = self.get_access_token()
        if not token:
            return None

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"

        # filter 这里需要飞书新版 API
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        return data


def get_default_storage() -> Optional[PriceHistoryStorage]:
    """获取默认实例，从环境变量读取配置"""
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    app_token = os.environ.get("PRICE_HISTORY_APP_TOKEN")
    table_id = os.environ.get("PRICE_HISTORY_TABLE_ID")

    if not all([app_id, app_secret, app_token, table_id]):
        print("[INFO] 价格历史存储未完全配置，将不保存历史记录")
        return None

    return PriceHistoryStorage(app_id, app_secret, app_token, table_id)

