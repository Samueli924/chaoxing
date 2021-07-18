import time
from random import randint

def regulate_print(content):
    l = len(content)
    if l < 80:
        content = content + (80 - l) * ' '
    else:
        content = content
    print(content,end='\r',flush=True)


def get_content(coursename):
    i = '1'
    print('Test Begin')
    while True:
        content = '课程名：'+coursename +'剩余时间'+ i + 's'
        ran = randint(0,3)
        if ran >= 1:
            i +=  '1'
            # print('增加')
        else:
            i = i[:-1]
            # print('减少')
        regulate_print(content)
        time.sleep(1)
if __name__ == '__main__':
    coursename = input('Input course name please')
    if not coursename:
        coursename = '清洁能源与生产'
    content = get_content(coursename)