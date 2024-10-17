from bs4 import BeautifulSoup
import api.cxsecret_font as cxfont
import re


class FontDecoder:
    def __init__(self,html_content:str=None):
        self.html_content = html_content
        # self.__isNeedDecode = True
        self.__font_hash_map = None
        self.__decode_init(html_content)
    
    def __decode_init(self, html_content):
        if html_content:
            soup = BeautifulSoup(html_content, "lxml")
            style_tag = soup.find("style",id="cxSecretStyle")
            match = re.search(r'base64,([\w\W]+?)\'', style_tag.text)
            self.__font_hash_map = cxfont.font2map('data:application/font-ttf;charset=utf-8;base64,'+match.group(1))

    def decode(self,target_str:str) -> str:
        return cxfont.decrypt(self.__font_hash_map, target_str)

