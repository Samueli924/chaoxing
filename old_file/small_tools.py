import os
def check_path(path):
    if os.path.exists(path):
        print('路径',path,'存在')
    else:
        os.mkdir(path)