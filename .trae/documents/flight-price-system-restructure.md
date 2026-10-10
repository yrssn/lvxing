# 航班比价系统重构：登录 + Element Plus 四模块 + 定时任务

## Context（背景）

现有系统是 Vue3 单页 + FastAPI：手动输入 Cookie 和查询参数抓取 fuwu.jiulvxing.com 比价接口，结果存 MySQL（spider_lvxing 库）。用户要求重构为多模块系统：

1. **登录功能**：多用户账号（可注册），所有 API 鉴权
2. **手动抓取模块**（Element Plus）：功能与现有一致——可选择「抓取进数据库」或「查看抓取的数据」
3. **航班数据模块**：浏览数据库已抓取数据，可筛选日期/航线等；走势图 = 按航班日期聚合的最低价趋势（基于数据库）
4. **航班信息模块**：预存储查询参数 CRUD，供定时任务选用
5. **定时任务模块**：选择若干航班信息参数，按间隔天数（每天/隔天…）+ 每日固定时刻后台自动抓取入库；任务内多条参数间支持可配置随机延时防频繁抓取；有执行日志、启停开关

已确认决策：Cookie 存数据库系统设置（手动/定时共用）；多用户账号；调度粒度 = 间隔天数 + 每日时刻 + 任务内条目间随机延时(min~max 秒)。

依赖增量：后端仅 +`pyjwt`；前端 +`element-plus`、`@element-plus/icons-vue`、`vue-router@4`、`echarts`。

## 后端（backend/）

### 文件结构
| 文件 | 操作 | 职责 |
|---|---|---|
| `models.py` | 新 | 全部 ORM：User、AppSetting、QueryParam、ScrapeTask、TaskParam、TaskRunLog、QueryHistory、BiddingRecord(+source/created_at/索引) |
| `auth.py` | 新 | pbkdf2_hmac 密码哈希；PyJWT HS256 token；`get_current_user` 依赖（401） |
| `scraper.py` | 新 | 手动/任务共用抓取核心：`get_cookie()`（读 app_setting）、`fetch_bidding(params)`（返回 status/data/cookie_invalid）、`scrape_and_save(params, source)` |
| `scheduler.py` | 新 | asyncio 30s 轮询循环 + `run_task()` + `next_run_at` 计算（advance 锚点推进法）+ 启动复位 running→idle |
| `routers/` | 新 | auth.py / settings.py / scrape.py / history.py / params.py / tasks.py / data.py |
| `main.py` | 改 | lifespan（init_db + scheduler 启停）、挂载 router、CORS 保留（替换废弃的 on_event） |
| `db.py` | 改 | 保留 engine/SessionLocal；`ensure_columns()` 轻量迁移（逐条 ALTER，捕获 errno 1060/1061 静默跳过） |
| `config.py` | 改 | +TOKEN_EXPIRE_HOURS=72 |
| `requirements.txt` | 新 | 现有依赖 + pyjwt>=2.8 |

### 新表结构
- **user**: id, username(UNIQUE), password_hash(`pbkdf2$100000$salt$hash`), is_active, created_at
- **app_setting**: setting_key(UNIQUE: 'cookie'/'jwt_secret'), setting_value, updated_at。jwt_secret 首次启动 `secrets.token_hex(32)` 生成持久化，避免重启 token 全失效
- **query_param**: id, name, domain(default shm), dpt, arr, flight_no, cabin, carrier, enabled, remark, created_at
- **scrape_task**: id, name, interval_days(1-30), time_of_day(TIME), enabled, status(idle/running), next_run_at, last_run_at, last_status, min_delay_sec(3), max_delay_sec(10), created_at
- **task_param**: task_id, param_id, order_index, UNIQUE(task_id, param_id)
- **task_run_log**: task_id, trigger_type(schedule/manual), started_at, finished_at, status(running/success/partial/failed), total_params, ok_params, message, detail(JSON 每条 param 的 historyId/rowCount/error)
- **bidding_record 迁移**：+source('manual'/'task', default manual)、+created_at、+索引(flight_date/created_at/dpt_arr)

