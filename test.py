import time


# print('视频任务“{}”总时长{}分钟{}秒，已看{}秒，完成度{:.2%},共完成视频任务{}/{}'.format(mp4[item][0],mm,ss,playingtime,percent,str(finished_num),str(len(mp4))),end="\r", flush=True)
def show_status(speed, name, totalmin, totalsec, done, job_done, totaljob):
    wait_time = int(60 / (float(60) * float(1 / speed)))
    goal = done + 60
    while done < goal:
        cont = int(done) / (int(totalmin)*60+int(totalsec))
        print(cont)
        print(int(cont))
        cont_detail = '*'*cont + '-'*(20-cont)
        status = '{}秒/{}秒'.format(done,(int(totalmin)*60+int(totalsec)))
        print('视频任务{}   {}  {}  总任务{}/{}'.format(name,cont_detail,status,job_done,totaljob),end='\r',flush=True)
        time.sleep(1)
        done += 1



if __name__ == '__main__':
    show_status(1,'清洁生产','10','30',100,'12','20')