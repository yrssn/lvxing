-- ============================================================
-- 九旅比价爬虫 数据库初始化脚本（MySQL 5.7+）
-- 用法（二选一）：
--   1) 命令行: mysql -u root -p < schema.sql
--   2) 客户端（Navicat 等）直接打开执行
-- 说明：
--   - 库名/连接信息见 backend/.env（默认库名 lvxing）
--   - 执行后启动后端会自动创建初始管理员账号：admin / admin123
--   - 已有旧表时会自动补列（后端启动时的轻量迁移），本脚本用 IF NOT EXISTS 可重复执行
-- ============================================================

CREATE DATABASE IF NOT EXISTS `lvxing` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `lvxing`;

-- 登录用户（is_admin=1 为管理员，可创建账号）
CREATE TABLE IF NOT EXISTS `user` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password_hash VARCHAR(200) NOT NULL,           -- pbkdf2$100000$salthex$hashhex
  is_admin TINYINT(1) NOT NULL DEFAULT 0,
  is_active TINYINT(1) DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 系统设置（key/value）：cookie、jwt_secret
CREATE TABLE IF NOT EXISTS `app_setting` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  setting_key VARCHAR(50) NOT NULL UNIQUE,
  setting_value TEXT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 航班信息：预存储查询参数（供定时任务选用）
CREATE TABLE IF NOT EXISTS `query_param` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) DEFAULT '',
  domain VARCHAR(20) DEFAULT 'shm',
  dpt VARCHAR(10) NOT NULL,
  arr VARCHAR(10) NOT NULL,
  flight_no VARCHAR(20) DEFAULT '',
  cabin VARCHAR(10) DEFAULT '',
  carrier VARCHAR(10) DEFAULT '',
  enabled TINYINT(1) DEFAULT 1,
  remark VARCHAR(200) DEFAULT '',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 定时任务
CREATE TABLE IF NOT EXISTS `scrape_task` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  interval_days INT NOT NULL DEFAULT 1,          -- 1=每天, 2=隔天...
  time_of_day TIME NOT NULL,                     -- 每日执行时刻
  days_ahead INT NOT NULL DEFAULT 1,             -- 抓取今天+N天后的航班日期
  enabled TINYINT(1) DEFAULT 1,
  status VARCHAR(20) NOT NULL DEFAULT 'idle',    -- idle/running（CAS 防重入用）
  next_run_at DATETIME,                          -- 调度依据
  last_run_at DATETIME,
  last_status VARCHAR(20),                       -- success/partial/failed
  min_delay_sec INT NOT NULL DEFAULT 3,          -- 任务内条目间随机延时下限
  max_delay_sec INT NOT NULL DEFAULT 10,         -- 任务内条目间随机延时上限
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 任务-查询参数关联
CREATE TABLE IF NOT EXISTS `task_param` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  task_id INT NOT NULL, KEY idx_tp_task (task_id),
  param_id INT NOT NULL, KEY idx_tp_param (param_id),
  order_index INT NOT NULL DEFAULT 0,            -- 抓取顺序（延时按此顺序生效）
  UNIQUE KEY uq_task_param (task_id, param_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 任务执行日志
CREATE TABLE IF NOT EXISTS `task_run_log` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  task_id INT NOT NULL, KEY idx_trl_task (task_id),
  trigger_type VARCHAR(20) NOT NULL,             -- schedule / manual
  started_at DATETIME, finished_at DATETIME,
  status VARCHAR(20) NOT NULL,                   -- running/success/partial/failed
  total_params INT DEFAULT 0, ok_params INT DEFAULT 0,
  message VARCHAR(500) DEFAULT '',
  detail JSON                                    -- 每条 param 的 historyId/rowCount/error
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 一次比价查询（手动/定时抓取的历史批次）
CREATE TABLE IF NOT EXISTS `query_history` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  domain VARCHAR(20) DEFAULT 'shm',
  flight_no VARCHAR(20) DEFAULT '',
  dpt VARCHAR(10) DEFAULT '',
  arr VARCHAR(10) DEFAULT '',
  flight_date VARCHAR(20) DEFAULT '',
  cabin VARCHAR(10) DEFAULT '',
  carrier VARCHAR(10) DEFAULT '',
  row_count INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 比价结果明细行
CREATE TABLE IF NOT EXISTS `bidding_record` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  history_id INT NOT NULL,                       -- 关联 query_history.id
  flight_date VARCHAR(20) DEFAULT '',
  dpt VARCHAR(10) DEFAULT '',
  arr VARCHAR(10) DEFAULT '',
  flight_no VARCHAR(20) DEFAULT '',
  main_flight_no VARCHAR(20) DEFAULT '',
  cabin VARCHAR(10) DEFAULT '',
  policy_type VARCHAR(100) DEFAULT '',
  follow_base_price FLOAT,
  sell_price FLOAT,
  external_cabin VARCHAR(10) DEFAULT '',
  self_price FLOAT,
  raw JSON,                                      -- 原始返回行
  source VARCHAR(10) NOT NULL DEFAULT 'manual',  -- manual=手动抓取 task=定时任务
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 数据更新时间
  KEY idx_br_history (history_id),
  KEY idx_br_flight_date (flight_date),
  KEY idx_br_created_at (created_at),
  KEY idx_br_dpt_arr (dpt, arr)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