### API 契约（沿用 `{success, data, message}` 风格）
鉴权白名单仅：POST /api/auth/register、POST /api/auth/login、GET /api/health；其余全部 Bearer token，失败 401。

- **auth**: POST /api/auth/register {username,password}→{id,username}；POST /api/auth/login（JSON body）→{token,username}；GET /api/auth/me
- **scrape**: POST /api/scrape/run {flightNo,dpt,arr,flightDate,cabin,carrier,domain?,save} → {success,status,historyId,raw}（save=true 才入库；替代旧 GET /api/bidding，旧接口删除）
- **history**（原样迁移+鉴权）: GET /api/history?limit、GET /api/history/{id}/records、DELETE /api/history/{id}
- **settings**: GET/PUT /api/settings/cookie（明文，内网工具）；POST /api/settings/test-cookie（服务端试探请求 → {valid,message,status}）
- **params**: GET /api/params、POST /api/params、PUT /api/params/{id}、DELETE /api/params/{id}（删除时级联删 task_param）
- **tasks**: GET /api/tasks（含 paramIds/nextRunAt/lastStatus）；POST /api/tasks {name,intervalDays,timeOfDay,minDelaySec,maxDelaySec,enabled,paramIds[]}；PUT /api/tasks/{id}（running 时 409 拒绝）；DELETE；POST /api/tasks/{id}/toggle {enabled}；POST /api/tasks/{id}/run-now（异步，返回 runId）；GET /api/tasks/{id}/logs?limit
- **data**: GET /api/data/records（筛选 dpt/arr/flightNo/carrier/source/crawlFrom/crawlTo + page/pageSize → {total,items}，按 created_at desc）；GET /api/data/trend（同筛选 → [{flightDate,minSellPrice,minSelfPrice,recordCount}]，GROUP BY flight_date）

### 调度器要点（asyncio 轮询，不引入 APScheduler）
- lifespan 启动 `asyncio.create_task(scheduler_loop())`；启动时先复位 `status='running'→'idle'`（崩溃残留）
- 每 30s 扫描 `enabled=1 AND status='idle' AND next_run_at<=now`；DB CAS 抢占（`UPDATE ... SET status='running' WHERE id=:id AND status='idle'`，rowcount==1 才执行）防双跑；到期任务串行执行
- **advance()**: 以旧 next_run_at 为锚点 while 推进到严格大于 now 的下一执行点（保证隔天语义不漂移，宕机多天自动追上、只补跑一次）
- **run_task 流程**：读 task+params(按 order_index)+cookie → 插 running 日志 → 逐条 scrape_and_save(source='task')，条目间 `asyncio.sleep(random.uniform(min,max))`（首条不延时）→ **cookie 失效立即熔断**终止剩余条目 → 汇总 success/partial/failed → 同事务更新 next_run_at + status='idle'
- run-now：`asyncio.create_task`，进程内 set 防重复点击，不影响 next_run_at
- 时区全链路本地时间（docker TZ=Asia/Shanghai，与 Windows 一致）

## 前端（frontend/）

### 文件结构
- `main.js`: use(ElementPlus)+use(router)+icons 注册
- `App.vue`: 精简为 `<router-view/>`
- `src/api/request.js`: fetch 封装（自动 Bearer、统一 {success,data,message} 解析、401 清 token 跳 /login）
- `src/api/index.js`: 各模块 API 函数
- `src/composables/auth.js`: token/username localStorage
- `src/router/index.js`: 路由表 + 守卫（无 token → /login）
- `src/layouts/MainLayout.vue`: el-container 左侧菜单（手动抓取/航班数据/航班信息/定时任务/系统设置）+ 顶部用户名/退出
- `src/views/`: LoginView（登录/注册 tab）、ManualScrapeView、FlightDataView、FlightInfoView、TaskView、SettingsView
- `src/components/TrendChart.vue`: ECharts 折线（echarts/core 按需注册 LineChart+Grid+Tooltip+Legend）
- `src/utils/csv.js`: 数组转 CSV（\ufeff BOM 防 Excel 乱码）Blob 下载

