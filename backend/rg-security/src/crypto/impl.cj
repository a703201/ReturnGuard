// ============================================================
// ams.crypto.impl · 基于 stdx.crypto 的 CryptoProvider 实现
//
// 依赖：ams.crypto.provider（接口）、ams.kernel.error
//
// 能力基线（实测 SDK 1.2.0 / stdx 1.2.0.1，2026-10-26）：
//   | 能力            | 状态 | 验证                                      |
//   |-----------------|------|-------------------------------------------|
//   | SM3 摘要        | OK   | 与国标标准值一致                          |
//   | HMAC-SM3        | OK   | 与 OpenSSL 3.5.7 逐字节一致               |
//   | SM4-CBC         | OK   | 与 OpenSSL 3.5.7 逐字节一致               |
//   | SM4-CTR         | OK   | 流模式可用                                |
//   | SM4-GCM         | 不可 | stdx 报 "create tag error"（OpenSSL 支持）|
//   | PBKDF2          | 自行 | stdx 无此 API，本包自行实现                |
//   | SecureRandom    | OK   | 16 字节随机数正常                          |
//
// 变更记录：
//   2026-10-25  stdx 1.0.5.1 上实测 SM4-GCM 不可用 → 采用 SM4-CBC + HMAC-SM3
//   2026-10-26  升级到 stdx 1.2.0.1 后**复测**，SM4-GCM 仍不可用
//              （"Encrypt failed due to create tag error."），故方案不变；
//              顺带记录 SM4-CTR 可用。
//
// 因此：
//   - 摘要与 HMAC 直接用 stdx
//   - 对称加密用 SM4-CBC（配合上层 Encrypt-then-MAC）
//   - PBKDF2-HMAC-SM3 按 RFC 2898 自行实现（仅用 HMAC-SM3 做原语）
//   - 完整方案与必要性论证见 docs/03-安全设计说明.md §5
// ============================================================
package rg.security.crypto

import std.crypto.cipher.*
import stdx.crypto.crypto.*
import stdx.crypto.digest.*

import rg.kernel.error.*

/**
 * 基于 stdx 的密码学服务实现。
 */
public class StdxCryptoProvider <: CryptoProvider {
    public init() {
    }

    /**
     * 计算摘要。
     */
    public func digest(data: Array<Byte>, algorithm: DigestAlgorithm): CryptoResult<Array<Byte>> {
        match (algorithm) {
            case DigestAlgorithm.Sm3 => return CryptoResult.Ok(digestSm3(data))
            case DigestAlgorithm.Sha256 => return CryptoResult.Ok(digestSha256(data))
        }
    }

    /**
     * 计算 HMAC。
     */
    public func hmac(
        key: Array<Byte>,
        data: Array<Byte>,
        algorithm: DigestAlgorithm
    ): CryptoResult<Array<Byte>> {
        if (key.isEmpty()) {
            return CryptoResult.Err(AppError(ErrKind.CryptoFailure, "HMAC 密钥不能为空"))
        }

        match (algorithm) {
            case DigestAlgorithm.Sm3 => return CryptoResult.Ok(hmacSm3(key, data))
            case DigestAlgorithm.Sha256 => return CryptoResult.Ok(hmacSha256(key, data))
        }
    }

    /**
     * 生成随机字节。
     */
    public func randomBytes(length: Int64): CryptoResult<Array<Byte>> {
        if (length <= 0) {
            return CryptoResult.Err(AppError(ErrKind.CryptoFailure, "随机数长度必须为正"))
        }
        let buf = Array<Byte>(length, repeat: 0u8)
        let rnd = SecureRandom()
        rnd.nextBytes(buf)
        return CryptoResult.Ok(buf)
    }

    /**
     * 对称加密（SM4）。
     */
    public func encrypt(
        key: Array<Byte>,
        iv: Array<Byte>,
        plaintext: Array<Byte>,
        mode: CipherMode
    ): CryptoResult<Array<Byte>> {
        let cipher = StdxCryptoProvider.newCipher(key, iv, mode)
        match (cipher) {
            case Some(c) => return CryptoResult.Ok(c.encrypt(plaintext))
            case None => return CryptoResult.Err(
                AppError(ErrKind.CryptoFailure, "SM4 参数不合法（密钥或 IV 长度错误）")
            )
        }
    }

    /**
     * 对称解密（SM4）。
     */
    public func decrypt(
        key: Array<Byte>,
        iv: Array<Byte>,
        ciphertext: Array<Byte>,
        mode: CipherMode
    ): CryptoResult<Array<Byte>> {
        let cipher = StdxCryptoProvider.newCipher(key, iv, mode)
        match (cipher) {
            case Some(c) => return CryptoResult.Ok(c.decrypt(ciphertext))
            case None => return CryptoResult.Err(
                AppError(ErrKind.CryptoFailure, "SM4 参数不合法（密钥或 IV 长度错误）")
            )
        }
    }

