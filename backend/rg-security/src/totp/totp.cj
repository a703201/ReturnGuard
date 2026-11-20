// ============================================================
// ams.security.totp · TOTP（RFC 6238）实现
//
// 为什么自己实现 SHA-1 / HMAC / Base32：
//   本机 stdx 只提供 SM3/SHA-256 摘要与 HMAC-SM3，**没有 SHA-1、没有 Base32**，
//   而 TOTP 要与 Google Authenticator / 微软 Authenticator 等标准 App 互通，
//   必须严格按 RFC 6238（HMAC-SHA1）/ RFC 4226（HOTP）/ RFC 4648（Base32）。
//   因此这里按规范实现最小子集，并用 RFC 6238 附录 B 的官方测试向量自检
//   （见 Totp.selftest）。
//
// 数值策略：
//   全部用 Int64 承载 32 位无符号中间量，每步 & 0xFFFFFFFF 截断。
//   原因：仓颉的 UInt32 溢出行为依赖运行时检查，而 SHA-1 处处需要「回绕加法」；
//   用 Int64 + 掩码是等价且绝不会抛异常的写法。
// ============================================================
package rg.security.totp

import std.collection.*

/**
 * SHA-1（FIPS 180-4）。
 */
public class Sha1 {
    /** 计算摘要，返回 20 字节 */
    public static func hash(data: Array<Byte>): Array<Byte> {
        var h0: Int64 = 0x67452301
        var h1: Int64 = 0xEFCDAB89
        var h2: Int64 = 0x98BADCFE
        var h3: Int64 = 0x10325476
        var h4: Int64 = 0xC3D2E1F0

        // 填充：0x80 + 若干 0x00 + 64 位大端比特长度
        let msg = ArrayList<Byte>()
        for (b in data) {
            msg.add(b)
        }
        msg.add(0x80u8)
        while ((msg.size + 8) % 64 != 0) {
            msg.add(0u8)
        }
        let bitLen = data.size * 8
        var s: Int64 = 56
        while (s >= 0) {
            msg.add(UInt8((bitLen >> s) & 0xFF))
            s = s - 8
        }
        let m = msg.toArray()

        var w = Array<Int64>(80, repeat: 0)
        var block: Int64 = 0
        while (block < m.size) {
            for (i in 0..16) {
                let o = block + i * 4
                w[i] = (Int64(m[o]) << 24) | (Int64(m[o + 1]) << 16) |
                       (Int64(m[o + 2]) << 8) | Int64(m[o + 3])
            }
            for (i in 16..80) {
                w[i] = Sha1.rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1)
            }
            var a = h0
            var b = h1
            var c = h2
            var d = h3
            var e = h4
            for (i in 0..80) {
                var f: Int64 = 0
                var k: Int64 = 0
                if (i < 20) {
                    f = (b & c) | ((b ^ 0xFFFFFFFF) & d)
                    k = 0x5A827999
                } else if (i < 40) {
                    f = b ^ c ^ d
                    k = 0x6ED9EBA1
                } else if (i < 60) {
                    f = (b & c) | (b & d) | (c & d)
                    k = 0x8F1BBCDC
                } else {
                    f = b ^ c ^ d
                    k = 0xCA62C1D6
                }
                let tmp = (Sha1.rotl(a, 5) + f + e + k + w[i]) & 0xFFFFFFFF
                e = d
                d = c
                c = Sha1.rotl(b, 30)
                b = a
                a = tmp
            }
            h0 = (h0 + a) & 0xFFFFFFFF
            h1 = (h1 + b) & 0xFFFFFFFF
            h2 = (h2 + c) & 0xFFFFFFFF
            h3 = (h3 + d) & 0xFFFFFFFF
            h4 = (h4 + e) & 0xFFFFFFFF
            block = block + 64
        }

