import win32api
import win32con
import win32com.client
from ctypes import windll
import os
import time
import json
import requests
import base64
import random
from io import BytesIO
from PIL import Image
from sys import version_info
import logging
import sys
from requests.exceptions import ConnectTimeout, TooManyRedirects, ConnectionError
from functools import wraps
from urllib3.exceptions import NewConnectionError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(levelname)s:%(message)s")

screen_handler = logging.StreamHandler(sys.stdout)
file_handler = logging.FileHandler('sjx.log', 'a', 'utf-8')

screen_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(screen_handler)
logger.addHandler(file_handler)
BDS_TOKEN = 'xxxxxxxxx'
HEADERS_FOR_BD = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3314.0 Safari/537.36 SE 2.X MetaSr 1.0',
    'Cookie': 'xxxxxxxx'
}


class BaseSpiderError(Exception):
    def __str__(self):
        info = '错误信息:{}'.format(self.error_info)
        return info


class MaxRteiesButFail(BaseSpiderError):
    def __init__(self, msg):
        """
        获取百度王牌的UploadId失败后抛出的异常
        :param msg: 文件百度网盘路径
        :param res_info: 网页接口请求返回值
        """
        self.error_info = '多次重试后仍旧失败:{}'.format(msg)


def reconnect(max_retries=999, delay=5, not_retry_exception_list=None, ignores=False):
    """
    用于网络请求失败后重试
    :param max_retries: 重试次数
    :param delay: 重试延迟时间
    :param not_retry_exception_list: 不重试的异常类型，是一个列表
    :return:
    """
    if not_retry_exception_list is None:
        not_retry_exception_list = []
    error_type = (ConnectTimeout, ConnectionError, TooManyRedirects, NewConnectionError)

    def wrapper(func):
        @wraps(func)
        def _wrapper(*args, **kwargs):
            nonlocal delay, max_retries
            while max_retries > 0:
                try:
                    result = func(*args, **kwargs)
                except Exception as ex:
                    exception_type = type(ex)
                    if not isinstance(exception_type, error_type) and not ignores:
                        raise ex
                    else:
                        logger.error(ex)
                        logger.info('正在重试...')
                        time.sleep(delay)
                        max_retries -= 1
                else:
                    return result  # 成功的情况
            if max_retries <= 0:
                raise MaxRteiesButFail(func.__name__)  # 重试次数用完，仍未成功，抛出异常

        return _wrapper

    return wrapper


class BaseBDError(Exception):
    def __str__(self):
        info = '错误信息:{}|返回信息:{}'.format(self.error_info, self.res_info)
        return info


class GetUploadIdError(BaseBDError):
    def __init__(self, msg, res_info):
        """
        获取百度王牌的UploadId失败后抛出的异常
        :param msg: 文件百度网盘路径
        :param res_info: 网页接口请求返回值
        """
        self.error_info = '获取：{}的UpLoadId失败'.format(msg)
        self.res_info = res_info


class UpLoadDataError(BaseBDError):
    def __init__(self, msg, res_info):
        """
        上传文件失败后抛出的异常
        :param msg: 文件百度网盘路径
        :param res_info: 网页接口请求返回值
        """
        self.error_info = '上传文件：{}失败'.format(msg)
        self.res_info = res_info


class CreataBDFileError(BaseBDError):
    def __init__(self, msg, res_info):
        """
        创建百度网盘文件失败后抛出的异常
        :param msg: 文件百度网盘路径
        :param res_info: 网页接口请求返回值
        """
        self.error_info = '创建文件：{}失败'.format(msg)
        self.res_info = res_info


class DeleteError(BaseBDError):
    def __init__(self, msg, res_info):
        self.error_info = '删除操作失败，路径数量：{}'.format(msg)
        self.res_info = res_info


def get_upload_id(net_file_path, s, is_split=True):
    url = "https://pan.baidu.com/api/precreate"
    data = {
        "path": net_file_path,
        "target_path": "/".join(net_file_path.split("/")[:-1]) + '/',
        "autoinit": 1,
        "isdir": 0,
        'bdstoken': BDS_TOKEN,
        "block_list": '["5910a591dd8fc18c32a8f3df4fdc1761","a5fc157d78e6ad1c7e114b056c92821e"]'
    }
    if not is_split:
        data['block_list'] = '["5910a591dd8fc18c32a8f3df4fdc1761"]'
    params = {
        "startLogTime": int(time.time() * 1000),
    }
    try:
        resp = s.post(
            url=url,
            headers=HEADERS_FOR_BD,
            params=params,
            data=data,
        )
        json_data = json.loads(resp.text)
        upload_id = json_data["uploadid"]
        if not json_data['errno'] == 0:
            raise GetUploadIdError(net_file_path, resp.text)
        logger.debug('获取upload成功:{}'.format(upload_id))
        return upload_id
    except Exception:
        raise GetUploadIdError(net_file_path, None)


def upload_data_func(upload_data, net_file_path, upload_id, s, partseq=0):
    url = "https://nj02ct01.pcs.baidu.com/rest/2.0/pcs/superfile2"
    files = {
        'file': ('blob', upload_data, 'application/octet-stream'),
    }
    params = {
        "method": "upload",
        'type': 'tmpfile',
        "path": net_file_path,
        "uploadid": upload_id,
        'app_id': '250528',
        'channel': 'chunlei',
        'clienttype': '0',
        'web': '1',
        'uploadsign': '0',
        'partseq': str(partseq),
        'bdstoken': BDS_TOKEN,
    }

    while True:
        try:
            resp = s.post(
                url=url,
                headers=HEADERS_FOR_BD,
                params=params,
                files=files,
            )
            try:
                x_bs_file_size = resp.headers["x-bs-file-size"]
            except:
                x_bs_file_size = 0
            try:
                content_md5 = resp.headers["Content-MD5"]
            except:
                content_md5 = ''
            logger.debug('上传分片成功,size:{},res:{}'.format(x_bs_file_size, resp.text))
            return x_bs_file_size, content_md5
        except Exception as e:
            logger.error(e)
            print(upload_data)
            logger.error('上传失败，正在重试')
            time.sleep(1)


def creat_path(end_length, block_list, net_file_path, upload_id, s):
    x_bs_file_size = end_length
    url = "https://pan.baidu.com/api/create"
    params = {
        "isdir": 0,
        "rtype": 1,
        "channel": "chunlei",
        "web": 1,
        "app_id": "250528",
        "clienttype": 0,
        'bdstoken': BDS_TOKEN,
    }
    data = {
        "path": net_file_path,
        "size": x_bs_file_size,
        "uploadid": upload_id,
        "target_path": "/".join(net_file_path.split("/")[:-1]) + '/',
        "block_list": str(block_list).replace("'", '"'),
    }
    try:
        resp = s.post(
            url=url,
            headers=HEADERS_FOR_BD,
            params=params,
            data=data,
        )
        json_data = json.loads(resp.text)
        if not json_data['errno'] == 0:
            raise CreataBDFileError(net_file_path, resp.text)
        else:
            logger.debug("文件上传成功:{}".format(net_file_path))
            return True
    except Exception as ex:
        print(data)
        raise CreataBDFileError(net_file_path, None)


# 百度网盘上传文件
def upload_file(file_generator=None, net_file_path=None, binary_data=None):
    s = requests.session()
    s.keep_alive = False
    content_length = 0
    md5_list = []
    if file_generator:
        if next(file_generator):
            logger.info('分片上传:{}'.format(net_file_path))
            upload_id = get_upload_id(net_file_path, s)
            logger.info('获取uploadid成功:{}-{}'.format(net_file_path, upload_id))
            for index, data in enumerate(file_generator):
                data_size, data_md5 = upload_data_func(data, net_file_path, upload_id, s, index)
                logger.info('上传分片{}成功:{}'.format(index, net_file_path))
                content_length += int(data_size)
                md5_list.append(data_md5)
        else:
            logger.info('不分片上传:{}'.format(net_file_path))
            upload_id = get_upload_id(net_file_path, s, is_split=False)
            logger.info('获取uploadid成功:{}-{}'.format(net_file_path, upload_id))
            data = next(file_generator)
            data_size, data_md5 = upload_data_func(data, net_file_path, upload_id, s)
            content_length += int(data_size)
            md5_list.append(data_md5)
    else:
        logger.info('不分片上传:{}'.format(net_file_path))
        upload_id = get_upload_id(net_file_path, s, is_split=False)
        logger.info('获取uploadid成功:{}-{}'.format(net_file_path, upload_id))
        data_size, data_md5 = upload_data_func(binary_data, net_file_path, upload_id, s)
        content_length += int(data_size)
        md5_list.append(data_md5)

    creat_path(content_length, md5_list, net_file_path, upload_id, s)
    logger.info('文件上传成功:{}'.format(net_file_path))


def set_on_start():
    logger.info('正在设置程序开机自启动...')
    path = sys.argv[0]
    name = os.path.basename(path).split('.')[0]
    key_name = 'Software\\Microsoft\\Windows\\CurrentVersion\\Run'
    try:
        key = win32api.RegOpenKey(win32con.HKEY_CURRENT_USER, key_name, 0, win32con.KEY_ALL_ACCESS)
        win32api.RegSetValueEx(key, name, 0, win32con.REG_SZ, path)
        win32api.RegCloseKey(key)
        logger.info('程序开机自启动设置完成')
    except Exception as e:
        logger.error(e)
        logger.info('程序开机自启动设置失败')


