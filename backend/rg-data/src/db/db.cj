// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// openGauss 持久化底座：复用 AMS 已验证的纯仓颉驱动（cangjie_tpc::opengauss）。
// 驱动产物在 backend/drv/，由 build.sh 链接。
package rg.data.db

import std.database.sql.*
import std.collection.*
import rg.kernel.error.*
import rg.kernel.log.*
import std.time.*
// 必须显式 import 驱动包以触发其顶层全局初始化器（DriverManager.register("opengauss")）。
// 仅靠 DriverManager.getDriver 反射查找不会链接驱动 .cjo，运行时会报"未找到 opengauss 驱动"。
import cangjie_tpc::opengauss.driver.*
// 连接池：ProxyConnection 的 close() 自动归还而非销毁，避免每次新建握手。
// 注意 std.database.sql 也有同名 PooledDatasource，故用别名避免歧义。
import cangjie_tpc::opengauss.sqlpool.{PooledDatasource as OgPool, PoolConfig as OgPoolConfig}

public class DbConfig {
    public let host: String
    public let port: Int64
    public let database: String
    public let user: String
    public let password: String
    public let maxPoolSize: Int64
    public init(host: String, port: Int64, database: String, user: String, password: String,
                maxPoolSize!: Int64 = 16) {
        this.host = host; this.port = port; this.database = database
        this.user = user; this.password = password
        this.maxPoolSize = maxPoolSize
    }
    /** 连接串：显式超时，避免 DB 抖动导致请求无限挂起（AMS FR-PERF 教训）。 */
    public func url(): String {
        return "opengauss://${user}:${password}@${host}:${port}/${database}" +
               "?sslmode=disable&connection_timeout=5000&read_timeout=15000&write_timeout=15000"
    }
    public func redacted(): String { return "opengauss://${user}:***@${host}:${port}/${database}" }
}

/** 数据库句柄（无连接池，骨架够用；后续可加 PooledDatasource）。 */
public class Database {
    private let ds: Datasource
    public let cfg: DbConfig

    public init(cfg: DbConfig) {
        this.cfg = cfg
        let driver = match (DriverManager.getDriver("opengauss")) {
            case Some(d) => d
            case None => throw AppError(ErrKind.Internal, "未找到 opengauss 驱动")
        }
        let raw = driver.open(cfg.url(), [])
        if (cfg.maxPoolSize > 0) {
            // 🔴 连接生命周期必须小于 openGauss session_timeout(默认10min)，
            // 否则空闲连接被服务端单方断开后池仍持有，拿到僵死连接会挂起 read_timeout。
            // idleTimeout/maxLifeTime 设 5min（<10min），keepAliveTime 1min 主动巡检淘汰。
            let pool = OgPoolConfig(
                Int32(cfg.maxPoolSize), Int32(cfg.maxPoolSize),
                Duration.minute * 5, Duration.minute * 5, Duration.minute * 1)
            this.ds = OgPool(raw, pool)
            Log.info("数据库连接池已建立（max=${cfg.maxPoolSize}）${cfg.redacted()}")
        } else {
            this.ds = raw
            Log.info("数据库连接已建立（无池）${cfg.redacted()}")
        }
    }
    public func connect(): Connection { return this.ds.connect() }

    /** 轻量 DB 探针：能连接并执行 SELECT 1 返回 true。供 /health 做深健康检查。
     *  连接池僵死时 connect()/query() 会阻塞，由外层 healthcheck 的 curl 超时判定 unhealthy → 容器重启自愈。 */
    public func ping(): Bool {
        try {
            let c = this.connect()
            try {
                let st = c.prepareStatement("SELECT 1")
                let rs = st.query()
                var ok = false
                while (rs.next()) { ok = true }   // 读到 EOF，保证连接归还
                return ok
            } finally { c.close() }
        } catch (e: Exception) {
            Log.warn("DB 健康探针失败：${e}")
            return false
        }
    }

    /** 列是否存在（用 information_schema，避免 openGauss 不支持 IF NOT EXISTS）。
     *  用独立连接查询并关闭，避免未消费的 ResultSet 占用 initSchema 的主连接。 */
    private func hasColumn(table: String, column: String): Bool {
        let c2 = this.connect()
        try {
            let st = c2.prepareStatement(
                "SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?")
            st.set(0, table)
            st.set(1, column)
            let rs = st.query()
            var found = false
            while (rs.next()) { found = true }
            return found
        } finally {
            c2.close()
        }
    }

