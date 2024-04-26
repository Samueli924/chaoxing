import wx
import threading
import sys
from api.logger import logger
from api.base import Chaoxing, Account
from api.exceptions import LoginError, FormatError, JSONDecodeError

class RedirectText:
    def __init__(self, text_ctrl, max_lines=2):
        self.output = text_ctrl
        self.max_lines = max_lines

    def write(self, string):
        wx.CallAfter(self.output.AppendText, string)
        lines = self.output.GetNumberOfLines()
        if lines > self.max_lines:
            wx.CallAfter(self.output.Remove, 0, self.output.XYToPosition(0, 1))

    def flush(self):
        pass

class ChaoxingStudyApp(wx.Frame):
    def __init__(self, parent, title):
        super(ChaoxingStudyApp, self).__init__(parent, title=title, size=(800, 400))
        self.panel = wx.Panel(self)

        # UI 元素
        self.username_label = wx.StaticText(self.panel, label="手机号：", pos=(20, 20))
        self.username_text = wx.TextCtrl(self.panel, pos=(120, 20), size=(200, -1))

        self.password_label = wx.StaticText(self.panel, label="密码：", pos=(20, 50))
        self.password_text = wx.TextCtrl(self.panel, pos=(120, 50), size=(200, -1), style=wx.TE_PASSWORD)

        self.course_choice_label = wx.StaticText(self.panel, label="选择课程：", pos=(20, 80))
        self.course_choice = wx.Choice(self.panel, pos=(120, 80), size=(200, -1))

        self.speed_label = wx.StaticText(self.panel, label="视频播放速度：", pos=(20, 110))
        self.speed_text = wx.TextCtrl(self.panel, pos=(120, 110), size=(200, -1), value="1")

        self.current_course_label = wx.StaticText(self.panel, label="当前学习课程：", pos=(20, 140))
        self.current_course_text = wx.TextCtrl(self.panel, pos=(160, 140), size=(620, -1), style=wx.TE_READONLY)

        self.output_label = wx.StaticText(self.panel, label="进度条：", pos=(20, 170))
        self.output_text = wx.TextCtrl(self.panel, pos=(20, 200), size=(760, -1),
                                       style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.output_text.SetEditable(False)

        self.load_button = wx.Button(self.panel, label="加载账号", pos=(20, 250))
        self.load_button.Bind(wx.EVT_BUTTON, self.load_accounts)

        self.save_button = wx.Button(self.panel, label="保存账号", pos=(150, 250))
        self.save_button.Bind(wx.EVT_BUTTON, self.save_accounts)

        self.start_button = wx.Button(self.panel, label="开始学习", pos=(280, 250))
        self.start_button.Bind(wx.EVT_BUTTON, self.on_start_study)

        self.course_choice.Bind(wx.EVT_CHOICE, self.on_course_choice)

        self.accounts = []
        self.selected_account = None
        self.all_courses = []

        sys.stdout = RedirectText(self.output_text, max_lines=1)

        self.Show(True)

    def load_accounts(self, event):
        with open("accounts.txt", "r") as f:
            lines = f.readlines()
            for line in lines:
                account_info = line.strip().split(",")
                if len(account_info) == 2:
                    self.accounts.append({"username": account_info[0], "password": account_info[1]})

        dlg = wx.SingleChoiceDialog(self, "请选择要使用的账号", "选择账号",
                                    [account["username"] for account in self.accounts])
        if dlg.ShowModal() == wx.ID_OK:
            self.selected_account = self.accounts[dlg.GetSelection()]
            self.username_text.SetValue(self.selected_account["username"])
            self.password_text.SetValue(self.selected_account["password"])
            self.load_courses() 
        dlg.Destroy()

    def save_accounts(self, event):
        username = self.username_text.GetValue()
        password = self.password_text.GetValue()
        if not username or not password:
            wx.MessageBox("请输入手机号和密码", '错误', wx.OK | wx.ICON_ERROR)
            return

        with open("accounts.txt", "a") as f:
            f.write(f"{username},{password}\n")
        wx.MessageBox("账号保存成功", '成功', wx.OK | wx.ICON_INFORMATION)

    def on_start_study(self, event):
        if not self.selected_account:
            wx.MessageBox("请先加载账号", '错误', wx.OK | wx.ICON_ERROR)
            return
        self.output_text.SetValue("准备中，请稍后")
        username = self.selected_account["username"]
        password = self.selected_account["password"]
        course_id_index = self.course_choice.GetSelection()
        if course_id_index == wx.NOT_FOUND:
            course_id_index=0
            #return
        course_id = self.all_courses[course_id_index]["courseId"]
        speed = float(self.speed_text.GetValue().strip())

        study_thread = threading.Thread(target=self.study_course, args=(username, password, course_id, speed))
        study_thread.start()

    def study_course(self, username, password, course_id, speed):
        try:
            account = Account(username, password)
            chaoxing = Chaoxing(account=account)
            _login_state = chaoxing.login()
            if not _login_state["status"]:
                raise LoginError(_login_state["msg"])

            course = next((c for c in self.all_courses if c["courseId"] == course_id), None)
            if not course:
                raise ValueError("未找到指定的课程")

            current_course_info = f"{course['title']}"
            wx.CallAfter(self.current_course_text.SetValue, current_course_info)

            point_list = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
            for point in point_list["points"]:
                jobs = []
                job_info = None
                jobs, job_info = chaoxing.get_job_list(course["clazzId"], course["courseId"], course["cpi"],
                                                       point["id"])
                if not jobs:
                    continue
                for job in jobs:
                    if job["type"] == "video":
                        logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
                        isAudio = False
                        try:
                            chaoxing.study_video(course, job, job_info, _speed=speed, _type="Video")
                        except JSONDecodeError as e:
                            logger.warning("当前任务非视频任务，正在尝试音频任务解码")
                            isAudio = True
                        if isAudio:
                            try:
                                chaoxing.study_video(course, job, job_info, _speed=speed, _type="Audio")
                            except JSONDecodeError as e:
                                logger.warning(f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}")
        except Exception as e:
            wx.CallAfter(wx.MessageBox, str(e), '错误', wx.OK | wx.ICON_ERROR)

    def load_courses(self):
        if not self.selected_account:
            wx.MessageBox("请先加载账号", '错误', wx.OK | wx.ICON_ERROR)
            return
        username = self.selected_account["username"]
        password = self.selected_account["password"]
        try:
            account = Account(username, password)
            chaoxing = Chaoxing(account=account)
            _login_state = chaoxing.login()
            if not _login_state["status"]:
                raise LoginError(_login_state["msg"])
            self.all_courses = chaoxing.get_course_list()
            if not self.all_courses:
                raise ValueError("未获取到课程信息")
            wx.CallAfter(self.update_course_choices)
        except Exception as e:
            wx.CallAfter(wx.MessageBox, str(e), '错误', wx.OK | wx.ICON_ERROR)

    def update_course_choices(self):
        course_titles = [course["title"] for course in self.all_courses]
        self.course_choice.Clear()
        self.course_choice.AppendItems(course_titles)

    def on_course_choice(self, event):
        course_id_index = self.course_choice.GetSelection()
        if course_id_index != wx.NOT_FOUND:
            self.output_text.SetValue("选择课程：" + self.all_courses[course_id_index]["title"])

if __name__ == '__main__':
    app = wx.App(False)
    frame = ChaoxingStudyApp(None, "超星学习自动化")
    app.MainLoop()
