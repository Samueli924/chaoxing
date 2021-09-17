import src.path.pathCheck as pathCheck

from rich.console import Console
from rich.table import Table
import re,json,requests
import requests.utils

def find_courses(usernm,session):
    console = Console()
    course = {}
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("序号", style="dim")
    table.add_column("课程名")
    chapterids = []
    print("正在获取课程")
    header = {'Accept-Encoding': 'gzip',
              'Accept-Language': 'zh_CN',
              'Host': 'mooc1-api.chaoxing.com',
              'Connection': 'Keep-Alive',
              'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_1969814533'
              }
    my_course = session.get("http://mooc1-api.chaoxing.com/mycourse?rss=1&mcode=", headers=header)
    result = my_course.json()
    channelList = result['channelList']
    for item in channelList:
        try:
            table.add_row(str(channelList.index(item)), item['content']['course']['data'][0]['name'])
        except:
            pass
    console.print(table)
    num = int(input('请输入你要选择的课程序号'))
    channelList_json = channelList[num]
    course['cpi'] = channelList_json['cpi']
    course['clazzid'] = channelList_json['content']['id']
    course['courseid'] = channelList_json['content']['course']['data'][0]['id']
    print("课程名称:" + channelList[num]['content']['course']['data'][0]['name'])
    print("讲师：" + channelList[num]['content']['course']['data'][0]['teacherfactor'])
    url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid=' + str(
        course['courseid']) + '&clazzid=' + str(course['clazzid']) + '&vc=1&cpi=' + str(course['cpi'])
    resp = session.get(url, headers=header)
    content = resp.text
    for chapter in re.findall('\?chapterId=(.*?)&', content):
        chapterids.append(str(chapter))
    course['enc'] = re.findall("&clazzid=.*?&enc=(.*?)'", content)[0]
    course_path = 'saves/{}/{}'.format(usernm,course['courseid'])
    pathCheck.check_path(course_path)
    with open('{}/courseinfo.json'.format(course_path),'w') as f:
        json.dump(course,f)
    with open('{}/chapterid.json'.format(course_path),'w') as f:
        json.dump(chapterids,f)
    return chapterids,course


def find_objectives(usernm,chapterids,course_id,session):
    jobs = {}
    for lesson_id in chapterids:
        url = 'http://mooc1-api.chaoxing.com/gas/knowledge?id=' + str(lesson_id) + '&courseid=' + str(
            course_id) + '&fields=begintime,clickcount,createtime,description,indexorder,jobUnfinishedCount,jobcount,jobfinishcount,label,lastmodifytime,layer,listPosition,name,openlock,parentnodeid,status,id,card.fields(cardIndex,cardorder,description,knowledgeTitile,knowledgeid,theme,title,id).contentcard(all)&view=json'
        header = {
            'Accept-Language': 'zh_CN',
            'Host': 'mooc1-api.chaoxing.com',
            'Connection': 'Keep-Alive',
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_19698145335.21'
        }
        resp = session.get(url, headers=header)
        try:
            content = str(json.loads(resp.text)['data'][0]['card']['data']).replace('&quot;', '')
            result = re.findall('{objectid:(.*?),.*?,_jobid:(.*?),', content)
            jobs[lesson_id] = result
            print('在章节{}中找到{}个任务点'.format(lesson_id,len(result)))
        except Exception as e:
            print('错误类型:{}'.format(e.__class__.__name__))
            print('错误明细:{}'.format(e))
    course_path = 'saves/{}/{}'.format(usernm,course_id)
    with open('{}/jobsinfo.json'.format(course_path) ,'w') as f:
        json.dump(jobs,f)
    return jobs