        let out = Array<Byte>(20, repeat: 0u8)
        Sha1.putBe(out, 0, h0)
        Sha1.putBe(out, 4, h1)
        Sha1.putBe(out, 8, h2)
        Sha1.putBe(out, 12, h3)
        Sha1.putBe(out, 16, h4)
        return out
    }

    /**
     * HMAC-SHA1（RFC 2104），块长 64 字节。
     */
    public static func hmac(key: Array<Byte>, data: Array<Byte>): Array<Byte> {
        var k = key
        if (k.size > 64) {
            k = Sha1.hash(k)
        }
        let ipad = Array<Byte>(64, repeat: 0x36u8)
        let opad = Array<Byte>(64, repeat: 0x5Cu8)
        for (i in 0..k.size) {
            ipad[i] = UInt8(Int64(ipad[i]) ^ Int64(k[i]))
            opad[i] = UInt8(Int64(opad[i]) ^ Int64(k[i]))
        }
        let inner = ArrayList<Byte>()
        for (b in ipad) {
            inner.add(b)
        }
        for (b in data) {
            inner.add(b)
        }
        let ih = Sha1.hash(inner.toArray())
        let outer = ArrayList<Byte>()
        for (b in opad) {
            outer.add(b)
        }
        for (b in ih) {
            outer.add(b)
        }
        return Sha1.hash(outer.toArray())
    }

    private static func rotl(x: Int64, n: Int64): Int64 {
        let v = x & 0xFFFFFFFF
        return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF
    }

    private static func putBe(out: Array<Byte>, at: Int64, v: Int64): Unit {
        out[at] = UInt8((v >> 24) & 0xFF)
        out[at + 1] = UInt8((v >> 16) & 0xFF)
        out[at + 2] = UInt8((v >> 8) & 0xFF)
        out[at + 3] = UInt8(v & 0xFF)
    }
}

/**
 * Base32（RFC 4648，无小写、允许无填充）。
 */
public class Base32 {
    private static let ALPHABET: String = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

    /** 编码（带 = 填充） */
    public static func encode(data: Array<Byte>): String {
        let sb = StringBuilder()
        var buffer: Int64 = 0
        var bits: Int64 = 0
        for (b in data) {
            buffer = (buffer << 8) | Int64(b)
            bits = bits + 8
            while (bits >= 5) {
                let idx = (buffer >> (bits - 5)) & 31
                sb.append(Base32.charAt(idx))
                bits = bits - 5
            }
        }
        if (bits > 0) {
            let idx = (buffer << (5 - bits)) & 31
            sb.append(Base32.charAt(idx))
        }
        while (sb.toString().size % 8 != 0) {
            sb.append("=")
        }
        return sb.toString()
    }

    /** 解码（忽略 = 与空格，容忍小写） */
    public static func decode(s: String): Array<Byte> {
        let out = ArrayList<Byte>()
        var buffer: Int64 = 0
        var bits: Int64 = 0
        for (ch in s.runes()) {
            let c = ch.toString()
            if (c == "=" || c == " " || c == "\n" || c == "\r") {
                continue
            }
            let v = Base32.valueOf(c)
            if (v < 0) {
                continue
            }
            buffer = (buffer << 5) | v
            bits = bits + 5
            if (bits >= 8) {
                out.add(UInt8((buffer >> (bits - 8)) & 0xFF))
                bits = bits - 8
            }
        }
        return out.toArray()
    }

    private static func charAt(idx: Int64): String {
        if (idx < 0 || idx > 31) {
            return "A"
        }
        return Base32.ALPHABET[idx..idx + 1]
    }

    private static func valueOf(c: String): Int64 {
        let b = c.toArray()[0]
        if (b >= 65 && b <= 90) {
            return Int64(b) - 65
        }
        if (b >= 97 && b <= 122) {
            return Int64(b) - 97
        }
        if (b >= 50 && b <= 55) {
            return Int64(b) - 50 + 26
        }
        return -1
    }
}

