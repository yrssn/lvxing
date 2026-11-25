"""离线回归：真实脱敏响应、模拟时钟和 SQLite，不向航司发送测试请求。"""
import asyncio
import copy
import json
from datetime import date, time, timedelta
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import db
import xiamenair as service
import xiamen_scheduler as scheduler
from xiamen_parser import parse_offers, ResponseFormatError
from models import Base, QueryParam, User, XiamenTask, XiamenTaskLog, XiamenQuery, XiamenOffer
from routers import xiamenair as api

FIXTURE = json.loads((Path(__file__).parent / "fixtures/xiamen_shopping.json").read_text(encoding="utf-8"))


class ParserTests(unittest.TestCase):
    def test_real_prices_promotions_timezone_and_brand_dedup(self):
        rows = parse_offers(FIXTURE)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first['totalAmount'], '1883.00')
        self.assertEqual(first['taxAmount'], '1176.00')
        self.assertEqual(first['route'], ['SHA', 'XMN', 'MEL'])
        self.assertEqual(first['elapsedMinutes'], 2030)
        self.assertEqual(first['transferMinutes'], [1350])
        self.assertEqual(first['promotions'][0]['title'], '限时优惠')
        self.assertEqual(len(first['services']), 3)

    def test_codeshare_exclusion_uses_operator(self):
        payload = copy.deepcopy(FIXTURE)
        offers = payload['result']['offers']
        shared_cabin = payload['result']['odInfos'][0]['flightInfos'][2]['paxCabins']['ADT1'][0]
        offers[shared_cabin['offerId']]['disclosureIds'] = ['154911']
        self.assertEqual(len(parse_offers(payload, True)), 2)
        all_rows = parse_offers(payload, False)
        self.assertEqual(len(all_rows), 3)
        self.assertFalse(all_rows[-1]['allMf'])
        self.assertEqual(all_rows[-1]['segments'][0]['operatingFlightNo'], 'MU5641')

    def test_unknown_disclosure_is_not_silent_no_discount(self):
        payload = copy.deepcopy(FIXTURE)
        payload['result']['refData']['disclosures'].pop('154911')
        with self.assertRaises(ResponseFormatError): parse_offers(payload)

    def test_sold_out_and_nonpromotional_offers_excluded(self):
        payload = copy.deepcopy(FIXTURE)
        payload['result']['odInfos'][0]['flightInfos'][0]['paxCabins']['ADT1'][0]['seatRemains'] = 0
        self.assertEqual(len(parse_offers(payload)), 1)

    def test_malformed_amount_and_shape_fail_closed(self):
        payload = copy.deepcopy(FIXTURE)
        payload['result']['odInfos'][0]['flightInfos'][0]['paxCabins']['ADT1'][0]['totalAmount'] = 'NaN'
        with self.assertRaises(ResponseFormatError): parse_offers(payload)
        with self.assertRaises(ResponseFormatError): parse_offers({'success':True,'code':0,'result':{}})

    def test_empty_valid_result_is_success(self):
        self.assertEqual(parse_offers({'success':True,'code':0,'result':{'odInfos':[],'offers':{},'refData':{}}}), [])

    def test_wrong_flight_date_is_not_saved(self):
        with self.assertRaises(ResponseFormatError): parse_offers(FIXTURE, flight_date=date(2026,11,26))

    def test_stopover_flight_legs_are_excluded(self):
        payload = copy.deepcopy(FIXTURE)
        segment = payload['result']['odInfos'][0]['flightInfos'][0]['segmentIds'][0]
        payload['result']['refData']['segments'][segment]['flightLegs'] = [{}, {}]
        self.assertEqual(len(parse_offers(payload)), 1)


class Clock:
    def __init__(self): self.now = 1795564800.0
    async def sleep(self, seconds): self.now += seconds; await asyncio.sleep(0)


class GateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock(); self.state = {}; self.sent = []
        self.gate = service.RequestGate(load=lambda: copy.deepcopy(self.state), save=self.save,
            clock=lambda: self.clock.now, sleep=self.clock.sleep, uniform=lambda a,b:a)
    def save(self, state): self.state = copy.deepcopy(state)
    async def ok(self):
        self.sent.append(self.clock.now)
        return httpx.Response(200, json={'code':0,'success':True})
    async def test_first_wait_and_spacing(self):
        start = self.clock.now
        await self.gate.send(self.ok)
        await self.gate.send(self.ok)
        self.assertEqual(self.sent, [start+30,start+60])
    async def test_batch_pause(self):
        for _ in range(11): await self.gate.send(self.ok)
        self.assertGreaterEqual(self.sent[10]-self.sent[9],180)
    async def test_daily_cap_survives_new_gate(self):
        self.state = {'day':service.datetime.fromtimestamp(self.clock.now, service.CN_TZ).date().isoformat(),'count':200}
        restored = service.RequestGate(load=lambda: copy.deepcopy(self.state), save=self.save,
            clock=lambda: self.clock.now, sleep=self.clock.sleep, uniform=lambda a,b:a)
        with self.assertRaises(service.CollectionStopped) as cm: await restored.send(self.ok)
        self.assertEqual(cm.exception.kind,'quota'); self.assertEqual(self.sent,[])
    async def test_day_rollover_keeps_active_cooldown(self):
        self.state={'day':'2000-01-01','count':200,'cooldownUntil':self.clock.now+3600,'reason':'cooldown'}
        self.assertEqual(self.gate.state()['count'],0)
        with self.assertRaises(service.CollectionStopped) as cm:await self.gate.send(self.ok)
        self.assertEqual(cm.exception.kind,'cooldown');self.assertEqual(self.sent,[])
    async def test_http200_business_failure_blocks_session(self):
        bad=AsyncMock(return_value=httpx.Response(200,json={'success':False,'code':956100,'tip':'uds-empty'}))
        with self.assertRaises(service.CollectionStopped): await self.gate.send(bad)
        self.assertEqual(bad.await_count,1)
        self.assertTrue(self.state['blocked'])
        with self.assertRaises(service.CollectionStopped): await self.gate.send(self.ok)
        self.assertEqual(self.sent,[])
    async def test_429_respects_retry_after_no_retry(self):
        bad=AsyncMock(return_value=httpx.Response(429,headers={'Retry-After':'7200'},json={}))
        with self.assertRaises(service.CollectionStopped): await self.gate.send(bad)
        self.assertEqual(self.state['cooldownUntil'],self.clock.now+7200)
        self.assertEqual(bad.await_count,1)
        with self.assertRaises(service.CollectionStopped): await self.gate.send(self.ok)
    async def test_cancel_before_request(self):
        with self.assertRaises(service.CollectionStopped) as cm:
            await self.gate.send(self.ok,stopped=lambda:True)
        self.assertEqual(cm.exception.kind,'cancelled'); self.assertEqual(self.sent,[])
    async def test_network_failure_is_counted_and_stopped(self):
        bad=AsyncMock(side_effect=httpx.ConnectError('test'))
        with self.assertRaises(service.CollectionStopped): await self.gate.send(bad)
        self.assertEqual(self.state['count'],1)
        self.assertEqual(self.state['cooldownUntil'],self.clock.now+900)


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions=sessionmaker(bind=self.engine,expire_on_commit=False)
        self.patches=[patch.object(db,'SessionLocal',self.sessions),patch.object(api,'SessionLocal',self.sessions)]
        for p in self.patches: p.start()
        self.app=FastAPI();self.app.include_router(api.router)
        self.app.dependency_overrides[auth.get_current_user]=lambda:User(id=1,username='test',is_admin=1)
        self.app.dependency_overrides[auth.require_admin]=lambda:User(id=1,username='test',is_admin=1)
        self.client=TestClient(self.app)
        with self.sessions() as s:
            s.add_all([QueryParam(id=1,dpt='SHA',arr='MEL',flight_no='WRONG',cabin='Z',carrier='MU'),
                       QueryParam(id=2,dpt='SHA',arr='MEL'),QueryParam(id=3,dpt='LHW',arr='HGH',enabled=0)])
            s.commit()
    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):p.stop()
        self.engine.dispose()
    def task(self,**extra):
        values=dict(name='test',routes=[{'id':1,'dpt':'SHA','arr':'MEL'}],window_mode='rolling',days_ahead=1,
                    days_count=2,interval_days=1,time_of_day=time(9),enabled=0,status='queued',min_delay_sec=30,max_delay_sec=60,mf_only=1)
        values.update(extra)
        with self.sessions() as s:
            t=XiamenTask(**values);s.add(t);s.commit();return t.id
    async def test_routes_only_codes_and_deduplicated(self):
        result=self.client.get('/api/xiamenair/routes').json()['data']
        self.assertEqual(result,[{'id':1,'dpt':'SHA','arr':'MEL'}])
    async def test_task_validation_and_isolation(self):
        body={'name':'sample','routeIds':[1,2],'daysCount':7}
        r=self.client.post('/api/xiamenair/tasks',json=body)
        self.assertEqual(r.status_code,200,r.text)
        task=r.json()['data'];self.assertEqual(task['routes'],[{'id':1,'dpt':'SHA','arr':'MEL'}]);self.assertFalse(task['enabled'])
        for bad in ({'minDelaySec':0},{'daysCount':31},{'daysAhead':90,'daysCount':2},{'routeIds':[999]},{'routeIds':[3]}):
            self.assertIn(self.client.post('/api/xiamenair/tasks',json={**body,**bad}).status_code,[400,422])
    async def test_collection_cache_and_secret_redaction(self):
        service.write_setting(service.SESSION_KEY,{'cookie':'secret-cookie','uds':'secret-uds'})
        fake_gate=service.RequestGate()
        fake_gate.send=AsyncMock(return_value=FIXTURE)
        with patch.object(service,'gate',fake_gate):
            first=await service.collect('SHA','MEL',date(2026,11,25))
            second=await service.collect('SHA','MEL',date(2026,11,25))
            self.assertEqual(first['rowCount'],2);self.assertFalse(first['cached']);self.assertTrue(second['cached'])
            self.assertEqual(fake_gate.send.await_count,1)
            result=self.client.get('/api/xiamenair/settings').text
            self.assertNotIn('secret-cookie',result);self.assertNotIn('secret-uds',result)
        with self.sessions() as s:
            self.assertEqual(s.query(XiamenQuery).count(),1);self.assertEqual(s.query(XiamenOffer).count(),2)
    async def test_empty_latest_query_hides_stale_offers(self):
        with self.sessions() as s:
            q=XiamenQuery(dpt='SHA',arr='MEL',flight_date=date(2026,11,25),source='manual');s.add(q);s.flush()
            s.add(XiamenOffer(query_id=q.id,flight_date=q.flight_date,dpt='SHA',arr='MEL',flight_numbers='MF803',total_amount=1883,currency='CNY',all_mf=1,payload={}))
            s.add(XiamenQuery(dpt='SHA',arr='MEL',flight_date=q.flight_date,source='manual',row_count=0));s.commit()
        self.assertEqual(self.client.get('/api/xiamenair/offers').json()['data']['total'],0)
        self.assertEqual(self.client.get('/api/xiamenair/offers?latest=false').json()['data']['total'],1)
    async def test_concurrent_collects_serial_and_manual_rejected_while_busy(self):
        service.write_setting(service.SESSION_KEY,{'cookie':'secret','uds':'secret'})
        fake_gate=service.RequestGate()
        entered, release=asyncio.Event(),asyncio.Event()
        calls=[]
        async def slow(*args,**kwargs):
            calls.append(1);entered.set();await release.wait();return FIXTURE
        fake_gate.send=slow
        with patch.object(service,'gate',fake_gate):
            first=asyncio.create_task(service.collect('SHA','MEL',date(2026,11,25),True))
            await entered.wait()
            second=asyncio.create_task(service.collect('SHA','MEL',date(2026,11,25),False))
            with self.assertRaises(service.CollectionStopped) as cm:
                await service.collect('SHA','MEL',date(2026,11,25),manual=True)
            self.assertEqual(cm.exception.kind,'busy')
            await asyncio.sleep(0);self.assertEqual(len(calls),1)
            release.set();await asyncio.gather(first,second)
            self.assertEqual(len(calls),2)
    async def test_session_update_preserves_daily_quota_and_cooldown(self):
        fake_gate=service.RequestGate()
        state=fake_gate.state();state.update(count=100,blocked=True,cooldownUntil=service.time.time()+3600,reason='cooldown')
        fake_gate.save(state)
        with patch.object(service,'gate',fake_gate):await service.save_session('new-cookie','new-uds')
        restored=fake_gate.state();self.assertEqual(restored['count'],100);self.assertFalse(restored['blocked'])
        self.assertGreater(restored['cooldownUntil'],service.time.time())
    async def test_tasks_over_request_budget_rejected(self):
        with self.sessions() as s:
            for i in range(10,18):s.add(QueryParam(id=i,dpt='SHA',arr='AA'+chr(65+i-10)))
            s.commit()
        r=self.client.post('/api/xiamenair/tasks',json={'name':'too large','routeIds':list(range(10,18)),'daysCount':30})
        self.assertEqual(r.status_code,400)
    async def test_task_progress_only_origin_destination_and_dates(self):
        tid=self.task()
        fake=AsyncMock(return_value={'queryId':1,'rowCount':2,'cached':False,'message':'ok'})
        with patch.object(service,'collect',fake):await scheduler.run_task(tid,'manual')
        self.assertEqual(fake.await_count,2)
        self.assertEqual(fake.await_args_list[0].args[:2],('SHA','MEL'))
        with self.sessions() as s:
            log=s.query(XiamenTaskLog).one();self.assertEqual(log.completed,2);self.assertEqual(log.offer_count,4)
            self.assertEqual(s.get(XiamenTask,tid).status,'idle')
    async def test_session_failure_stops_remaining_days_and_disables(self):
        tid=self.task(enabled=1)
        fake=AsyncMock(side_effect=service.CollectionStopped('session invalid','session'))
        with patch.object(service,'collect',fake):await scheduler.run_task(tid,'schedule')
        self.assertEqual(fake.await_count,1)
        with self.sessions() as s:
            t=s.get(XiamenTask,tid);self.assertEqual(t.enabled,0);self.assertIsNone(t.next_run_at)
            log=s.query(XiamenTaskLog).one();self.assertEqual(log.status,'blocked');self.assertEqual(len(log.detail),1)
    async def test_stop_before_task_sends_nothing(self):
        tid=self.task(stop_requested=1)
        fake=AsyncMock()
        with patch.object(service,'collect',fake):await scheduler.run_task(tid,'manual')
        fake.assert_not_awaited()
        with self.sessions() as s:self.assertEqual(s.query(XiamenTaskLog).one().status,'cancelled')
    async def test_fixed_dates_skip_past_and_expire(self):
        today=service.now_cn().date()
        tid=self.task(window_mode='fixed',fixed_date_from=today-timedelta(days=2),fixed_date_to=today-timedelta(days=1),enabled=1)
        fake=AsyncMock()
        with patch.object(service,'collect',fake):await scheduler.run_task(tid,'schedule')
        fake.assert_not_awaited()
        with self.sessions() as s:self.assertEqual(s.get(XiamenTask,tid).enabled,0)
    async def test_queued_cancel_does_not_wait_for_running_task(self):
        tid=self.task()
        lock=asyncio.Lock();await lock.acquire()
        with patch.object(scheduler,'_execution_lock',lock):
            job=asyncio.create_task(scheduler.run_task(tid,'manual'))
            await asyncio.sleep(0)
            self.client.post(f'/api/xiamenair/tasks/{tid}/stop')
            await asyncio.wait_for(job,3)
        lock.release()
        with self.sessions() as s:self.assertEqual(s.query(XiamenTaskLog).one().status,'cancelled')


if __name__ == '__main__': unittest.main()