class Dm:
    def __init__(self):
        logger.info('初始化大漠插件对象...')
        self.dm = self.get_dm()
        if not self.register_pro():
            sys.exit(-1)
        logger.info('大漠插件对象初始化完成')

    @staticmethod
    def register_dm():
        """"
        注册大漠插件到系统
        """
        base_path = os.getcwd()
        dll_path = os.path.join(base_path, 'dm.dll')
        os.system('regsvr32 {} /s'.format(dll_path))

    @staticmethod
    def get_dm():
        """
        获取大漠插件
        如果没注册进行注册
        :return:
        """
        try:
            dm = win32com.client.Dispatch('dm.dmsoft')
            if not dm.ver().startswith('7'):
                raise Exception
            logger.info('大漠插件已注册')
        except Exception as e:
            logger.info(e)
            logger.info('大漠插件未注册')
            logger.info('开始注册大漠插件...')
            Dm.register_dm()
            dm = win32com.client.Dispatch('dm.dmsoft')
            logger.info('大漠插件注册成功')
        return dm

    def register_pro(self):
        """
        使用激活码注册大漠插件
        :return:
        """
        if self.dm.Reg('xxxxxxx', '0001') == 1:
            return True
        else:
            logger.info('大漠插件连接失败')


class Yzm:
    def __init__(self):
        logger.info('开始初始化验证码对象...')
        self.uname = 'xxxxxxx'
        self.pwd = 'xxxxxxx'
        self.softid = 'xxxxxxx'
        logger.info('验证码对象初始化完成')

    @staticmethod
    def base64_api(uname, pwd, softid, img):
        img = img.convert('RGB')
        buffered = BytesIO()
        img.save(buffered, format="JPEG")
        if version_info.major >= 3:
            b64 = str(base64.b64encode(buffered.getvalue()), encoding='utf-8')
        else:
            b64 = str(base64.b64encode(buffered.getvalue()))
        data = {"username": uname, "password": pwd, "softid": softid, "image": b64}
        result = json.loads(requests.post("http://api.ttshitu.com/base64", json=data).text)
        if result['success']:
            return result["data"]["result"]
        else:
            return result["message"]

    def get_yzm_result(self, img_path):
        img = Image.open(img_path)
        logger.info('开始获取验证码结果...')
        result = self.base64_api(uname=self.uname, pwd=self.pwd, softid=self.softid, img=img)
        logger.info('获取到验证码结果:{}'.format(result))
        return result


class DD:
    def __init__(self):
        logger.info('开始初始化DD键鼠驱动对象...')
        base_path = os.getcwd()
        dll_path = os.path.join(base_path, 'DD94687.32.dll')
        self.dd_dll = windll.LoadLibrary(dll_path)
        logger.info('DD键鼠驱动对象初始化完成')

    def down_up(self, code):
        # 进行一组按键。
        self.dd_dll.DD_key(code, 1)
        time.sleep(0.05)
        self.dd_dll.DD_key(code, 2)

    def left_click(self):
        self.dd_dll.DD_btn(1)
        time.sleep(0.3)
        self.dd_dll.DD_btn(2)

    def right_click(self):
        self.dd_dll.DD_btn(4)
        time.sleep(0.05)
        self.dd_dll.DD_btn(8)


class ToRestartException(Exception):
    def __init__(self, *args):
        self.args = args


class FinishException(Exception):
    def __init__(self, handle):
        self.handle = handle