/**
 * TOTP（RFC 6238）。
 */
public class Totp {
    /** 默认 6 位、30 秒 */
    public static let DIGITS: Int64 = 6
    public static let PERIOD: Int64 = 30

    /**
     * 计算某个时间点的动态码。
     *
     * @param secretB32 Base32 密钥
     * @param epochMillis 毫秒时间戳
     */
    public static func code(secretB32: String, epochMillis: Int64): String {
        return Totp.codeAt(secretB32, epochMillis / 1000 / PERIOD)
    }

    /**
     * 校验动态码。
     *
     * @param window 允许的时间步偏差（1 = 前后各 30 秒）
     * @return 命中的时间步；不匹配返回 -1（调用方用时间步做重放保护）
     */
    public static func verify(secretB32: String, code: String, epochMillis: Int64, window: Int64): Int64 {
        let cleaned = code.trimAscii()
        if (cleaned.size != 6) {
            return -1
        }
        let step = epochMillis / 1000 / PERIOD
        var w: Int64 = -window
        while (w <= window) {
            let st = step + w
            if (st >= 0) {
                if (Totp.codeAt(secretB32, st) == cleaned) {
                    return st
                }
            }
            w = w + 1
        }
        return -1
    }

    /** 生成新密钥（20 字节随机 → Base32，与主流 App 一致） */
    public static func newSecret(random: Array<Byte>): String {
        return Base32.encode(random)
    }

    /**
     * otpauth:// 绑定链接（供前端生成二维码）。
     */
    public static func otpauthUrl(issuer: String, account: String, secretB32: String): String {
        return "otpauth://totp/${Totp.urlEncode(issuer)}:${Totp.urlEncode(account)}" +
               "?secret=${secretB32}&issuer=${Totp.urlEncode(issuer)}" +
               "&algorithm=SHA1&digits=6&period=30"
    }

    /**
     * 自检：RFC 6238 附录 B 向量（SHA-1，密钥 = "12345678901234567890"）。
     *
     * 该向量的原文是 ASCII 密钥，Base32 编码后为
     * "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"。
     * 期望码取自 RFC（截断到 6 位：取后 6 位）。
     *
     * @return 全部通过返回 true
     */
    public static func selftest(): Bool {
        let secret = Base32.encode("12345678901234567890".toArray())
        let cases: Array<(Int64, String)> = [
            (59, "287082"),
            (1111111109, "081804"),
            (1111111111, "050471"),
            (1234567890, "005924"),
            (2000000000, "279037")
        ]
        for ((sec, expected) in cases) {
            if (Totp.code(secret, sec * 1000) != expected) {
                return false
            }
        }
        return true
    }

    private static func codeAt(secretB32: String, step: Int64): String {
        let key = Base32.decode(secretB32)
        // 8 字节大端计数器
        let counter = Array<Byte>(8, repeat: 0u8)
        var v = step
        var i: Int64 = 7
        while (i >= 0) {
            counter[i] = UInt8(v & 0xFF)
            v = v >> 8
            i = i - 1
        }
        let mac = Sha1.hmac(key, counter)
        let offset = Int64(mac[19] & 0x0F)
        let bin = ((Int64(mac[offset]) & 0x7F) << 24) |
                  ((Int64(mac[offset + 1]) & 0xFF) << 16) |
                  ((Int64(mac[offset + 2]) & 0xFF) << 8) |
                  (Int64(mac[offset + 3]) & 0xFF)
        let mod = 1000000
        let n = bin % mod
        let digits = "${n}"
        var pad = 6 - digits.size
        let sb = StringBuilder()
        while (pad > 0) {
            sb.append("0")
            pad = pad - 1
        }
        sb.append(digits)
        return sb.toString()
    }

    private static func urlEncode(s: String): String {
        return s.replace(" ", "%20").replace(":", "%3A").replace("/", "%2F")
    }
}
