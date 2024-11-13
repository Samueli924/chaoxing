# -*- coding:utf-8 -*-
"""
AES加密模块
提供PKCS7填充和AES-CBC模式加密功能
"""

import base64
from typing import List, Union
import pyaes
from api.config import GlobalConst as gc


def pkcs7_unpadding(data: bytes) -> bytes:
    """
    移除PKCS7填充
    
    Args:
        data: 需要移除填充的字节串
        
    Returns:
        移除填充后的字节串
    """
    padding_length = data[-1]
    return data[:-padding_length]


def pkcs7_padding(data: bytes, block_size: int = 16) -> bytes:
    """
    添加PKCS7填充
    
    Args:
        data: 需要填充的字节串
        block_size: 块大小,默认16字节
        
    Returns:
        填充后的字节串
    """
    padding_length = block_size - len(data) % block_size
    padding = bytes([padding_length] * padding_length)
    return data + padding


def split_to_blocks(data: bytes, block_size: int = 16) -> List[bytes]:
    """
    将字节串分割为固定大小的块
    
    Args:
        data: 需要分割的字节串
        block_size: 块大小,默认16字节
        
    Returns:
        分割后的块列表
    """
    return [data[i:i + block_size] for i in range(0, len(data), block_size)]


class AESCipher:
    """AES加密类,使用CBC模式"""
    
    def __init__(self):
        """初始化密钥和IV向量"""
        self.key = str(gc.AESKey).encode("utf-8")
        self.iv = str(gc.AESKey).encode("utf-8")
        
    def encrypt(self, plaintext: str) -> str:
        """
        加密明文
        
        Args:
            plaintext: 待加密的字符串
            
        Returns:
            Base64编码的密文
        """
        # 初始化CBC模式
        cbc = pyaes.AESModeOfOperationCBC(self.key, self.iv)
        
        # 对明文进行填充并分块
        padded_data = pkcs7_padding(plaintext.encode('utf-8'))
        blocks = split_to_blocks(padded_data)
        
        # 加密所有数据块
        ciphertext = b''.join(cbc.encrypt(block) for block in blocks)
        
        # Base64编码并返回
        return base64.b64encode(ciphertext).decode("utf-8")