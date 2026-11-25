"""厦航独立采集服务：会话、持久化限速、优惠快照。必须单 worker 运行。"""
import asyncio
import json
import random
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from models import AppSetting, XiamenOffer, XiamenQuery
from xiamen_parser import ResponseFormatError, parse_offers

URL = "https://csapi-2a.xiamenair.com/offer/api/v3/offer/shopping?preBusiness=0&type=I"
DAILY_LIMIT = 200
MAX_TASK_REQUESTS = 200
MAX_DAYS = 30
MIN_DELAY = 30
SESSION_KEY = "xiamenair_session"
STATE_KEY = "xiamenair_rate_state"
CN_TZ = timezone(timedelta(hours=8))


def now_cn():
    return datetime.now(CN_TZ).replace(tzinfo=None)


class CollectionStopped(Exception):
    def __init__(self, message, kind="stopped"):
        super().__init__(message)
        self.kind = kind


def read_setting(key):
    from db import SessionLocal
    with SessionLocal() as db:
        row = db.query(AppSetting).filter_by(setting_key=key).first()
        return json.loads(row.setting_value) if row and row.setting_value else {}


def write_setting(key, value):
    from db import SessionLocal
    with SessionLocal() as db:
        row = db.query(AppSetting).filter_by(setting_key=key).first()
        if row is None:
            row = AppSetting(setting_key=key)
            db.add(row)
        row.setting_value = json.dumps(value, ensure_ascii=False)
        db.commit()


def request_body(origin, destination, flight_date):
    return {
        "shoppingPreference": {
            "pricingMode": "Money", "wantSoldOut": True,
            "connectionPreference": {"maxConnectionQuantity": -1},
            "flightPreference": {"cabinCombineMode": "Cabin", "lowestFare": True,
                                 "productPreferences": [{"productType": "Flight"}]},
        },
        "cabinClasses": ["Economy", "Business", "First"],
        "passengerCount": {"adult": 1, "child": 0, "infant": 0},
        "itineraries": [{"departureDate": str(flight_date), "origin": {"airport": {"code": origin}},
                         "destination": {"airport": {"code": destination}}}],
    }


def response_error(response, data):
    """不要把 HTTP 200 当作业务成功，也不要把限流当作无优惠。"""
    code, tip = data.get("code"), str(data.get("tip", "")).lower()
    if response.status_code == 401 or code == 1001 or "uds-empty" in tip or "token" in tip or "登录" in tip:
        return "session", "厦航会话已失效或缺失，请更新 Cookie 和 uds；本次采集已停止"
    if response.status_code in (403, 429) or code == 956100 or any(k in tip for k in ("captcha", "验证", "频繁", "风控")):
        return "risk", "厦航返回限流或验证要求，本次采集已停止并进入冷却"
    if response.status_code != 200 or data.get("success") is not True or code != 0:
        return "upstream", "厦航接口暂不可用或返回业务错误，本次采集已停止，15 分钟后再检查"
    return None


def retry_after_seconds(value, now):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return 0


class RequestGate:
    """所有厦航入口共用一个锁；计数和冷却写库，重启不清空限制。"""
    def __init__(self, load=None, save=None, clock=None, sleep=None, uniform=None):
        self.lock = asyncio.Lock()
        self.load = load or (lambda: read_setting(STATE_KEY))
        self.save = save or (lambda state: write_setting(STATE_KEY, state))
        self.clock = clock or time.time
        self.sleep = sleep or asyncio.sleep
        self.uniform = uniform or random.uniform

    def state(self):
        state = self.load()
        today = datetime.fromtimestamp(self.clock(), CN_TZ).date().isoformat()
        if state.get("day") != today:
            state.update(day=today, count=0)
        return state

    def check(self, state):
        if state.get("blocked"):
            raise CollectionStopped(state.get("reason", "请更新厦航会话"), "session")
        if state.get("cooldownUntil", 0) > self.clock():
            raise CollectionStopped(state.get("reason", "厦航采集冷却中"), "cooldown")
        if state.get("count", 0) >= DAILY_LIMIT:
            raise CollectionStopped("厦航今日请求已达 200 次，今天不再发送请求", "quota")

    async def wait(self, until, stopped=None, progress=None):
        if progress:
            progress("等待请求间隔，预计 " + datetime.fromtimestamp(until, CN_TZ).strftime("%H:%M:%S") + " 发送")
        while self.clock() < until:
            if stopped and stopped():
                raise CollectionStopped("已停止；已完成的数据保留", "cancelled")
            await self.sleep(min(2, until - self.clock()))
        if stopped and stopped():
            raise CollectionStopped("已停止；已完成的数据保留", "cancelled")

    async def send(self, operation, min_delay=30, max_delay=60, stopped=None, progress=None):
        # 调用方须持锁；首次请求同样等待，多个任务不会各自突发请求。
        state = self.state()
        self.check(state)
        lo, hi = max(MIN_DELAY, min_delay), max(MIN_DELAY, min_delay, max_delay)
        until = max(state.get("nextAllowed", 0), self.clock() + self.uniform(lo, hi))
        state["nextAllowed"] = until
        self.save(state)
        await self.wait(until, stopped, progress)
        state = self.state()
        self.check(state)
        state["count"] = state.get("count", 0) + 1
        # 请求前持久化计数及保守的崩溃恢复间隔。
        state["nextAllowed"] = self.clock() + 90
        self.save(state)
        if progress:
            progress("正在查询厦航；单次最多等待 45 秒")
        try:
            response = await operation()
            try:
                data = response.json()
                if not isinstance(data, dict):
                    data = {}
            except ValueError:
                data = {}
            error = response_error(response, data)
            if error:
                kind, message = error
                self.fail(state, kind, message, response.headers.get("retry-after"))
                raise CollectionStopped(message, kind)
        except httpx.HTTPError:
            message = "厦航网络请求失败，已停止；15 分钟冷却后再检查"
            self.fail(state, "network", message)
            raise CollectionStopped(message, "network") from None
        state["nextAllowed"] = self.clock() + self.uniform(lo, hi)
        if state["count"] % 10 == 0:
            state["nextAllowed"] = max(state["nextAllowed"], self.clock() + self.uniform(180, 300))
        state["reason"] = ""
        self.save(state)
        return data

    def fail(self, state, kind, message, retry_after=None):
        if kind == "session":
            state["blocked"] = True
        else:
            delay = 3600 if kind == "risk" else 900
            state["cooldownUntil"] = self.clock() + max(delay, retry_after_seconds(retry_after, self.clock()))
        state["reason"] = message
        self.save(state)


