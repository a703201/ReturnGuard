// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 极简日志（标准输出，带时间戳）。参考 AMS ams.kernel.log。
package rg.kernel.log

import std.time.*

public class Log {
    public static func info(msg: String): Unit {
        println("[INFO] ${nowIso()} ${msg}")
    }
    public static func warn(msg: String): Unit {
        println("[WARN] ${nowIso()} ${msg}")
    }
    private static func nowIso(): String {
        return DateTime.now().toString()
    }
}
