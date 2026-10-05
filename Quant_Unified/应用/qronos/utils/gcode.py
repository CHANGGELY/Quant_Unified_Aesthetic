import os

import pyotp


def google_code(secret_key=''):
    # 创建TOTP对象
    totp = pyotp.TOTP(secret_key)
    return totp.now()


def verify_google_code(secret_key, code):
    totp = pyotp.TOTP(secret_key)
    print(totp.now())
    return totp.verify(code)


if __name__ == '__main__':
    # 密钥只从环境变量读取；原硬编码密钥已泄露，使用前先在对应账户重置 2FA
    secret = os.environ.get('TOTP_SECRET_KEY', '')
    if not secret:
        raise SystemExit('缺少环境变量 TOTP_SECRET_KEY，拒绝使用硬编码密钥')
    print(google_code(secret_key=secret))