    /**
     * PBKDF2-HMAC-SM3（RFC 2898）。
     */
    public func deriveKey(
        password: Array<Byte>,
        salt: Array<Byte>,
        iterations: Int64,
        keyLength: Int64
    ): CryptoResult<Array<Byte>> {
        if (iterations <= 0) {
            return CryptoResult.Err(AppError(ErrKind.CryptoFailure, "PBKDF2 迭代次数必须为正"))
        }
        if (keyLength <= 0) {
            return CryptoResult.Err(AppError(ErrKind.CryptoFailure, "PBKDF2 派生长度必须为正"))
        }
        if (salt.isEmpty()) {
            return CryptoResult.Err(AppError(ErrKind.CryptoFailure, "PBKDF2 盐值不能为空"))
        }
        return CryptoResult.Ok(Pbkdf2.deriveSm3(password, salt, iterations, keyLength))
    }

    /**
     * 恒定时间比较。
     */
    public func constantTimeEquals(a: Array<Byte>, b: Array<Byte>): Bool {
        if (a.size != b.size) {
            return false
        }
        // 累积所有字节的异或差，避免提前返回泄露长度/前缀信息
        var diff: UInt8 = 0u8
        for (i in 0..a.size) {
            diff = diff | (a[i] ^ b[i])
        }
        return diff == 0u8
    }

    // ---- 内部实现 ----

    private static func newCipher(
        key: Array<Byte>,
        iv: Array<Byte>,
        mode: CipherMode
    ): ?BlockCipher {
        if (key.size != 16 || iv.size != 16) {
            return None
        }
        match (mode) {
            case CipherMode.Cbc => return Some(SM4(OperationMode.CBC, key, iv: iv))
            case CipherMode.Ctr => return Some(SM4(OperationMode.CTR, key, iv: iv))
        }
    }

    private static func digestSm3(data: Array<Byte>): Array<Byte> {
        let h = SM3()
        h.write(data)
        return h.finish()
    }

    private static func digestSha256(data: Array<Byte>): Array<Byte> {
        let h = SHA256()
        h.write(data)
        return h.finish()
    }

    private static func hmacSm3(key: Array<Byte>, data: Array<Byte>): Array<Byte> {
        let h = HMAC(key, HashType.SM3)
        h.write(data)
        return h.finish()
    }

    /**
     * HMAC-SHA256（RFC 2104），基于本仓已验证可用的 stdx `SHA256` 摘要原语。
     *
     * 【为什么不直接 `HMAC(key, HashType.SHA256)`】SDK 1.2.0 的
     * `HashType` 在本工具链下只确认有 `SM3`；源码/头文件里查不到
     * `SHA256` 成员，赌一个不存在的枚举会让整个 crypto 包编译失败。
     * 而 HMAC 构造本身只有 ipad/opad + 两次摘要，自己实现 30 行、
     * 完全可控，还能用 RFC 4231 标准向量证明正确性（见 impl_test.cj）。
     *
     *   K' = (key > 64B ? SHA256(key) : key) 右补零到 64B
     *   out = SHA256( (K' xor opad) || SHA256( (K' xor ipad) || data ) )
     *
     * 注意：本函数只做 HMAC 计算，**不用于**档案字段加密（那仍是
     * HMAC-SM3 / EtM）。它的用途是 S3 SigV4 / OBS 兼容签名等
     * 与外部云服务商互操作的场景。
     */
    private static func hmacSha256(key: Array<Byte>, data: Array<Byte>): Array<Byte> {
        var k = key
        if (k.size > 64) {
            let hk = SHA256()
            hk.write(k)
            k = hk.finish()
        }
        let ipad = Array<Byte>(64, repeat: 0u8)
        let opad = Array<Byte>(64, repeat: 0u8)
        var i: Int64 = 0
        while (i < 64) {
            let bv = if (i < k.size) { Int64(k[i]) } else { 0 }
            ipad[i] = UInt8(bv ^ 54)    // 0x36
            opad[i] = UInt8(bv ^ 92)    // 0x5C
            i = i + 1
        }
        let inner = Array<Byte>(64 + data.size, repeat: 0u8)
        i = 0
        while (i < 64) {
            inner[i] = ipad[i]
            i = i + 1
        }
        i = 0
        while (i < data.size) {
            inner[64 + i] = data[i]
            i = i + 1
        }
        let hi = SHA256()
        hi.write(inner)
        let ih = hi.finish()

        let outer = Array<Byte>(64 + ih.size, repeat: 0u8)
        i = 0
        while (i < 64) {
            outer[i] = opad[i]
            i = i + 1
        }
        i = 0
        while (i < ih.size) {
            outer[64 + i] = ih[i]
            i = i + 1
        }
        let ho = SHA256()
        ho.write(outer)
        return ho.finish()
    }
}
