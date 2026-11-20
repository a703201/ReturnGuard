// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 统一错误类型与 HTTP 状态码映射（参考 AMS ams.kernel.error）。
package rg.kernel.error

public enum ErrKind {
    NotFound | MethodNotAllowed | BadRequest | Unauthorized | Forbidden
    | TooManyRequests | PayloadTooLarge | Internal | CryptoFailure
}

public class AppError <: Exception {
    public let kind: ErrKind
    public let detail: String
    public init(kind: ErrKind, detail: String) {
        super(detail)
        this.kind = kind
        this.detail = detail
    }
}

public func httpStatusOf(kind: ErrKind): UInt16 {
    match (kind) {
        case ErrKind.NotFound => return 404
        case ErrKind.MethodNotAllowed => return 405
        case ErrKind.BadRequest => return 400
        case ErrKind.Unauthorized => return 401
        case ErrKind.Forbidden => return 403
        case ErrKind.TooManyRequests => return 429
        case ErrKind.PayloadTooLarge => return 413
        case ErrKind.CryptoFailure => return 500
        case ErrKind.Internal => return 500
    }
}
