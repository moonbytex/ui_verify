"""配置读取。

对应原始代码：
- deveco-cli/packages/cli/src/ui-verification/config.ts       loadUiVerificationConfig
- deveco-cli/packages/cli/src/auth/utils/local-crypto.ts       decryptForLocalStorage
- deveco-cli/packages/cli/src/auth/auth-config.ts              CONFIG_DIR_NAME/APP_NAME/KEY_FILE_NAME/KEK_VERSIONS
- ui-verification-mcp/dist/uiVerification.mjs                  Nr() 读取整数型环境变量

devecocli verify 会把 baseUrl/modelName/apiKey 通过环境变量 UI_VERIFY_* 传给 MCP 子进程，
这里直接读取同一份本地配置（只读，不会创建/修复密钥材料），环境变量优先。
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

KEK_VERSIONS = ("kek-v1", "kek-v2", "kek-v3")


def _config_dir() -> Path:
    data_dir = os.environ.get("DEVECO_CLI_DATA_DIR")
    if data_dir:
        return Path(data_dir)
    return Path.home() / ".config" / "deveco-cli"


def _key_dir() -> Path:
    return Path.home() / ".local" / "share" / "deveco-cli" / "keys"


def _aes_gcm_decrypt(ciphertext: bytes, key: bytes, iv_b64: str, tag_b64: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    iv = base64.b64decode(iv_b64)
    tag = base64.b64decode(tag_b64)
    # Node 的 GCM 把 authTag 单独存放；cryptography 需要 ciphertext||tag
    return AESGCM(key).decrypt(iv, ciphertext + tag, None)


def _load_dek() -> bytes:
    wrapped = json.loads((_config_dir() / "token.dek").read_text("utf-8"))
    kek_id = wrapped["kekId"]
    if kek_id not in KEK_VERSIONS:
        raise ValueError(f"Invalid kekId: {kek_id}")
    kek = (_key_dir() / f"{kek_id}.bin").read_bytes()
    if len(kek) != 32:
        raise ValueError("Invalid root key length")
    dek = _aes_gcm_decrypt(
        base64.b64decode(wrapped["encryptedDek"]), kek, wrapped["iv"], wrapped["authTag"]
    )
    if len(dek) != 32:
        raise ValueError("Invalid DEK length")
    return dek


def _is_encrypted_blob(v) -> bool:
    return (
        isinstance(v, dict)
        and v.get("algorithm") == "aes-256-gcm"
        and all(isinstance(v.get(k), str) for k in ("ciphertext", "iv", "authTag"))
    )


@dataclass
class ModelConfig:
    base_url: str
    model_name: str
    api_key: str


def load_model_config() -> ModelConfig:
    """环境变量 UI_VERIFY_* / RC_* 优先，否则读 devecocli verify init 保存的配置。"""
    base_url = os.environ.get("UI_VERIFY_BASE_URL") or os.environ.get("RC_BASE_URL")
    model = os.environ.get("UI_VERIFY_MODEL_NAME") or os.environ.get("RC_MODEL_NAME")
    api_key = os.environ.get("UI_VERIFY_API_KEY") or os.environ.get("RC_API_KEY")

    cfg_path = _config_dir() / "ui_verification_config.json"
    if cfg_path.exists() and not (base_url and model and api_key):
        raw = json.loads(cfg_path.read_text("utf-8"))
        base_url = base_url or raw.get("baseUrl")
        model = model or raw.get("modelName")
        if not api_key and _is_encrypted_blob(raw.get("encryptedApiKey")):
            blob = raw["encryptedApiKey"]
            api_key = _aes_gcm_decrypt(
                base64.b64decode(blob["ciphertext"]), _load_dek(), blob["iv"], blob["authTag"]
            ).decode("utf-8")

    if not (base_url and model and api_key):
        raise RuntimeError(
            "未配置多模态模型。请先运行 devecocli verify init --base-url ... --model-name ... --api-key ...，"
            "或设置环境变量 UI_VERIFY_BASE_URL / UI_VERIFY_MODEL_NAME / UI_VERIFY_API_KEY"
        )
    return ModelConfig(base_url.rstrip("/"), model, api_key)


def env_int(name: str, default: int) -> int:
    """对应 Nr(t, e)：只接受正整数，否则用默认值。"""
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    try:
        n = float(v)
    except ValueError:
        return default
    return int(n) if n.is_integer() and n > 0 else default


# 对应 mjs 中的常量
MAX_ABNORMAL_RETRIES = env_int("UI_VERIFY_MAXIMAL_ABNORMAL_RETRIES", 3)  # qo
MAX_REPEATED_STATUS = env_int("UI_VERIFY_MAXIMAL_REPEATED_STATUS", 3)  # Vc
MAX_EXECUTION_ROUNDS = env_int("UI_VERIFY_MAX_EXECUTION_ROUNDS", 30)  # gr