### 页面要点
- **ManualScrapeView**：还原截图布局——按钮区（查询 / 抓取并入库 / 导出记录 / 刷新数据），内联表单（航司/起飞/到达/航班号/航班日期/舱位），结果 el-table（definedCols 迁移：日期/出发/到达/航班号/主飞航班号/舱位/政策类型/就旅伴外放退改价/全网低价+externalCabin/自有政策），深色日志输出区（前端本地 append 请求时间/参数/行数/耗时，上限 200 条），历史列表回看+删除（=查看抓取的数据）。「查询」save=false、「抓取并入库」save=true
- **FlightDataView**：筛选（日期范围 daterange=crawlFrom/crawlTo、航线、航班号、来源 radio）→ server-side 分页表格 → 导出当前筛选全部页 CSV → 「查看走势」el-dialog 内嵌 TrendChart
- **FlightInfoView**：el-table + 新建/编辑 dialog（dpt/arr 必填、enabled switch）
- **TaskView**：el-table（nextRunAt/lastRunAt/lastStatus el-tag/启停 switch/编辑/立即执行/日志/删除）；新建 dialog（延时区间 el-input-number 校验 min<=max + 参数 el-select multiple）；日志 el-drawer（detail 逐条展开）
- **SettingsView**：cookie textarea + 保存 + 测试 Cookie 按钮

## 实施步骤

1. backend 基建：models.py + db.py 迁移函数 + requirements.txt + 安装 pyjwt 到 spider 环境 → 启动验证建表/加列
2. auth：auth.py + routers/auth.py + main.py 改造 → curl 验证注册/登录/401
3. scraper.py 抽取（cookie 读取+失效判定）+ routers/scrape.py（POST+save 开关）+ settings.py + history.py，全局加鉴权
4. routers/data.py（records+trend）→ curl 验证聚合
5. routers/params.py + routers/tasks.py（CRUD，不含调度）
6. scheduler.py 调度循环 + run_task + run-now
7. 前端：基建（main/router/request/Layout/Login）→ ManualScrapeView → Settings → FlightInfo → Task → FlightData（TrendChart/csv）
8. 端到端联调 + 修复 start-backend.bat python 路径

## 验证

1. 鉴权：curl 注册/登录 → 无 token 访问 /api/history 应 401，带 token 200
2. 手动抓取：「查询」不入库；「抓取并入库」后 SQL 查 source='manual' 且 created_at 有值
3. Cookie 失效路径：垃圾 cookie → 提示失效；测试按钮 valid=false
4. 定时任务：建任务 time_of_day=now+2min 挂 3 条 param → 2 分钟后 task_run_log 出现 schedule 记录、detail 3 条有 historyId、间隔落在延时区间、bidding_record 出现 source='task'、next_run_at 推进次日
5. run-now：手动日志出现，next_run_at 不变
6. 重启恢复：执行中 kill 后端 → 重启后 running 复位、已过期补跑且只跑一次
7. 数据模块：跨 3 天数据 → 走势 3 个点为各日 MIN(sell_price)；分页/筛选/CSV 中文无乱码

## 风险与注意

- **start-backend.bat 写死 `C:\Users\yrssn\...` 路径**，当前机器是 Administrator → 先 `conda env list` 确认实际路径再修 bat；pyjwt 必须装进该 env（PYTHONNOUSERSITE=1）
- create_all 不给已有表加列 → ensure_columns 负责迁移；迁移前建议备份 bidding_record
- uvicorn 必须单 worker（现状即如此）；CAS 已防双跑
- flight_date 是字符串列，依赖 yyyy-MM-dd 格式 → 前端 el-date-picker 天然 ISO，后端正则兜底
- 价格 Float 现状保留，本次不迁 DECIMAL
- JWT secret 持久化到 app_setting，避免重启 token 全失效
