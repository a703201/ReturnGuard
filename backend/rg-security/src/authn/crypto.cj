// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 密码学原语：SHA256 / HMAC-SHA256 / PBKDF2-HMAC-SHA256 / hex / 常量时间比较。
// 参考 AMS ams-crypto 的已验证实现（SDK 1.2.0 stdx crypto）。
package rg.security.authn

import stdx.crypto.digest.*
import stdx.crypto.crypto.*

/** 字节数组转小写 hex。 */
public func toHex(bytes: Array<Byte>): String {
    let hex = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "c", "d", "e", "f"]
    let sb = StringBuilder()
    for (b in bytes) {
        let v = Int64(b)
        sb.append(hex[(v >> 4) & 0xf])
        sb.append(hex[v & 0xf])
    }
    return sb.toString()
}

/** SHA256 摘要。 */
public func sha256(data: Array<Byte>): Array<Byte> {
    let h = SHA256()
    h.write(data)
    return h.finish()
}

/** HMAC-SHA256（RFC 2104，自实现，因 SDK 的 HashType 未确认有 SHA256 成员）。 */
public func hmacSha256(key: Array<Byte>, data: Array<Byte>): Array<Byte> {
    var k = key
    if (k.size > 64) { k = sha256(k) }
    let ipad = Array<Byte>(64, repeat: 0u8)
    let opad = Array<Byte>(64, repeat: 0u8)
    var i: Int64 = 0
    while (i < 64) {
        let bv = if (i < k.size) { Int64(k[i]) } else { 0 }
        ipad[i] = UInt8(bv ^ 54)  // 0x36
        opad[i] = UInt8(bv ^ 92)  // 0x5C
        i += 1
    }
    let inner = Array<Byte>(64 + data.size, repeat: 0u8)
    for (i in 0..64) { inner[i] = ipad[i] }
    for (i in 0..data.size) { inner[64 + i] = data[i] }
    let innerHash = sha256(inner)
    let outer = Array<Byte>(64 + 32, repeat: 0u8)
    for (i in 0..64) { outer[i] = opad[i] }
    for (i in 0..32) { outer[64 + i] = innerHash[i] }
    return sha256(outer)
}

/** PBKDF2-HMAC-SHA256（RFC 2898），返回派生密钥字节。 */
public func pbkdf2(password: Array<Byte>, salt: Array<Byte>, iterations: Int64, keyLen: Int64): Array<Byte> {
    let hLen = 32
    let blocks = (keyLen + hLen - 1) / hLen
    let out = Array<Byte>(keyLen, repeat: 0u8)
    var block: Int64 = 1
    var offset: Int64 = 0
    while (block <= blocks) {
        // U1 = HMAC(password, salt || INT_32_BE(block))
        let msg = Array<Byte>(salt.size + 4, repeat: 0u8)
        for (i in 0..salt.size) { msg[i] = salt[i] }
        msg[salt.size] = UInt8((block >> 24) & 0xff)
        msg[salt.size + 1] = UInt8((block >> 16) & 0xff)
        msg[salt.size + 2] = UInt8((block >> 8) & 0xff)
        msg[salt.size + 3] = UInt8(block & 0xff)
        var u = hmacSha256(password, msg)
        let t = Array<Byte>(u.size, repeat: 0u8)
        for (i in 0..u.size) { t[i] = u[i] }
        var iter: Int64 = 1
        while (iter < iterations) {
            u = hmacSha256(password, u)
            for (i in 0..u.size) { t[i] = t[i] ^ u[i] }
            iter += 1
        }
        let take = if (offset + hLen <= keyLen) { hLen } else { keyLen - offset }
        for (i in 0..take) { out[offset + i] = t[i] }
        offset += hLen
        block += 1
    }
    return out
}

/** 安全随机字节。 */
public func randomBytes(length: Int64): Array<Byte> {
    let buf = Array<Byte>(length, repeat: 0u8)
    let rnd = SecureRandom()
    rnd.nextBytes(buf)
    return buf
}

/** 常量时间字符串比较（防时序侧信道）。 */
public func constantEq(a: String, b: String): Bool {
    let ba = a.toArray()
    let bb = b.toArray()
    if (ba.size != bb.size) { return false }
    var diff: UInt8 = 0
    for (i in 0..ba.size) { diff = diff | (ba[i] ^ bb[i]) }
    return diff == 0
}
