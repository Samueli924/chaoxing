import re
from typing import Dict, Optional

from bs4 import BeautifulSoup

import api.cxsecret_font as cxfont
from api.exceptions import FontDecodeError
from api.logger import logger


class FontDecoder:
    """超星加密字体解码器。
    
    用于解码超星平台使用特殊字体加密的内容。
    """
    
    # 正则表达式常量
    FONT_BASE64_PATTERN = r"base64,([\w\W]+?)\'"
    FONT_DATA_URL_PREFIX = "data:application/font-ttf;charset=utf-8;base64,"
    
    def __init__(self, html_content: Optional[str] = None):
        """初始化字体解码器。
        
        Args:
            html_content: 包含加密字体信息的HTML内容
        """
        self.html_content = html_content
        self.__font_map: Optional[Dict] = None
        
        if html_content:
            self.__init_font_map(html_content)
    
    def __init_font_map(self, html_content: str) -> None:
        """从HTML内容中提取字体信息并初始化字体映射。
        
        Args:
            html_content: 包含加密字体信息的HTML内容
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")
            style_tag = soup.find("style", id="cxSecretStyle")
            
            if not style_tag or not style_tag.text:
                raise FontDecodeError("未找到加密字体样式标签")

            match = re.search(self.FONT_BASE64_PATTERN, style_tag.text)
            if not match:
                raise FontDecodeError("无法从样式标签中提取字体数据")

            font_base64 = match.group(1)
            font_data_url = self.FONT_DATA_URL_PREFIX + font_base64
            self.__font_map = cxfont.font2map(font_data_url)
        except Exception as e:
            logger.warning(f"初始化字体映射失败: {e}")
            self.__font_map = None
    
    def decode(self, target_str: str) -> str:
        """解码加密字符串。
        
        Args:
            target_str: 需要解码的加密字符串
            
        Returns:
            解码后的字符串
            
        Raises:
            ValueError: 当字体映射未初始化时抛出
        """
        if not self.__font_map:
            raise FontDecodeError("字体映射未初始化，无法解码")

        return cxfont.decrypt(self.__font_map, target_str)
    
    def set_html_content(self, html_content: str) -> None:
        """设置新的HTML内容并重新初始化字体映射。
        
        Args:
            html_content: 包含加密字体信息的HTML内容
        """
        self.html_content = html_content
        self.__init_font_map(html_content)
