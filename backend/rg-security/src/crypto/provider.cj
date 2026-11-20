// ============================================================
// ams.crypto.provider · 密码学能力抽象
//
// 目的（架构 §5.4）：
//   把「国密能力的具体实现」与「调用方」解耦。
//   当前实现基于 stdx.crypto（见 ams.crypto.impl），
//   后续若切换到 C++ OpenSSL 插件或硬件密码机，只需换 Provider 实现，
//   上层业务代码零改动。
//
// 规约：
//   - 所有方法**不得**抛裸异常，失败一律返回 Result 值
//   - 密钥材料不得进入日志或异常消息
//   - 涉及随机数的接口必须用 SecureRandom（不可预测）
// ============================================================
package rg.security.crypto

import rg.kernel.error.*

/**
 * 摘要算法。
 */
public enum DigestAlgorithm {
    | Sm3
    | Sha256
}

/**
 * 对称加密模式。
 *
 * 注意：**GCM 在 stdx 1.0.5.1 与 1.2.0.1 上均不可用**（实测报 "create tag error"，
 * 而 OpenSSL 3.5.7 本身支持 SM4-GCM），故本项目采用
 * Encrypt-then-MAC 组合（CBC 加密 + HMAC-SM3 认证）。
 * 详见安全章 §4.0 的实测记录。
 */
public enum CipherMode {
    | Cbc
    | Ctr
}

/**
 * 操作结果。避免用异常表达可预期的失败。
 */
public enum CryptoResult<T> {
    | Ok(T)
    | Err(AppError)
}

/**
 * 密码学服务接口。
 *
 * 实现类必须线程安全。
 */
public interface CryptoProvider {
    /**
     * 计算摘要。
     *
     * @param data 待摘要数据
     * @param algorithm 摘要算法
     * @return 摘要字节（SM3 为 32 字节）
     */
    func digest(data: Array<Byte>, algorithm: DigestAlgorithm): CryptoResult<Array<Byte>>

    /**
     * 计算 HMAC。
     *
     * @param key 密钥
     * @param data 待认证数据
     * @param algorithm 底层摘要算法（国密场景用 Sm3）
     */
    func hmac(key: Array<Byte>, data: Array<Byte>, algorithm: DigestAlgorithm): CryptoResult<Array<Byte>>

    /**
     * 生成随机字节。
     *
     * @param length 字节数
     */
    func randomBytes(length: Int64): CryptoResult<Array<Byte>>

    /**
     * 对称加密。
     *
     * @param key 密钥（SM4 为 16 字节）
     * @param iv 初始化向量（CBC 为 16 字节，CTR 为 16 字节计数器）
     * @param plaintext 明文
     * @param mode 加密模式
     */
    func encrypt(
        key: Array<Byte>,
        iv: Array<Byte>,
        plaintext: Array<Byte>,
        mode: CipherMode
    ): CryptoResult<Array<Byte>>

    /**
     * 对称解密（key/iv/mode 必须与加密时一致）。
     */
    func decrypt(
        key: Array<Byte>,
        iv: Array<Byte>,
        ciphertext: Array<Byte>,
        mode: CipherMode
    ): CryptoResult<Array<Byte>>

    /**
     * 口令派生（PBKDF2-HMAC-SM3）。
     *
     * @param password 口令
     * @param salt 盐值（建议 ≥ 16 字节，且每次不同）
     * @param iterations 迭代次数（越大越慢越安全）
     * @param keyLength 派生密钥长度（字节）
     */
    func deriveKey(
        password: Array<Byte>,
        salt: Array<Byte>,
        iterations: Int64,
        keyLength: Int64
    ): CryptoResult<Array<Byte>>

    /**
     * 恒定时间比较，避免时序侧信道。
     */
    func constantTimeEquals(a: Array<Byte>, b: Array<Byte>): Bool
}
