import json
import os
def check_course_file(usernm):
    courses = os.listdir(usernm)
    tmp = ''
    if courses:
        print('检测到存在以下课程进度存档')
        i = 1
        for item in courses:
            print(str(i) + '、' + item)
    else:
        print('未检测到已存在的进度存档')
        return 0
    num = int(input('请选择您要继续的课程,重开请输入0'))
    if num == 0:
        return 0
    else:
        path = os.path.join(usernm, courses[num - 1])
        j = {}
        print('正在加载course')
        with open(os.path.join(path, 'mp4_log.json'), 'r') as mp4_dump:
            m = json.loads(mp4_dump.read())
        with open(os.path.join(path, 'ppt_log.json'), 'r') as ppt_dump:
            p = json.loads(ppt_dump.read())
        with open(os.path.join(path, 'course_info.json'), 'r') as course_dump:
            c = json.loads(course_dump.read())
        with open(os.path.join(path, 'job_list.json'), 'r') as job_dump:
            jj = json.loads(job_dump.read())
        l = []
        for item in m:
            if m[item][6] in l:
                pass
            else:
                l.append(m[item][6])
        for item in p:
            if p[item][5] in l:
                pass
            else:
                l.append(p[item][5])
        print('课程内容加载完毕')
        j['mp4'] = m
        j['ppt'] = p
        j['course'] = c
        j['job'] = jj
        j['chapter'] = l
        return j

