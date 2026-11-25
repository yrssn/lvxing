"""厦航 shopping 响应解析。只把明确关联 Pricing 优惠的整程报价入库。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re


class ResponseFormatError(ValueError):
    pass


def money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise InvalidOperation
        return str(number.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError, TypeError):
        raise ResponseFormatError("厦航报价金额格式变化，已停止采集")


def location(value):
    return {k: value.get(k) for k in (
        "iataLocationCode", "iataLocationName", "stationName", "terminalName",
        "aircraftScheduledDateTime", "timeZone",
    )}


def moment(value):
    t = datetime.fromisoformat(value["aircraftScheduledDateTime"])
    return t.replace(tzinfo=timezone(timedelta(minutes=value["timeZone"]["offset"])))


def limited_promotions(offer, disclosures):
    result = []
    for did in offer.get("disclosureIds", []):
        d = disclosures.get(did)
        if d is None:
            raise ResponseFormatError("厦航优惠说明引用缺失，已停止采集")
        if d.get("type") == "Pricing" and (
            d.get("disclosureCode") == "MTMF" or "限时" in d.get("title", "")
        ):
            result.append({"title": d.get("title", "限时优惠"), "code": d.get("disclosureCode"),
                           "description": " ".join(re.sub(r"<[^>]*>", "", v.get("text", ""))
                                                   for v in d.get("descriptions", []))})
    return result


def parse_offers(data, mf_only=True, flight_date=None):
    if data.get("success") is not True or data.get("code") != 0:
        raise ResponseFormatError("厦航查询未成功")
    try:
        result = data["result"]
        od_infos = result["odInfos"]
        offers = result["offers"]
        ref = result["refData"]
        if not isinstance(od_infos, list) or not isinstance(offers, dict):
            raise ResponseFormatError("厦航响应结构变化，已停止采集")
        rows, seen = [], set()
        for od in od_infos:
            for flight in od["flightInfos"]:
                segment_ids = flight["segmentIds"]
                if not segment_ids:
                    raise ResponseFormatError("厦航返回空航段，已停止采集")
                raw_segments = [ref["segments"][sid] for sid in segment_ids]
                if flight_date and raw_segments[0]["departure"]["aircraftScheduledDateTime"][:10] != str(flight_date):
                    raise ResponseFormatError("厦航返回日期与查询日期不一致，已停止采集")
                # 单航段含多个 flightLegs 表示经停，不混入本模块的直飞/联程范围。
                if any(len(s.get("flightLegs", [])) > 1 for s in raw_segments):
                    continue
                all_mf = all(s.get("operatingCarrier", {}).get("carrier", {}).get("code") == "MF"
                             for s in raw_segments)
                if mf_only and not all_mf:
                    continue
                segments = []
                for s in raw_segments:
                    marketing, operating = s["marketingCarrier"], s.get("operatingCarrier", {})
                    segments.append({
                        "flightNo": marketing["carrier"]["code"] + marketing["flightNumber"],
                        "operatingFlightNo": operating.get("carrier", {}).get("code", "") + operating.get("flightNumber", ""),
                        "operatingCarrier": operating.get("carrier", {}).get("code"),
                        "departure": location(s["departure"]), "arrival": location(s["arrival"]),
                        "equipment": s.get("equipment", {}).get("code"),
                        "flightLegs": s.get("flightLegs", []),
                    })
                # 单成人查询，仅用 ADT1，避免 ADT_BRAND 对同一报价的重复展示。
                for cabin in flight["paxCabins"]["ADT1"]:
                    offer = offers[cabin["offerId"]]
                    promotions = limited_promotions(offer, ref.get("disclosures", {}))
                    if not promotions:
                        continue
                    if cabin.get("seatRemains") in (0, "0"):
                        continue
                    journey = ref["paxJourneys"][cabin["paxJourneyId"]]
                    if journey["segmentIds"] != segment_ids:
                        raise ResponseFormatError("厦航报价与航段关联变化，已停止采集")
                    services = journey.get("transferServices", {})
                    total, base = money(cabin["totalAmount"]), money(cabin["baseAmount"])
                    if Decimal(base) > Decimal(total):
                        raise ResponseFormatError("厦航票价税费不一致，已停止采集")
                    row = {
                        "dpt": raw_segments[0]["departure"]["iataLocationCode"],
                        "arr": raw_segments[-1]["arrival"]["iataLocationCode"],
                        "flightNo": " / ".join(s["flightNo"] for s in segments),
                        "route": [raw_segments[0]["departure"]["iataLocationCode"]]
                                 + [s["arrival"]["iataLocationCode"] for s in raw_segments],
                        "allMf": all_mf, "segments": segments,
                        "cabinCodes": cabin.get("cabinCodes", []), "cabinTypes": cabin.get("cabinTypes", []),
                        "totalAmount": total, "baseAmount": base,
                        "taxAmount": str(Decimal(total) - Decimal(base)), "currency": cabin["currency"],
                        "promotions": promotions,
                        "services": [{"type": v.get("transferServiceType"), "name": v.get("serviceContent", {}).get("name", "")}
                                     for v in services.get("availableServiceList", [])],
                        "baggage": cabin.get("baggageDescrition", ""),
                        "elapsedMinutes": int((moment(raw_segments[-1]["arrival"]) - moment(raw_segments[0]["departure"])).total_seconds() / 60),
                        "transferMinutes": [int((moment(b["departure"]) - moment(a["arrival"])).total_seconds() / 60)
                                            for a, b in zip(raw_segments, raw_segments[1:])],
                    }
                    key = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        rows.append(row)
        return rows
    except (KeyError, TypeError, IndexError, ValueError) as e:
        if isinstance(e, ResponseFormatError):
            raise
        raise ResponseFormatError("厦航响应字段变化，已停止采集，请检查适配") from e