class Lol:
    def __init__(self):
        logger.info('开始初始化LOL对象...')
        self.version_id = 5
        self.addr = 'http://x.x.x.x:xxxxx/{}'
        self.dm = Dm().dm
        self.this_window = None
        self.set_window_position_and_size()
        logger.info('开始设置字库...')
        self.dm.SetDictPwd('xxxxx')
        self.dm.SetDict(0, 'bin/daqu.txt')
        self.dm.SetDict(1, 'bin/legends.txt')
        self.dm.SetDict(2, 'bin/cards.txt')
        self.dm.SetDict(3, 'bin/tokens.txt')
        self.dm.SetDict(4, 'bin/daqu2.txt')
        logger.info('字库设置完成')
        self.token_number = -1
        self.dd = DD()
        self.yzm = Yzm()
        self.cur_window_handle = None
        self.cur_window_size = None
        self.qq_number = None
        self.start_token_number = None
        self.pwd = None
        self.aim_token_number = 0
        self.area = None
        self.from_ = None
        self.game_path = None
        self.start = -1
        self.need = -1
        self.machine_name = ''
        self.init_base_data()
        self.is_setting = True
        self.config_init()
        self.in_gaming = False
        self.legends_list = None
        self.cards = None
        self.legends_position = None
        self.erxing_legends_list = None
        self.erxing_legends_position = None
        self.is_six_level = False
        self.error_times = time.time()
        self.status = 0
        self.pwd_error_times = 0
        self.game_times = 0
        self.is_start = False
        self.open_juejin()
        logger.info('LOL对象初始化完成')

    def get_and_deal_command(self):
        request_data = {
            'machine_name': self.machine_name
        }
        res = requests.post(self.addr.format('get_command'), data=request_data)
        json_data = json.loads(res.text)
        requests.session().close()
        if json_data['data'] == '无命令':
            return
        need_restart = False
        just_close = False
        for command_data in json_data['data']:
            if command_data['command'] == 'new_pwd':
                need_restart = True
                new_pwd = command_data['data']['pwd']
                self.pwd = new_pwd
                with open('setting.conf', 'r', encoding='utf-8') as f:
                    data = f.read()
                    if data.startswith('\ufeff'):
                        data = data.encode('utf8')[3:].decode('utf8')
                    data = json.loads(data)
                    json_data = data
                json_data['PWD'] = self.pwd
                with open('setting.conf', 'w', encoding='utf-8') as f:
                    json_text = json.dumps(json_data, ensure_ascii=False)
                    f.write(json_text)
            elif command_data['command'] == 'close_qq':
                need_restart = True
                with open('setting.conf', 'r', encoding='utf-8') as f:
                    data = f.read()
                    if data.startswith('\ufeff'):
                        data = data.encode('utf8')[3:].decode('utf8')
                    data = json.loads(data)
                    json_data = data
                json_data['success'] = 1
                with open('setting.conf', 'w', encoding='utf-8') as f:
                    json_text = json.dumps(json_data, ensure_ascii=False)
                    f.write(json_text)
            elif command_data['command'] == 'update':
                os.system('taskkill /IM "League of Legends.exe" /F')
                os.system('taskkill /IM LeagueClient.exe /F')
                os.system('taskkill /IM Client.exe /F')
                os.system('taskkill /IM TPHelper.exe /F')
                update_time = command_data['data']['update_time']
                timeArray = time.strptime(update_time, "%Y-%m-%dT%H:%M")
                # 转换为时间戳
                update_time_stamp = int(time.mktime(timeArray))
                data = {
                    'qq_number': self.qq_number,
                    'area': self.area,
                    'start_coin': self.start,
                    'now_coin': self.token_number,
                    'need_all': self.need,
                    'status': '等待更新游戏',
                    'upgrade_time': time.time(),
                    'machine_name': self.machine_name,
                    'pwd': self.pwd,
                    'version_id': self.version_id,
                    'from': self.from_
                }
                self.send_info(data)
                while True:
                    now = int(time.time())
                    time.sleep(30)
                    if now >= update_time_stamp:
                        data = {
                            'qq_number': self.qq_number,
                            'area': self.area,
                            'start_coin': self.start,
                            'now_coin': self.token_number,
                            'need_all': self.need,
                            'status': '正在更新游戏',
                            'upgrade_time': time.time(),
                            'machine_name': self.machine_name,
                            'pwd': self.pwd,
                            'version_id': self.version_id,
                            'from': self.from_
                        }
                        self.send_info(data)
                        while True:
                            self.on_game()
                            self.get_login_window()
                            for i in range(900):
                                res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/status1.bmp',
                                                      '000000', 0.9,
                                                      2)
                                if res[0] != -1:
                                    raise ToRestartException
                                time.sleep(1)
                                self.check_version()
            if need_restart:
                raise ToRestartException


    def send_info(self, data):
        try:
            res = requests.post(self.addr.format('get_machine_info_from_vm'), data=data).text
        except Exception as e:
            for i in range(15):
                res = requests.post(self.addr.format('get_machine_info_from_vm'), data=data).text
                time.sleep(2)
        if res == 'OK':
            return True
        else:
            for i in range(20):
                try:
                    res = requests.post(self.addr.format('get_machine_info_from_vm'), data=data).text
                except Exception as e:
                    for i in range(15):
                        res = requests.post(self.addr.format('get_machine_info_from_vm'), data=data).text
                        time.sleep(2)
                requests.session().close()
                if res == 'OK':
                    return True
                if i == 19:
                    return False

    def open_juejin(self):
        test_handle = self.dm.FindWindow('', 'aoteman')
        if test_handle:
            return

        juejin_path = os.path.join('xg', '掘金硬件修改大师破解补丁.exe')
        logger.info('正在启动硬件修改器..')
        for j in range(10):
            os.system('taskkill /IM 掘金硬件修改大师破解补丁.exe /F')
            os.system('taskkill /IM 掘金硬件修改大师.exe /F')
            os.system('taskkill /IM Client.exe /F')
            os.system('taskkill /IM "League of Legends.exe" /F')
            os.system('taskkill /IM LeagueClient.exe /F')
            os.system('taskkill /IM Client.exe /F')
            os.system('taskkill /IM TPHelper.exe /F')
            is_continue = False

            for i in range(15):
                if i == 14:
                    is_continue = True
                try:
                    win32api.ShellExecute(0, 'open', juejin_path, '', '', 1)
                    logger.info('硬件修改器启动成功')
                    break
                except Exception:
                    time.sleep(1)
                    continue
            if is_continue:
                continue

            for i in range(30):
                handle = self.dm.FindWindow('', '掘金硬件修改大师_Crack补丁')
                if handle:
                    os.system('taskkill /IM iexplore.exe /F')
                    os.system('taskkill /IM iexplore.exe /F')
                    os.system('taskkill /IM iexplore.exe /F')
                    self.dm.MoveWindow(handle, 0, 0)
                    time.sleep(3)
                    self.dm.SetWindowState(handle, 1)
                    self.dm.MoveTo(133, 59)
                    time.sleep(1)
                    self.dm.LeftClick()
                    time.sleep(0.1)
                    self.dm.MoveTo(0, 0)
                    break
                time.sleep(1)
                if i == 29:
                    is_continue = True
            if is_continue:
                continue

            for i in range(30):
                handle = self.dm.FindWindow('', 'aoteman')
                if handle:
                    os.system('taskkill /IM 掘金硬件修改大师破解补丁.exe /F')
                    self.dm.MoveWindow(handle, 1280, 720)
                    time.sleep(3)
                    self.dm.SetWindowState(handle, 1)
                    self.dm.MoveTo(1305, 754)
                    time.sleep(1)
                    self.dm.LeftClick()
                    time.sleep(1)
                    self.dm.MoveTo(1335, 777)
                    time.sleep(1)
                    self.dm.LeftClick()
                    break
                time.sleep(1)
                if i == 29:
                    is_continue = True
            if is_continue:
                continue

            for i in range(30):
                handle = self.dm.FindWindow('', '会员登录')
                if handle:
                    time.sleep(3)
                    self.dm.SetWindowState(handle, 1)
                    self.dm.MoveTo(1523, 827)
                    time.sleep(1)
                    self.dm.LeftClick()
                    time.sleep(1)
                    self.dm.KeyPressStr('1', 100)

                    self.dm.MoveTo(1548, 865)
                    time.sleep(1)
                    self.dm.LeftClick()
                    time.sleep(1)
                    self.dm.KeyPressStr('1', 100)

                    self.dm.MoveTo(1736, 835)
                    time.sleep(1)
                    self.dm.LeftClick()

                    for k in range(30):
                        handle = self.dm.FindWindow('', '会员登录')
                        if not handle:
                            break
                        if k == 29:
                            is_continue = True
                        time.sleep(1)
                    break
                time.sleep(1)
                if i == 29:
                    is_continue = True
            if is_continue:
                continue

            self.on_game()
            self.get_login_window()
            for i in range(45):
                res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/status1.bmp',
                                      '000000', 0.9,
                                      2)
                if res[0] != -1:
                    logger.info('硬件修改成功')
                    os.system('taskkill /IM Client.exe /F')
                    break
                if i == 44:
                    is_continue = True
                time.sleep(1)

            if is_continue:
                continue
            else:
                break

    def init_base_data(self):

        logger.info('开始初始化玩家信息...')
        with open('setting.conf', 'r', encoding='utf-8') as (f):
            data = f.read()
            if data.startswith('\ufeff'):
                data = data.encode('utf8')[3:].decode('utf8')
            data = json.loads(data)
            self.qq_number = data['QQ']
            self.pwd = data['PWD']
            self.area = data['Area']
            self.game_path = data['GamePath']
            self.start = data['Start']
            self.need = data['Need']
            self.machine_name = data['MachineName']
            self.from_ = data['From']
            is_success = data['success']
            self.check_version()
            if self.qq_number == -1 or self.qq_number == '-1' or is_success == 1 or is_success == '1':
                logger.info('向服务器请求账号...')
                data = {
                    'machine-pre': self.machine_name.split('|')[0]
                }
                server_data = requests.post(self.addr.format('get_qq'), data=data).text
                server_json_data = json.loads(server_data)
                server_data = server_json_data['data']
                if server_data == '无账号':
                    logger.info('服务器无账号..')
                    while True:
                        logger.info('向服务器请求账号...')
                        data = {
                            'machine-pre': self.machine_name.split('|')[0]
                        }
                        server_data = requests.post(self.addr.format('get_qq'), data=data).text
                        server_json_data = json.loads(server_data)
                        server_data = server_json_data['data']
                        if server_data != '无账号':
                            self.qq_number = server_data['qq_number']
                            self.pwd = server_data['qq_pwd']
                            self.area = server_data['area']
                            self.need = server_data['need']
                            self.from_ = server_data['from']
                            break
                        data = {
                            'qq_number': self.qq_number,
                            'area': self.area,
                            'start_coin': self.start,
                            'now_coin': self.token_number,
                            'need_all': self.need,
                            'status': '等待账号中...',
                            'upgrade_time': time.time(),
                            'machine_name': self.machine_name,
                            'pwd': self.pwd,
                            'version_id': self.version_id,
                            'from': self.from_
                        }
                        self.send_info(data)
                        time.sleep(30)
                data = {
                    'qq_number': self.qq_number,
                    'area': self.area,
                    'start_coin': self.start,
                    'now_coin': self.token_number,
                    'need_all': self.need,
                    'status': '获取账号成功',
                    'upgrade_time': time.time(),
                    'machine_name': self.machine_name,
                    'pwd': self.pwd,
                    'version_id': self.version_id,
                    'from': self.from_
                }
                self.send_info(data)
                with open('setting.conf', 'r', encoding='utf-8') as f:
                    data = f.read()
                    if data.startswith('\ufeff'):
                        data = data.encode('utf8')[3:].decode('utf8')
                    data = json.loads(data)
                    json_data = data
                json_data['success'] = -1
                json_data['QQ'] = server_data['qq_number']
                json_data['PWD'] = server_data['qq_pwd']
                json_data['Area'] = server_data['area']
                json_data['Need'] = server_data['need']
                json_data['From'] = server_data['from']
                with open('setting.conf', 'w', encoding='utf-8') as f:
                    json_text = json.dumps(json_data, ensure_ascii=False)
                    f.write(json_text)

            if self.need == '-1':
                logger.info('Need设置错误')
                sys.exit(-1)
            logger.info('玩家信息初始化完成:{}-{}'.format(self.qq_number, self.area))

    def config_init(self):
        logger.info('开始替换配置文件...')
        # 1.替换host文件
        host_path = r'C:\Windows\System32\drivers\etc\hosts'
        with open('config/hosts', 'r', encoding='utf-8') as f:
            with open(host_path, 'w', encoding='utf-8') as f1:
                hosts_data = f.read()
                f1.write(hosts_data)
                logger.info('host文件替换完成')

        # 2.替换英雄联盟配置文件
        lol_config_path = os.path.join(os.path.join(os.path.dirname(os.path.dirname(self.game_path)), 'Game'), 'Config')
        if not os.path.exists(lol_config_path):
            try:
                os.mkdir(lol_config_path)
            except Exception as e:
                logger.info('游戏路径错误，请重新选择')
                raise e
            item_list = ['game.cfg', 'PersistedSettings.json']
        else:
            item_list = os.listdir(lol_config_path)
            inputini_path = os.path.join(lol_config_path, 'input.ini')
            if os.path.exists(inputini_path):
                os.remove(inputini_path)
        for item in item_list:
            if item not in ['game.cfg', 'PersistedSettings.json']:
                continue
            item_path = os.path.join(lol_config_path, item)
            if os.path.isfile(item_path):
                local_path = os.path.join('config', item)
                with open(local_path, 'r', encoding='utf-8') as f:
                    with open(item_path, 'w', encoding='utf-8') as f1:
                        data = f.read()
                        f1.write(data)
            elif not os.path.exists(item_path):
                local_path = os.path.join('config', item)
                with open(local_path, 'r', encoding='utf-8') as f:
                    with open(item_path, 'w', encoding='utf-8') as f1:
                        data = f.read()
                        f1.write(data)

        lol_game_config_path = os.path.join(
            os.path.join(os.path.dirname(os.path.dirname(self.game_path)), 'LeagueClient'), 'config')
        if not os.path.exists(lol_game_config_path):
            os.mkdir(lol_game_config_path)
        item_path = os.path.join('config', 'LCULocalPreferences.yaml')
        aim_path = os.path.join(lol_game_config_path, 'LCULocalPreferences.yaml')
        with open(item_path, 'r', encoding='utf-8') as f:
            with open(aim_path, 'w', encoding='utf-8') as f1:
                data = f.read()
                f1.write(data)

        xg_config_path = os.path.join('xg', 'User.ini')
        json_data = None
        with open(xg_config_path, 'r') as f:
            json_data = json.load(f)
        json_data['proxy']['proxypath'][0]['path'] = self.game_path
        with open(xg_config_path, 'w') as f:
            json_text = json.dumps(json_data, ensure_ascii=False)
            f.write(json_text)
        logger.info('游戏配置文件替换完成')
        logger.info('替换配置文件完成')

    def get_gaming_window(self):
        logger.info('开始获取游戏窗口...')
        handle = self.dm.FindWindow('RiotWindowClass', 'League of Legends (TM) Client')
        for i in range(180):
            handle = self.dm.FindWindow('RiotWindowClass', 'League of Legends (TM) Client')
            if handle:
                break
            time.sleep(1)
            if i == 179:
                logger.info('获取游戏窗口失败,开始重新启动游戏...')
                raise ToRestartException
        self.cur_window_handle = handle
        self.set_cur_window_size()
        self.set_window_position()
        self.in_gaming = True
        self.is_six_level = False
        logger.info('获取游戏窗口成功')
        os.system('taskkill /IM TPHelper.exe /F')
        data = {
            'qq_number': self.qq_number,
            'area': self.area,
            'start_coin': self.start,
            'now_coin': self.token_number,
            'need_all': self.need,
            'status': '游戏中',
            'upgrade_time': time.time(),
            'machine_name': self.machine_name,
            'pwd': self.pwd,
            'version_id': self.version_id,
            'from': self.from_
        }
        self.send_info(data)
        return True

    def get_login_window(self):
        """
        获取登录窗口的句柄
        :return:
        """
        logger.info('开始获取登录窗口...')
        handle = self.dm.FindWindow('TWINCONTROL', '英雄联盟登录程序')
        for i in range(180):
            handle = self.dm.FindWindow('TWINCONTROL', '英雄联盟登录程序')
            if handle:
                break
            time.sleep(1)
            if i == 179:
                logger.info('获取登录窗口失败,开始重新启动游戏...')
                raise ToRestartException
        self.cur_window_handle = handle
        self.set_cur_window_size()
        self.set_window_position()
        logger.info('获取登录窗口成功')
        data = {
            'qq_number': self.qq_number,
            'area': self.area,
            'start_coin': self.start,
            'now_coin': self.token_number,
            'need_all': self.need,
            'status': '登录阶段',
            'upgrade_time': time.time(),
            'machine_name': self.machine_name,
            'pwd': self.pwd,
            'version_id': self.version_id,
            'from': self.from_
        }
        self.send_info(data)
        self.get_and_deal_command()
        return True

    def get_client_window(self):
        """
        获取登陆后客户端窗口句柄
        :return:
        """
        logger.info('开始获取客户端窗口...')
        handle = self.dm.FindWindow('RCLIENT', 'League of Legends')
        for i in range(180):
            handle = self.dm.FindWindow('RCLIENT', 'League of Legends')
            if handle:
                break
            time.sleep(1)
            if i == 179:
                logger.info('获取客户端窗口失败,开始重新启动游戏...')
                raise ToRestartException
        self.cur_window_handle = handle
        self.set_cur_window_size()
        self.set_window_position()
        logger.info('获取客户端窗口成功')
        os.system('taskkill /IM TPHelper.exe /F')
        data = {
            'qq_number': self.qq_number,
            'area': self.area,
            'start_coin': self.start,
            'now_coin': self.token_number,
            'need_all': self.need,
            'status': '客户端阶段',
            'upgrade_time': time.time(),
            'machine_name': self.machine_name,
            'pwd': self.pwd,
            'version_id': self.version_id,
            'from': self.from_
        }
        self.send_info(data)
        self.get_and_deal_command()
        return True

    def set_window_position(self):
        """
        将窗口放置到左上角
        :param window_handle: 窗口句柄
        :return:
        """
        self.dm.MoveWindow(self.cur_window_handle, 0, 0)
        self.dm.SetWindowState(self.cur_window_handle, 1)

    def set_cur_window_size(self):
        """
        获取当前窗口的大小
        :return:
        """
        for i in range(180):
            # 激活当前窗口
            self.dm.SetWindowState(self.cur_window_handle, 1)
            time.sleep(1)
            # 获取窗口大小
            res = self.dm.GetClientSize(self.cur_window_handle)
            if res[0] != 1 or res[1] == 0:
                if i == 179:
                    raise ToRestartException
                continue
            self.cur_window_size = res
            break
        return True

    def bind_window(self):
        self.dm.BindWindowEx(self.cur_window_handle, 'normal', 'normal', 'normal', 'dx.public.input.ime', 0)

    def is_qq_login(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        # 开始识图QQ登录
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/qq_login.bmp', '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            self.dd.left_click()
            return True
        return False

    def input_qq_number(self):
        step = 0
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        # 开始识图
        # 开始寻找QQ输入框
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/qq_number.bmp', '000000',
                              0.9, 2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(1)
            self.dd.left_click()
            time.sleep(1)
            for _ in range(20):
                self.dd.down_up(self.dd.dd_dll.DD_todc(8))
                time.sleep(0.01)
            for i in self.qq_number:
                self.dd.dd_dll.DD_str(i)
                time.sleep(0.05)
            step += 1
        time.sleep(3)
        # 开始寻找QQ密码输入框
        res = self.dm.FindPic(0, 0, self.cur_window_size[1],
                              self.cur_window_size[2], 'img/qq_pwd.bmp', '000000', 1, 2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(1)
            self.dd.left_click()
            time.sleep(1)
            for _ in range(20):
                self.dd.down_up(self.dd.dd_dll.DD_todc(8))
                time.sleep(0.01)
            for i in self.pwd:
                self.dd.dd_dll.DD_str(i)
                time.sleep(0.05)
            step += 1
        time.sleep(1)
        # 开始寻找同意协议
        res = self.dm.FindPic(0, 0, self.cur_window_size[1],
                              self.cur_window_size[2], 'img/agree.bmp', '000000', 1, 2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(1)
            self.dd.left_click()
            step += 1
        # 开始登录
        res = self.dm.FindPic(0, 0, self.cur_window_size[1],
                              self.cur_window_size[2], 'img/login.bmp', '000000', 1, 2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(1)
            self.dd.left_click()
            step += 1

        time.sleep(3)
        if step >= 3:
            return True
        else:
            return False

    def is_yz(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/yz.bmp', '000000', 0.9,
                              3)
        if res[0] != -1:
            return True
        return False

    def input_yzm(self):
        yzm_result = self.yzm.get_yzm_result('yzm.png')
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        # 开始识别验证码输入位置
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/iyzm.bmp', '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            for i in yzm_result:
                self.dd.dd_dll.DD_str(i)
                time.sleep(0.05)

        # 开始识别验证码提交位置
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/yzmqd.bmp', '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(1.5)
            self.dd.left_click()
            return True
        return False

    def is_pwd_error(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        # 开始识图QQ登录
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/pwderror.bmp', '000000', 0.9,
                              3)
        if res[0] != -1:
            return True
        return False

    def is_dj(self):
        self.set_window_position()
        time.sleep(1)

        # 开始识图QQ登录
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/dj1.bmp', '000000', 0.9,
                              3)
        if res[0] != -1:
            return True
        return False

    def close_pwd_error(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        # 开始识图QQ登录
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/pwderrorqd.bmp', '000000',
                              0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            return True
        return False

    def login_success(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/logincg.bmp', '000000', 0.9,
                              2)
        if res[0] != -1:
            return True
        return False

    def choose_area(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/logincg.bmp', '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(84, 671)
            time.sleep(0.5)
            self.dd.left_click()
        time.sleep(3)

    def confirm_area(self):
        for i in range(10):
            if self.area == '男爵领域':
                self.dm.UseDict(4)
                res = self.dm.FindStrFast(0, 0, self.cur_window_size[1], self.cur_window_size[2], self.area,
                                          'cff8fa-181818', '0.8')
            else:
                self.dm.UseDict(0)
                res = self.dm.FindStrFast(0, 0, self.cur_window_size[1], self.cur_window_size[2], self.area,
                                          'ccbe8f-181818', '0.8')
            if res[0] != -1:
                self.dd.dd_dll.DD_mov(res[1], res[2])
                time.sleep(0.5)
                self.dd.left_click()
                time.sleep(0.5)
                logger.info('选择大区成功:{}'.format(self.area))
                return True
            else:
                self.choose_area()
        return False

    def into_game(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/intogame.bmp', '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            return True
        return False

    def choose_wating(self):
        # 激活当前窗口
        self.set_window_position()
        # time.sleep(1)

        # 开始识图QQ登录
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/waiting.bmp', '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            return True
        return False

    # def open_setting(self):
    #     # 激活当前窗口
    #     self.set_window_position()
    #     time.sleep(1)
    #
    #     res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/setting.bmp',
    #                           '000000', 0.9,
    #                           2)
    #     if res[0] != -1:
    #         self.dd.dd_dll.DD_mov(res[1], res[2])
    #         time.sleep(0.5)
    #         self.dd.left_click()
    #         self.dd.dd_dll.DD_mov(0, 0)
    #         return True
    #     return False
    #
    # def not_close_client(self):
    #
    #     # 激活当前窗口
    #     self.set_window_position()
    #     time.sleep(1)
    #
    #     res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/notcloseclient.bmp',
    #                           '000000', 0.9,
    #                           2)
    #     if res[0] != -1:
    #         self.dd.dd_dll.DD_mov(res[1], res[2])
    #         time.sleep(0.5)
    #         self.dd.left_click()
    #         self.dd.dd_dll.DD_mov(0, 0)
    #         return True
    #     return False
    #
    # def setting_ok(self):
    #     # 激活当前窗口
    #     self.set_window_position()
    #     time.sleep(1)
    #
    #     res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/settingok.bmp',
    #                           '000000', 0.9,
    #                           2)
    #     if res[0] != -1:
    #         self.dd.dd_dll.DD_mov(res[1], res[2])
    #         time.sleep(0.5)
    #         self.dd.left_click()
    #         self.dd.dd_dll.DD_mov(0, 0)
    #         return True
    #     return False
    #
    # def low_machine(self):
    #     self.set_window_position()
    #     time.sleep(1)
    #
    #     res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/low_machine.bmp',
    #                           '000000', 0.9,
    #                           2)
    #     if res[0] != -1:
    #         self.dd.dd_dll.DD_mov(res[1], res[2])
    #         time.sleep(0.5)
    #         self.dd.left_click()
    #         self.dd.dd_dll.DD_mov(0, 0)
    #         return True
    #     return False

    # def client_setting(self):
    #     """
    #     客户端设置
    #     在游戏过程中不关闭客户端
    #     :return:
    #     """
    #     if self.is_setting:
    #         return True
    #     for i in range(10):
    #         self.open_setting()
    #         res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/settingok.bmp','000000', 0.9,2)
    #         if res[0] != -1:
    #             break
    #         elif i == 9:
    #             raise ToRestartException
    #         time.sleep(1)
    #
    #     for i in range(20):
    #         self.low_machine()
    #         res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/low_machine_ok.bmp', '000000',
    #                               0.9, 2)
    #         if res[0] != -1:
    #             break
    #         elif i == 19:
    #             raise ToRestartException
    #         time.sleep(1)
    #
    #     self.not_close_client()
    #
    #     for i in range(15):
    #         self.setting_ok()
    #         res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/room.bmp|img/play.bmp|img/status5.bmp',
    #                               '000000',
    #                               0.9, 2)
    #         if res[0] != -1:
    #             break
    #         elif i == 14:
    #             raise ToRestartException
    #         time.sleep(1)
    #
    #     self.is_setting = True
    #     return True

    def play(self):
        """
        选择play
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/play.bmp|img/room.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('进入游戏选择')
            return True
        return False

    def choose_pvp(self):
        """
        选择玩家对战模式
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/pvp.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('选择玩家对战')
            return True
        return False

    def choose_yunding(self):
        """
        选择云顶之奕模式
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/yunding.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('选择云顶之弈模式')
            return True
        return False

    def choose_pipei(self):
        """
        选择云顶之奕匹配模式
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/pipei.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('选择匹配模式')
            return True
        return False

    def confirm_game(self):
        """"
        确认游戏类型，进入房间
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/confirmgame.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            return True
        return False

    def close_team(self):
        """
        关闭队伍
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/close_team.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('设置小队为私密小队')
            return True
        return False

    def find_game(self):
        """
        寻找对局
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/find_game.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
        if self.is_in_queue():
            return True
        return False

    def find_game2(self):
        """
        寻找对局
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/find_game.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            return True
        return False

    def is_in_queue(self):
        """
        正在匹配对局状态
        :return:
        """
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/in_queue.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            return True
        return False

    def start_game(self):
        """
        接受游戏
        :return:
        """
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/start_game.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('接受游戏')
            return True
        return False

    # 第一阶段：登录阶段
    def login(self):
        # 输入密码登录循环
        while True:
            login_sc = False
            # 选择登录方式、输入账号密码
            for i in range(10):
                if self.is_qq_login():
                    time.sleep(8)
                    self.input_qq_number()
                    break
                elif self.input_qq_number():
                    break
                else:
                    time.sleep(1)
                    logger.info('找不到登录方式:{}'.format(i))
                    if i == 9:
                        raise ToRestartException
                    continue
            # 验证码和密码错误处理
            times = 0
            while True:
                if self.is_yz():
                    self.dm.CapturePng(574, 423, 703, 475, 'yzm.png')
                    self.input_yzm()
                    times = 0
                elif self.is_pwd_error():
                    self.pwd_error_times += 1
                    logger.info('密码错误：{}'.format(self.pwd_error_times))
                    data = {
                        'qq_number': self.qq_number,
                        'area': self.area,
                        'start_coin': self.start,
                        'now_coin': self.token_number,
                        'need_all': self.need,
                        'status': '密码错误-{}'.format(self.pwd_error_times),
                        'upgrade_time': time.time(),
                        'machine_name': self.machine_name,
                        'pwd': self.pwd,
                        'version_id': self.version_id,
                        'from': self.from_
                    }
                    self.send_info(data)
                    self.close_pwd_error()
                    if self.pwd_error_times > 8:
                        logger.info('密码错误8次，等待新密码')
                        while True:
                            self.get_and_deal_command()
                            time.sleep(30)
                    break
                elif self.is_dj():
                    logger.info('账号冻结')
                    while True:
                        data = {
                            'qq_number': self.qq_number,
                            'area': self.area,
                            'start_coin': self.start,
                            'now_coin': self.token_number,
                            'need_all': self.need,
                            'status': '账号冻结',
                            'upgrade_time': time.time(),
                            'machine_name': self.machine_name,
                            'pwd': self.pwd,
                            'version_id': self.version_id,
                            'from': self.from_
                        }
                        self.send_info(data)
                        while True:
                            self.get_and_deal_command()
                            time.sleep(30)
                elif self.login_success():
                    login_sc = True
                    break
                times += 1
                if times > 15:
                    raise ToRestartException
            if login_sc:
                self.error_times = time.time()
                break

    # 第二阶段：选择大区阶段
    def go_to_game(self):
        """
        选择游戏区
        :return:
        """
        self.confirm_area()
        self.into_game()
        time.sleep(5)
        handle = self.dm.FindWindow('TWINCONTROL', '英雄联盟登录程序')
        if handle:
            res = self.dm.GetClientSize(handle)
            if res[1]:
                self.choose_wating()
        self.error_times = time.time()
        self.get_client_window()

    # 第三阶段：游戏大厅阶段
    def game_client_status(self):
        os.system('taskkill /IM TPHelper.exe /F')
        for i in range(10):
            if self.play():
                return True
            if i == 9:
                return False

    # 第四阶段：游戏类型选择阶段
    def choose_game_status(self):
        for i in range(15):
            self.choose_pvp()
            self.choose_yunding()
            self.choose_pipei()
            if self.confirm_game():
                break
            if i == 9:
                raise ToRestartException

    # 第五阶段：在房间中的阶段：
    def in_room_status(self):
        # 查询代币
        os.system('taskkill /IM TPHelper.exe /F')
        for i in range(15):
            self.open_zlp()
            if self.get_tokens_number():
                break
        # 检查版本更新
        self.check_version()
        for i in range(60):
            self.play()
            time.sleep(3)
            if self.find_game2():
                break
            if i == 60:
                raise ToRestartException
        time.sleep(3)
        self.close_team()
        for i in range(40):
            if self.find_game():
                logger.info('寻找对局成功')
                break
            if i == 39:
                self.find_and_close_queue()
                raise ToRestartException
        for i in range(300):
            self.start_game()
            handle = self.dm.FindWindow('RiotWindowClass', 'League of Legends (TM) Client')
            if handle:
                self.game_times += 1
                if not self.token_number == '暂未获取到':
                    cur_need = int(self.need) - (int(self.token_number) - int(self.start))
                else:
                    cur_need = 'None'
                self.dm.SetWindowText(self.this_window,
                                      '第{}局游戏,开始:{},代币:{},还需：{}，账号:{}-{}'.format(self.game_times, self.start,
                                                                                 self.token_number, cur_need,
                                                                                 self.qq_number, self.area))
                data = {
                    'qq_number': self.qq_number,
                    'area': self.area,
                    'start_coin': self.start,
                    'now_coin': self.token_number,
                    'need_all': self.need,
                    'status': '获取战利品成功',
                    'upgrade_time': time.time(),
                    'machine_name': self.machine_name,
                    'pwd': self.pwd,
                    'version_id': self.version_id,
                    'from': self.from_
                }
                self.send_info(data)
                break
            if i > 120:
                res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2],
                                      'img/play.bmp|img/room.bmp',
                                      '000000', 0.9,
                                      2)
                if res[0] != -1:
                    self.error_times = time.time()
                    logger.info('游戏队列中时跳出房间外...')
                    return
            if i == 299:
                raise ToRestartException
        self.error_times = time.time()
        self.get_gaming_window()

    def open_zlp(self):
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/zlp.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('打开战利品')
            return True
        return False

    def get_tokens_number(self):
        self.set_window_position()
        time.sleep(1)
        self.is_need_sure()
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/db.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('发现全球总决赛代币')
            logger.info('正在读取代币数量...')
            self.dm.UseDict(3)
            res = self.dm.Ocr(res[1], res[2], res[1] + 55, res[2] + 60,
                              'ddd1a6-000000', 0.9)
            if res:
                self.token_number = res
                logger.info('获取代币数量成功:{}'.format(self.token_number))

                if self.start == '-1' or self.start == -1:
                    self.start = self.token_number
                    with open('setting.conf', 'r', encoding='utf-8') as f:
                        data = f.read()
                        if data.startswith('\ufeff'):
                            data = data.encode('utf8')[3:].decode('utf8')
                        data = json.loads(data)
                        json_data = data
                    json_data['Start'] = self.start
                    with open('setting.conf', 'w', encoding='utf-8') as f:
                        json_text = json.dumps(json_data, ensure_ascii=False)
                        f.write(json_text)
                    self.dm.CapturePng(0, 0, 1280, 720, 'start-{}.png'.format(self.qq_number))
                    with open('start-{}.png'.format(self.qq_number), 'rb') as f:
                        net_file_path = '/云顶截图/{}/start-{}.png'.format(self.qq_number, self.qq_number)
                        try:
                            upload_file(net_file_path=net_file_path, binary_data=f.read())
                        except Exception as e:
                            data = {
                                'qq_number': self.qq_number,
                                'area': self.area,
                                'start_coin': self.start,
                                'now_coin': self.token_number,
                                'need_all': self.need,
                                'status': '上传首图失败',
                                'upgrade_time': time.time(),
                                'machine_name': self.machine_name,
                                'pwd': self.pwd,
                                'version_id': self.version_id,
                                'from': self.from_
                            }
                            self.send_info(data)
                            while True:
                                time.sleep(9999)
                cur_need = int(self.need) - (int(self.token_number) - int(self.start))

                if cur_need <= 0:
                    with open('setting.conf', 'r', encoding='utf-8') as f:
                        data = f.read()
                        if data.startswith('\ufeff'):
                            data = data.encode('utf8')[3:].decode('utf8')
                        data = json.loads(data)
                        json_data = data
                    json_data['success'] = 1
                    with open('setting.conf', 'w', encoding='utf-8') as f:
                        json_text = json.dumps(json_data, ensure_ascii=False)
                        f.write(json_text)
                    data = {
                        'qq_number': self.qq_number,
                        'area': self.area,
                        'start_coin': self.start,
                        'now_coin': self.token_number,
                        'need_all': self.need,
                        'status': '完成',
                        'upgrade_time': time.time(),
                        'machine_name': self.machine_name,
                        'pwd': self.pwd,
                        'version_id': self.version_id,
                        'from': self.from_
                    }
                    self.send_info(data)
                    while True:
                        self.dm.CapturePng(0, 0, 1280, 720, 'end-{}.png'.format(self.qq_number))
                        with open('end-{}.png'.format(self.qq_number), 'rb') as f:
                            net_file_path = '/云顶截图/{}/end-{}.png'.format(self.qq_number, self.qq_number)
                            try:
                                upload_file(net_file_path=net_file_path, binary_data=f.read())
                            except Exception as e:
                                data = {
                                    'qq_number': self.qq_number,
                                    'area': self.area,
                                    'start_coin': self.start,
                                    'now_coin': self.token_number,
                                    'need_all': self.need,
                                    'status': '上传完成图失败',
                                    'upgrade_time': time.time(),
                                    'machine_name': self.machine_name,
                                    'pwd': self.pwd,
                                    'version_id': self.version_id,
                                    'from': self.from_
                                }
                                self.send_info(data)
                                while True:
                                    time.sleep(9999)
                        x = self.dm.CreateFoobarRect(self.this_window, 0, 0, 640, 720)
                        self.dm.FoobarSetFont(x, '宋体', 25, 1)
                        self.dm.FoobarPrintText(x, '完成', 'ff0000')
                        raise FinishException(handle=x)

                # if not os.path.exists('start-{}.png'.format(self.qq_number)):
                #     self.dm.CapturePng(0, 0, 1280, 720, 'start-{}.png'.format(self.qq_number))
                #     with open('start-{}.png'.format(self.qq_number), 'rb') as f:
                #         net_file_path = '/云顶截图/{}/start-{}.png'.format(self.qq_number, self.qq_number)
                #         try:
                #             upload_file(net_file_path=net_file_path, binary_data=f.read())
                #         except Exception as e:
                #             data = {
                #                 'qq_number': self.qq_number,
                #                 'area': self.area,
                #                 'start_coin': self.start,
                #                 'now_coin': self.token_number,
                #                 'need_all': self.need,
                #                 'status': '上传首图失败',
                #                 'upgrade_time': time.time(),
                #                 'machine_name': self.machine_name,
                #                 'pwd': self.pwd,
                #                 'version_id': self.version_id,
                #                 'from': self.from_
                #             }
                #             self.send_info(data)
                #             while True:
                #                 time.sleep(9999)
                #     try:
                #         pass
                #     except Exception as e:
                #         os.remove('start-{}.png'.format(self.qq_number))
                #         raise ToRestartException

                if int(self.token_number) >= self.aim_token_number:
                    self.dm.CapturePng(0, 0, 1280, 720, 'now-{}.png'.format(self.qq_number))
                    with open('now-{}.png'.format(self.qq_number), 'rb') as f:
                        net_file_path = '/云顶截图/{}/now-{} {}.png'.format(self.qq_number, self.qq_number, time.strftime(
                            '%Y{y}%m{m}%d{d} %H{h}%M{f}%S{s}',
                            time.localtime(time.time())).format(y='年', m='月', d='日', h='时', f='分', s='秒'))
                        print(net_file_path)
                        try:
                            upload_file(net_file_path=net_file_path, binary_data=f.read())
                        except Exception as e:
                            pass
                    try:
                        pass
                    except Exception as e:
                        os.remove('end-{}.png'.format(self.qq_number))
                        raise ToRestartException
                    else:
                        # 需要关闭游戏关闭删除虚拟机留出空位
                        pass

                return True
            else:
                logger.info('未获取到代币数量')
        return False

    def find_and_close_queue(self):
        self.set_window_position()

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/close_queue.bmp', '000000',
                              0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            logger.info('出现异常，关闭房间')
            return True
        return False

    def on_game(self):
        """
        启动游戏
        :param self:
        :return:
        """
        logger.info('开始启动游戏...')
        for i in range(15):
            if i == 14:
                return False
            try:
                win32api.ShellExecute(0, 'open', self.game_path, '', '', 1)
                logger.info('游戏启动成功')
                return True
            except Exception:
                time.sleep(1)
                continue

    def is_in_bz_status(self):
        self.set_window_position()
        if self.is_close_game():
            return
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/bz.bmp',
                              '000000', 0.9,
                              2)
        if res[0] == -1:
            logger.info('正在备战状态...')
            return True
        return False

    def read_legends_info(self, position):
        position = position.split(',')
        self.set_window_position()
        self.dd.dd_dll.DD_mov(int(position[1]) + 43, int(position[2]) + 58)
        time.sleep(0.01)
        self.dd.right_click()
        time.sleep(0.35)
        self.dm.UseDict(1)
        res = self.dm.Ocr(int(position[1]), int(position[2]) - 200, int(position[1]) + 350, int(position[2]) + 200,
                          'ffffff-505050', 0.8)
        self.legends_list.append(res)

    def get_legends_info(self):
        """
        获取场上的英雄名
        :return:
        """
        logger.info('正在读取一星英雄信息...')
        self.set_window_position()

        res = self.dm.FindPicEx(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/info.bmp',
                                '000000', 0.9,
                                2)
        if res:
            legends_postion_list = res.split('|')
            self.legends_list = []
            self.legends_position = []
            self.legends_position = legends_postion_list.copy()
            for postion in legends_postion_list:
                self.read_legends_info(postion)
            self.dd.right_click()
        logger.info('一星英雄信息读取完成:{}'.format(self.legends_list))

    def get_card_info(self):
        logger.info('正在读取选秀区卡牌信息...')
        self.cards = []
        self.dm.useDict(2)
        # 第一张卡
        res = self.dm.Ocr(168, 659, 312, 764, 'cccccc-505050', 0.9)
        if res:
            self.cards.append(res)
        # 第二张卡
        res = self.dm.Ocr(310, 659, 453, 764, 'cccccc-505050', 0.9)
        if res:
            self.cards.append(res)
        # 第三张卡
        res = self.dm.Ocr(454, 659, 597, 764, 'cccccc-505050', 0.9)
        if res:
            self.cards.append(res)
        # 第四张卡
        res = self.dm.Ocr(598, 659, 742, 764, 'cccccc-505050', 0.9)
        if res:
            self.cards.append(res)
        # 第五张卡
        res = self.dm.Ocr(741, 659, 886, 764, 'cccccc-505050', 0.9)
        if res:
            self.cards.append(res)
        logger.info('卡牌区信息读取成功:{}'.format(self.cards))

    def buy_cards(self, scan):
        logger.info('正在处理英雄和卡牌...')
        # 买英雄
        if self.legends_list is None:
            self.legends_list = []

        if self.erxing_legends_list is None:
            self.erxing_legends_list = []

        to_buy_list = []
        if True:
            for index, item in enumerate(self.cards):
                if item in self.legends_list or item in self.erxing_legends_list:
                    data = (index + 1, item)
                    to_buy_list.append(data)

            legend_number = len(self.legends_list)
            temp_list = self.cards.copy()
            if legend_number < 8:
                for index, item in enumerate(self.cards):
                    if item in temp_list[index + 1:] or item in temp_list[:index]:
                        data = (index + 1, item)
                        to_buy_list.append(data)
                        legend_number += 1

            if legend_number < 8:
                data = (random.randint(1, 5), None)
                to_buy_list.append(data)
        else:
            legends_need = ['诡术妖姬', '永恒梦魇', '扭曲树精', '翠神', '虚空遁地兽', '皎月女神', '光辉女郎']
            for index, item in enumerate(self.cards):
                if item in legends_need:
                    data = (index + 1, item)
                    to_buy_list.append(data)

        # 去重
        temp_list = []
        for item in to_buy_list:
            if item not in temp_list:
                temp_list.append(item)
        to_buy_list = temp_list.copy()
        logger.info('待购买英雄列表:{}'.format(to_buy_list))
        for item in to_buy_list:
            index = item[0]
            if index == 1:
                self.dd.dd_dll.DD_mov(246, 711)
                time.sleep(0.1)
                self.dd.left_click()
            elif index == 2:
                self.dd.dd_dll.DD_mov(386, 716)
                time.sleep(0.1)
                self.dd.left_click()
            elif index == 3:
                self.dd.dd_dll.DD_mov(520, 707)
                time.sleep(0.1)
                self.dd.left_click()
            elif index == 4:
                self.dd.dd_dll.DD_mov(671, 712)
                time.sleep(0.1)
                self.dd.left_click()
            elif index == 5:
                self.dd.dd_dll.DD_mov(799, 715)
                time.sleep(0.1)
                self.dd.left_click()
            time.sleep(1.5)
        # 卖英雄
        sold_list = []
        if True:
            legend_number = len(self.legends_list)
            self.legends_list.append('XXX')
            if len(self.legends_list) > 9:
                for index, item in enumerate(self.legends_list[:-1]):
                    if item not in self.cards and (
                            item not in self.legends_list[index + 1:] and item not in self.legends_list[
                                                                                      :index]) and item not in self.erxing_legends_list:
                        sold_list.append([index, item])
                        legend_number -= 1
                        if legend_number <= 9:
                            break
        else:
            legends_need = ['诡术妖姬', '永恒梦魇', '扭曲树精', '翠神', '虚空遁地兽', '皎月女神', '光辉女郎']
            for index, item in enumerate(self.legends_list):
                if item not in legends_need and item:
                    sold_list.append([index, item])
        if not scan:
            sold_list = []
        logger.info('待卖出英雄列表:{}'.format(sold_list))
        for item in sold_list:
            index = item[0]
            position = self.legends_position[index].split(',')
            self.dd.dd_dll.DD_mov(int(position[1]) + 35, int(position[2]) + 50)
            time.sleep(0.1)
            self.dd.dd_dll.DD_btn(1)
            time.sleep(0.2)
            self.dd.dd_dll.DD_mov(408, 704)
            time.sleep(0.2)
            self.dd.dd_dll.DD_btn(2)
            time.sleep(0.2)

    def up_level(self):
        self.set_window_position()

        self.dd.dd_dll.DD_mov(110, 733)
        time.sleep(0.05)
        self.dd.left_click()
        logger.info('升级...')

    def play_again(self):
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/play_again.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.1)
            self.dd.left_click()
            time.sleep(0.1)
            self.dd.dd_dll.DD_mov(0, 0)
            logger.info('开始下一局游戏...')
            self.dd.dd_dll.DD_mov(0, 0)
            return True
        self.dd.dd_dll.DD_mov(0, 0)
        return False

    def check_client_window(self):
        handle = self.dm.FindWindow('RiotWindowClass', 'League of Legends (TM) Client')
        if handle:
            self.in_gaming = True
            self.get_gaming_window()
            return True
        handle = self.dm.FindWindow('RCLIENT', 'League of Legends')
        if not handle:
            return True
        for i in range(30):
            res = self.dm.GetClientSize(handle)
            if res[0] != 1 or res[1] == 0:
                self.set_window_position()
                time.sleep(1)
            else:
                break
            if i == 29:
                self.in_gaming = False
                return True
        if self.cur_window_handle != handle:
            self.get_client_window()
        return False

    def is_in_waiting(self):
        self.set_window_position()
        if self.is_close_game():
            return
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/paidui.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            return True
        return False

    def is_fh(self):
        self.set_window_position()
        if self.is_close_game():
            return
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/fh.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            return True
        return False

    def is_need_sure(self):
        self.set_window_position()
        if self.is_close_game():
            return
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2] + 150,
                              'img/sure1.bmp|img/sure2.bmp|img/sure3.bmp|img/sure4.bmp|img/sure5.bmp|img/sure6.bmp|img/sure7.bmp|img/sure8.bmp|img/sure9.bmp',
                              '000000', 1,
                              2)
        if res[0] != -1:
            if res[0] == 4:
                self.dd.dd_dll.DD_mov(res[1] + 38, res[2] + 91)
            else:
                self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.1)
            self.dd.left_click()
            time.sleep(0.05)
            logger.info(res)
            self.dd.dd_dll.DD_mov(0, 0)
            return True
        return False

    # 获取非游戏中的状态
    def get_status(self):
        self.set_window_position()
        time.sleep(1)

        # 识别第一阶段
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/status1.bmp',
                              '000000', 0.9,
                              2)

        if res[0] != -1:
            logger.info('登陆阶段')
            self.error_times = time.time()
            return self.login

        # 识别第二阶段
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/status2.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('选区阶段')
            self.error_times = time.time()
            return self.go_to_game

        # 检查客户端窗口
        if self.check_client_window():
            if int((time.time() - self.error_times)) >= 200:
                logger.info('客户端窗口异常,正在重新启动游戏...')
                raise ToRestartException
            return '客户端窗口消失:{}'.format(self.error_times)

        # 检查是否排队
        if self.is_in_waiting():
            self.error_times = time.time()
            return '正在排队中...'

        # 检查是否封号
        if self.is_fh():
            logger.info('账号已封停，等待处理中...')
            while True:
                data = {
                    'qq_number': self.qq_number,
                    'area': self.area,
                    'start_coin': self.start,
                    'now_coin': self.token_number,
                    'need_all': self.need,
                    'status': '封停',
                    'upgrade_time': time.time(),
                    'machine_name': self.machine_name,
                    'pwd': self.pwd,
                    'version_id': self.version_id,
                    'from': self.from_
                }
                self.send_info(data)
                while True:
                    self.get_and_deal_command()
                    time.sleep(30)

        if self.is_need_sure():
            self.error_times = time.time()
            return '点击确定'

        # 识别第三阶段
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/play.bmp|img/room.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('正在游戏大厅中')
            self.error_times = time.time()
            return self.game_client_status

        # 识别第四阶段
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/status4.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('选择游戏模式中')
            self.error_times = time.time()
            return self.choose_game_status

        # 识别第五阶段
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/status5.bmp',
                              '00000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('云顶之弈匹配房间中')
            self.error_times = time.time()
            return self.in_room_status

        # 进错模式
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/xg.bmp|img/sy.bmp',
                              '00000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('游戏房间错误')
            self.error_times = time.time()
            self.find_and_close_queue()
            return '处理游戏房间错误完成'

        # 客户端加载阶段
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/loading.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.error_times = time.time()
            return '正在加载客户端'

        # 开始下一局
        if self.play_again():
            self.error_times = time.time()
            return '开始下一局'

        # 检查对局问题
        if self.check_dj():
            raise ToRestartException

        # 客户端重连
        if self.check_reconnect():
            self.error_times = time.time()
            return '重新连接游戏'

        if int(time.time() - self.error_times) > 200:
            raise ToRestartException
        return '未包含状态:{}'.format(self.error_times)

    def is_in_gaming(self):
        # 激活当前窗口
        self.set_window_position()

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/in_gaming.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            return True
        return False

    def is_six(self):
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(141, 742, 164, 764, 'img/6ji.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('已到达六级')
            return True
        return False

    def loss_con(self):
        self.set_window_position()
        time.sleep(1)
        start_time = time.time()
        while True:
            res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/rec.bmp',
                                  '000000', 0.9,
                                  2)
            if res[0] != -1:
                logger.info('出现掉线:{}'.format(self.error_times))
                now_time = time.time()
                if now_time - start_time > 10:
                    raise ToRestartException
            else:
                break

    def go_to_site(self):
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/site.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            for i in range(3):
                self.dd.dd_dll.DD_mov(res[1], res[2])
                time.sleep(0.1)
                self.dd.right_click()
                self.dd.dd_dll.DD_mov(0, 0)
                time.sleep(1)
            time.sleep(0.5)

    def move_to_question(self):
        res = self.dm.FindColor(258, 133, 848, 531, '59fefe-000000|a4a7a4-000000', 1, 0)
        if res[0]:
            logger.info('发现问号')
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.3)
            self.dd.right_click()
        else:
            logger.info('自由移动')
            self.dm.MoveToEx(258, 133, 848, 531)
            time.sleep(0.05)
            self.dd.right_click()

    def get_gift(self):
        if self.is_close_game():
            return
        if not self.is_six_level:
            if self.is_six():
                self.is_six_level = True
        self.set_window_position()
        self.move_to_question()
        self.loss_con()
        time.sleep(2)
        return True

    def new_card(self):
        logger.info('刷新选秀区，获取新的卡牌')
        self.dd.dd_dll.DD_mov(91, 691)
        time.sleep(0.05)
        self.dd.left_click()

    def is_loading_gaming(self):
        # 激活当前窗口
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/load_game.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            return True
        return False

    def check_gaming_window(self):
        handle = self.dm.FindWindow('RiotWindowClass', 'League of Legends (TM) Client')
        if not handle:
            self.in_gaming = False
            return True
        for i in range(30):
            res = self.dm.GetClientSize(self.cur_window_handle)
            if res[0] != 1 or res[1] == 0:
                self.set_window_position()
                time.sleep(1)
            else:
                break
            if i == 29:
                self.in_gaming = False
                return True
        return False

    def is_close_game(self):
        self.set_window_position()
        time.sleep(1)

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/end_game.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dm.SetWindowState(self.this_window, 1)
            time.sleep(0.05)
            self.set_window_position()
            time.sleep(0.1)
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            logger.info('小小英雄死亡,点击离开游戏')
            time.sleep(3)
            self.dd.dd_dll.DD_mov(0, 0)
            return True
        return False

    # 获取游戏中的状态
    def get_in_gamin_status(self):
        if self.check_gaming_window():
            self.error_times = time.time()
            return '游戏窗口消失'
        elif self.is_loading_gaming():
            self.error_times = time.time()
            return '对局正在加载中'
        elif self.is_in_gaming():
            self.error_times = time.time()
            self.loss_con()
            if self.is_share():  # 共享选秀
                time.sleep(1)
                return '共享选秀中...'
            elif self.is_in_bz_status():  # 备战阶段
                self.set_equipment()
                self.get_erxing_legends_info()
                self.get_legends_info()
                self.set_equipment()
                self.replace_low_level()
                scan = True
                for i in range(2):
                    self.get_card_info()
                    self.buy_cards(scan)
                    if not self.is_six_level:
                        break
                    if self.is_six_level and i != 1:
                        self.new_card()
                    time.sleep(0.1)
                    scan = False
                for i in range(2):
                    self.up_level()
                    time.sleep(0.1)
                self.set_equipment()
                self.set_equipment()
            elif self.get_gift():
                return '移动完成'
            else:
                '未包含的情况'
        else:
            if int(time.time() - self.error_times) > 120:
                raise ToRestartException
            return '过渡阶段'

    def check_reconnect(self):
        self.set_window_position()
        time.sleep(1)
        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/cl.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.1)
            self.dd.left_click()
            logger.info('重新连接...')
            return True
        return False

    def check_dj(self):
        self.set_window_position()

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/dj.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            logger.info('出现对局问题，等待中...')
            for i in range(60):
                if self.check_reconnect():
                    break
                handle = self.dm.FindWindow('RiotWindowClass', 'League of Legends (TM) Client')
                if handle:
                    break
                if i == 59:
                    return True
            return False

    def replace_low_level(self):
        if not self.erxing_legends_position or not self.legends_position:
            return
        two_star_list = []
        one_star_list = []
        for item in self.erxing_legends_position:
            item = item.split(',')
            if int(item[2]) > 444:
                two_star_list.append(item)

        for item in self.legends_position:
            item = item.split(',')
            if int(item[2]) < 444:
                one_star_list.append(item)
        logger.info('正在用未上场的二星英雄，替换场上的一星英雄...')
        while one_star_list:
            one_star_item = one_star_list.pop()
            if two_star_list:
                two_star_item = two_star_list.pop()
                self.dd.dd_dll.DD_mov(int(two_star_item[1]) + 35, int(two_star_item[2]) + 50)
                time.sleep(0.2)
                self.dd.dd_dll.DD_btn(1)
                time.sleep(0.2)
                self.dd.dd_dll.DD_mov(int(one_star_item[1]) + 35, int(one_star_item[2]) + 50)
                time.sleep(0.2)
                self.dd.dd_dll.DD_btn(2)
                time.sleep(0.2)
            else:
                break

    def is_share(self):
        self.set_window_position()

        res = self.dm.FindPic(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/gxxx.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(430, 358)
            time.sleep(0.1)
            self.dd.right_click()
            return True
        return False

    def set_equipment(self):
        logger.info('正在给二星英雄上装备...')
        if not self.erxing_legends_position:
            return
        for i in range(4):
            res1 = self.dm.MoveToEx(61, 455, 105, 132)
            print(res1)
            time.sleep(0.5)
            cours_pos = self.dm.GetCursorPos()
            print(cours_pos)
            if cours_pos[0]:
                color_res1 = self.dm.FindColor(cours_pos[1], cours_pos[1], cours_pos[2] + 10, cours_pos[2] - 60,
                                               '00ff12-050505', 0.9, 0)
                if not color_res1[0]:
                    logger.info('装备选择错误')
                    continue
                color_res = self.dm.FindColor(cours_pos[1] - 50, cours_pos[1] - 50, cours_pos[2] + 50,
                                              cours_pos[2] + 50, 'f8453b-101010', 1, 0)
                if color_res[0]:
                    print(color_res)
                    break
            if i == 3:
                return
        self.dd.dd_dll.DD_btn(1)
        time.sleep(0.23)
        position = self.erxing_legends_position[random.randint(0, len(self.erxing_legends_position) - 1)]
        position = position.split(',')
        self.dd.dd_dll.DD_mov(int(position[1]) + 35, int(position[2]) + 50)
        time.sleep(0.2)
        self.dd.dd_dll.DD_btn(2)
        time.sleep(0.2)
        self.dd.dd_dll.DD_btn(2)
        time.sleep(0.05)
        self.dd.dd_dll.DD_btn(2)
        time.sleep(0.05)
        self.dd.dd_dll.DD_btn(2)

    def read_erxing_legends_info(self, position):
        position = position.split(',')
        self.set_window_position()
        self.dd.dd_dll.DD_mov(int(position[1]) + 43, int(position[2]) + 58)
        time.sleep(0.01)
        self.dd.right_click()
        time.sleep(0.35)
        self.dm.useDict(1)
        res = self.dm.Ocr(int(position[1]), int(position[2]) - 200, int(position[1]) + 350, int(position[2]) + 200,
                          'ffffff-505050', 0.8)
        self.erxing_legends_list.append(res)

    def get_erxing_legends_info(self):
        self.set_window_position()
        self.erxing_legends_list = []
        res = self.dm.FindPicEx(0, 0, self.cur_window_size[1], self.cur_window_size[2], 'img/erxing.bmp',
                                '000000', 0.9,
                                2)
        if res:
            legends_postion_list = res.split('|')
            self.erxing_legends_position = legends_postion_list.copy()
            logger.info('正在读取二星英雄信息...')
            for postion in legends_postion_list:
                self.read_erxing_legends_info(postion)
            self.dd.right_click()
            logger.info('二星英雄信息读取完成:{}'.format(self.erxing_legends_list))

    def get_cur_window_handle(self):
        logger.info('正在获取当前需要的窗口句柄...')
        handle = self.dm.FindWindow('RiotWindowClass', 'League of Legends (TM) Client')
        if not handle:
            handle = self.dm.FindWindow('RCLIENT', 'League of Legends')
            if not handle:
                handle = self.dm.FindWindow('TWINCONTROL', '英雄联盟登录程序')
                if not handle:
                    return False
                self.get_login_window()
                return True
            self.get_client_window()
            return True
        self.get_gaming_window()
        return True

    def restart_game(self):
        # 关闭游戏

        data = {
            'qq_number': self.qq_number,
            'area': self.area,
            'start_coin': self.start,
            'now_coin': self.token_number,
            'need_all': self.need,
            'status': '重启游戏',
            'upgrade_time': time.time(),
            'machine_name': self.machine_name,
            'pwd': self.pwd,
            'version_id': self.version_id,
            'from': self.from_
        }
        self.send_info(data)
        os.system('taskkill /IM "League of Legends.exe" /F')
        os.system('taskkill /IM LeagueClient.exe /F')
        os.system('taskkill /IM Client.exe /F')
        os.system('taskkill /IM TPHelper.exe /F')
        self.init_base_data()
        self.is_need_sure()
        self.error_times = time.time()
        self.on_game()
        self.get_login_window()

    def main_loop(self):
        """
        主循环
        识别当前状态后调用相应的函数
        :return:
        """
        logger.info('启动成功')
        try:
            if not self.get_cur_window_handle():
                # self.run_nb_master()
                self.on_game()
                self.get_login_window()
        except ToRestartException:
            self.restart_game()

        while True:
            try:
                if self.in_gaming:
                    status = self.get_in_gamin_status()
                else:
                    status = self.get_status()
                if callable(status):
                    status()
                else:
                    logger.info(status)
                time.sleep(1)
            except ToRestartException:
                self.restart_game()
            except FinishException as e:
                handle = e.handle
                while True:
                    logger.info('向服务器请求账号...')
                    data = {
                        'machine-pre': self.machine_name.split('|')[0]
                    }
                    server_data = requests.post(self.addr.format('get_qq'), data=data).text
                    server_json_data = json.loads(server_data)
                    server_data = server_json_data['data']
                    if server_data != '无账号':
                        self.dm.FoobarClose(handle)
                        self.qq_number = server_data['qq_number']
                        self.pwd = server_data['qq_pwd']
                        self.area = server_data['area']
                        self.need = server_data['need']
                        self.from_ = server_data['from']
                        with open('setting.conf', 'r', encoding='utf-8') as f:
                            data = f.read()
                            if data.startswith('\ufeff'):
                                data = data.encode('utf8')[3:].decode('utf8')
                            data = json.loads(data)
                            json_data = data
                        json_data['success'] = -1
                        json_data['QQ'] = server_data['qq_number']
                        json_data['PWD'] = server_data['qq_pwd']
                        json_data['Area'] = server_data['area']
                        json_data['Need'] = server_data['need']
                        json_data['From'] = server_data['from']
                        with open('setting.conf', 'w', encoding='utf-8') as f:
                            json_text = json.dumps(json_data, ensure_ascii=False)
                            f.write(json_text)
                        data = {
                            'qq_number': self.qq_number,
                            'area': self.area,
                            'start_coin': self.start,
                            'now_coin': self.token_number,
                            'need_all': self.need,
                            'status': '获取账号成功',
                            'upgrade_time': time.time(),
                            'machine_name': self.machine_name,
                            'pwd': self.pwd,
                            'version_id': self.version_id,
                            'from': self.from_
                        }
                        self.send_info(data)
                        self.restart_game()
                        break
                    data = {
                        'qq_number': self.qq_number,
                        'area': self.area,
                        'start_coin': self.start,
                        'now_coin': self.token_number,
                        'need_all': self.need,
                        'status': '等待账号中...',
                        'upgrade_time': time.time(),
                        'machine_name': self.machine_name,
                        'pwd': self.pwd,
                        'version_id': self.version_id,
                        'from': self.from_
                    }
                    self.send_info(data)
                    time.sleep(30)

    def set_window_position_and_size(self):
        handle = self.dm.FindWindow('ConsoleWindowClass', os.getcwd())
        if handle:
            self.this_window = handle
        self.dm.MoveWindow(handle, 1280, 0)
        self.dm.SetWindowSize(handle, 640, 720)

    def is_change_hard(self):
        time.sleep(1)
        res = self.dm.FindPic(0, 0, 529, 525, 'img/nb1.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            return True
        return False

    def is_change_hard_ok(self):
        time.sleep(1)
        res = self.dm.FindPic(0, 0, 529, 525, 'img/nb2.bmp',
                              '000000', 0.9,
                              2)
        if res[0] != -1:
            self.dd.dd_dll.DD_mov(res[1], res[2])
            time.sleep(0.5)
            self.dd.left_click()
            time.sleep(0.5)
            self.dd.dd_dll.DD_mov(0, 0)
            return True
        return False

    def set_nb_window(self):
        logger.info('开始获取牛逼硬件大师窗口...')
        for i in range(30):
            handle = self.dm.FindWindow('#32770', '牛B硬件信息修改大师')
            if handle:
                logger.info('获取牛逼硬件大师窗口成功')
                logger.info('正在设置牛逼硬件大师的窗口位置...')
                self.dm.MoveWindow(handle, 0, 0)
                break
        return True

    def run_nb_master(self):
        """
        执行牛逼大师
        :return:
        """
        logger.info('正在修改硬件信息...')
        win32api.ShellExecute(0, 'open', r'nb.exe', '', '', 1)
        for i in range(3):
            self.set_nb_window()
            for j in range(20):
                if self.is_change_hard():
                    break
                if j == 19:
                    return
            for k in range(30):
                if self.is_change_hard_ok():
                    break
                if k == 19:
                    return
            logger.info('第{}次修改完成'.format(i + 1))
        os.system('taskkill /F /IM nb.exe')
        self.error_times = time.time()
        logger.info('硬件信息修改完成')

    def check_version(self):
        version_id = self.version_id
        logger.info('检车更新')
        url = self.addr.format('get_version')
        try:
            msg = requests.get(url).text
            json_data = json.loads(msg)
        except Exception as e:
            logger.info('检查更新失败，继续执行')
            return
        server_version_id = json_data['version_id']
        if int(server_version_id) > version_id:
            logger.info('发现新版本')
            url = json_data['url']
            logger.info('正在下载新版本')
            data = None
            for i in range(10):
                try:
                    data = requests.get(url)
                    break
                except Exception as e:
                    logger.info('下载更新失败，5秒后重试')
                    time.sleep(5)
                if i == 9:
                    while True:
                        logger.info('更新失败，等待处理...')
                        data = {
                            'qq_number': self.qq_number,
                            'area': self.area,
                            'start_coin': self.start,
                            'now_coin': self.token_number,
                            'need_all': self.need,
                            'status': '脚本更新失败',
                            'upgrade_time': time.time(),
                            'machine_name': self.machine_name,
                            'pwd': self.pwd,
                            'version_id': self.version_id,
                            'from': self.from_
                        }
                        self.send_info(data)
                        time.sleep(9999)
            with open('{}.exe'.format(server_version_id), 'wb') as f:
                f.write(data.content)
            logger.info('下载完成，启动新版本...')
            try:
                win32api.ShellExecute(0, 'open', '{}.exe'.format(server_version_id), '', '', 1)
                logger.info('新版本启动成功')
                sys.exit(0)
            except Exception:
                logger.info('启动失败，等待处理...')
                while True:
                    data = {
                        'qq_number': self.qq_number,
                        'area': self.area,
                        'start_coin': self.start,
                        'now_coin': self.token_number,
                        'need_all': self.need,
                        'status': '新版本脚本启动失败',
                        'upgrade_time': time.time(),
                        'machine_name': self.machine_name,
                        'pwd': self.pwd,
                        'version_id': self.version_id,
                        'from': self.from_
                    }
                    self.send_info(data)
                    time.sleep(9999)
        else:
            logger.info('未发现新版本')
            for i in range(10):
                pre_version_id = version_id - i - 1
                if os.path.exists('{}.exe'.format(pre_version_id)):
                    logger.info('删除旧版本')
                    os.remove('{}.exe'.format(pre_version_id))
            return


def go():
    # set_on_start()
    l = Lol()
    l.main_loop()


if __name__ == '__main__':
    go()