gate = RequestGate()


def public_settings():
    session, state = read_setting(SESSION_KEY), gate.state()
    return {
        "configured": bool(session.get("cookie") and session.get("uds")),
        "updatedAt": session.get("updatedAt", ""), "dailyLimit": DAILY_LIMIT,
        "todayCount": state.get("count", 0), "blocked": bool(state.get("blocked")),
        "reason": state.get("reason", ""), "busy": gate.lock.locked(),
        "cooldownUntil": datetime.fromtimestamp(state["cooldownUntil"], CN_TZ).isoformat() if state.get("cooldownUntil", 0) > time.time() else "",
        "nextAllowed": datetime.fromtimestamp(state["nextAllowed"], CN_TZ).isoformat() if state.get("nextAllowed", 0) > time.time() else "",
    }


async def save_session(cookie, uds):
    if gate.lock.locked():
        raise CollectionStopped("采集中，请先停止任务并等当前请求结束后更新会话", "busy")
    async with gate.lock:
        write_setting(SESSION_KEY, {"cookie": cookie, "uds": uds, "updatedAt": now_cn().isoformat(timespec="seconds")})
        state = gate.state()
        state["blocked"] = False
        if state.get("cooldownUntil", 0) <= time.time():
            state["reason"] = ""
        gate.save(state)  # 更新会话不清空当天配额或风控冷却


def query_result(query, rows, cached=False):
    return {"queryId": query.id, "rowCount": len(rows), "rows": rows, "cached": cached,
            "capturedAt": query.created_at.isoformat(), "message": "命中近 10 分钟采集结果，未发送新请求" if cached else (f"已保存 {len(rows)} 条限时优惠" if rows else "查询成功，未发现符合条件的限时优惠")}


async def collect(origin, destination, flight_date, mf_only=True, task_id=None,
                  min_delay=30, max_delay=60, stopped=None, progress=None, manual=False):
    from db import SessionLocal
    if manual and gate.lock.locked():
        raise CollectionStopped("厦航已有查询正在等待或执行，请稍后查看任务进度", "busy")
    async with gate.lock:
        if stopped and stopped():
            raise CollectionStopped("已停止；已完成的数据保留", "cancelled")
        with SessionLocal() as db:
            recent = db.query(XiamenQuery).filter_by(dpt=origin, arr=destination, flight_date=flight_date,
                                                    mf_only=int(mf_only)).order_by(XiamenQuery.id.desc()).first()
            if recent and recent.created_at >= now_cn() - timedelta(minutes=10):
                rows = [r.payload for r in db.query(XiamenOffer).filter_by(query_id=recent.id).all()]
                return query_result(recent, rows, True)
        session = read_setting(SESSION_KEY)
        if not session.get("cookie") or not session.get("uds"):
            raise CollectionStopped("请先配置厦航 Cookie 和 uds", "session")
        headers = {"Accept": "application/json", "Origin": "https://cdn-mfemas.xiamenair.com",
                   "Referer": "https://cdn-mfemas.xiamenair.com/", "av": "7.0.0", "channel": "M_WEBSITE",
                   "device": "mini", "os": "ios", "plat": "M_WEBSITE", "Cookie": session["cookie"],
                   "uds": session["uds"], "User-Agent": "Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36 (KHTML, like Gecko) Edg/158.0.0.0 Mobile Safari/537.36"}
        async def operation():
            async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
                return await client.post(URL, headers=headers, json=request_body(origin, destination, flight_date))
        data = await gate.send(operation, min_delay, max_delay, stopped, progress)
        try:
            rows = parse_offers(data, mf_only, flight_date)
        except ResponseFormatError as e:
            gate.fail(gate.state(), "schema", str(e))
            raise CollectionStopped(str(e), "schema") from e
        with SessionLocal() as db:
            query = XiamenQuery(dpt=origin, arr=destination, flight_date=flight_date, task_id=task_id,
                                mf_only=int(mf_only), source="task" if task_id else "manual",
                                row_count=len(rows), created_at=now_cn())
            db.add(query)
            db.flush()
            for row in rows:
                db.add(XiamenOffer(query_id=query.id, flight_date=flight_date, dpt=row["dpt"], arr=row["arr"],
                                   flight_numbers=row["flightNo"], total_amount=row["totalAmount"],
                                   base_amount=row["baseAmount"], currency=row["currency"], all_mf=int(row["allMf"]),
                                   payload=row, created_at=query.created_at))
            db.commit()
            return query_result(query, rows)