    /** 启动时建表（幂等）。 */
    public func initSchema(): Unit {
        let c = this.connect()
        try {
            let st1 = c.prepareStatement(
                "CREATE TABLE IF NOT EXISTS rg_users (" +
                "username VARCHAR(64) PRIMARY KEY, password_hash VARCHAR(160) NOT NULL, " +
                "tenant_name VARCHAR(128) NOT NULL DEFAULT '', token_version BIGINT NOT NULL DEFAULT 1, " +
                "failed_count BIGINT NOT NULL DEFAULT 0, locked_until_ms BIGINT NOT NULL DEFAULT 0)")
            st1.update()
            let st2 = c.prepareStatement(
                "CREATE TABLE IF NOT EXISTS rg_cases (" +
                "case_id VARCHAR(64) PRIMARY KEY, tenant VARCHAR(64) NOT NULL, " +
                "sku VARCHAR(64), category VARCHAR(64), supplier VARCHAR(32), platform VARCHAR(32), " +
                "region VARCHAR(32), season VARCHAR(16), amount DOUBLE PRECISION, similarity DOUBLE PRECISION, " +
                "outcome VARCHAR(32), defect VARCHAR(128))")
            st2.update()
            let st3 = c.prepareStatement(
                "CREATE TABLE IF NOT EXISTS rg_audit (" +
                "seq BIGINT PRIMARY KEY, ts_ms BIGINT NOT NULL, actor VARCHAR(64), action VARCHAR(64), " +
                "ip VARCHAR(64), outcome VARCHAR(64), detail VARCHAR(512), prev_hash VARCHAR(64), hash VARCHAR(64) NOT NULL)")
            st3.update()
            // 向前兼容：为旧库补列（openGauss 不支持 ADD COLUMN IF NOT EXISTS，先查 information_schema）
            if (!this.hasColumn("rg_users", "totp_secret")) {
                c.prepareStatement("ALTER TABLE rg_users ADD COLUMN totp_secret VARCHAR(128) NOT NULL DEFAULT ''").update()
            }
            if (!this.hasColumn("rg_users", "hash_algo")) {
                c.prepareStatement("ALTER TABLE rg_users ADD COLUMN hash_algo VARCHAR(16) NOT NULL DEFAULT 'sha256'").update()
            }
            // 个人资料字段（3.1.0）
            if (!this.hasColumn("rg_users", "display_name")) {
                c.prepareStatement("ALTER TABLE rg_users ADD COLUMN display_name VARCHAR(128) NOT NULL DEFAULT ''").update()
            }
            if (!this.hasColumn("rg_users", "email")) {
                c.prepareStatement("ALTER TABLE rg_users ADD COLUMN email VARCHAR(160) NOT NULL DEFAULT ''").update()
            }
            let st6 = c.prepareStatement(
                "CREATE TABLE IF NOT EXISTS rg_quota (" +
                "scope VARCHAR(32) NOT NULL, bucket VARCHAR(128) NOT NULL, cnt BIGINT NOT NULL DEFAULT 0, " +
                "PRIMARY KEY(scope, bucket))")
            st6.update()
            let st7 = c.prepareStatement(
                "CREATE TABLE IF NOT EXISTS rg_sessions (" +
                "sid VARCHAR(64) PRIMARY KEY, username VARCHAR(64) NOT NULL, token_hash VARCHAR(64) NOT NULL, " +
                "device VARCHAR(128) NOT NULL DEFAULT '', ip VARCHAR(64) NOT NULL DEFAULT '', " +
                "created_ms BIGINT NOT NULL, expires_ms BIGINT NOT NULL, revoked SMALLINT NOT NULL DEFAULT 0)")
            st7.update()
            // refresh token 支持：refresh_hash + used（重放检测）
            if (!this.hasColumn("rg_sessions", "refresh_hash")) {
                c.prepareStatement("ALTER TABLE rg_sessions ADD COLUMN refresh_hash VARCHAR(64) NOT NULL DEFAULT ''").update()
            }
            if (!this.hasColumn("rg_sessions", "used")) {
                c.prepareStatement("ALTER TABLE rg_sessions ADD COLUMN used SMALLINT NOT NULL DEFAULT 0").update()
            }
            // 会话空闲超时：last_used_ms（滑动窗口），默认 0 表示在 Repo 层禁用
            if (!this.hasColumn("rg_sessions", "last_used_ms")) {
                c.prepareStatement("ALTER TABLE rg_sessions ADD COLUMN last_used_ms BIGINT NOT NULL DEFAULT 0").update()
            }
            Log.info("数据库表已就绪（rg_users/rg_cases/rg_audit/rg_quota/rg_sessions，含 refresh/空闲超时字段）")
        } finally {
            c.close()
        }
    }
}

/** 把 QueryResult 读成字符串 map 列表（驱动把任意 PG 类型转成字符串，NULL 为 None）。 */
public func readRows(rs: QueryResult): ArrayList<HashMap<String, String>> {
    let out = ArrayList<HashMap<String, String>>()
    let infos = rs.columnInfos
    while (rs.next()) {
        let row = HashMap<String, String>()
        for (i in 0..infos.size) {
            match (rs.getOrNull<String>(i)) {
                case Some(v) => row.add(infos[i].name, v)
                case None => ()
            }
        }
        out.add(row)
    }
    return out
}
