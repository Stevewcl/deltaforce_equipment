"""
三角洲买装备脚本
功能：通过高频刷新交易行界面监控装备价格，截取低价装备购买
"""
import mss
import numpy as np
import win32gui
import win32process
import psutil
import win32con
from PIL import ImageDraw
import detect_money
import detect_location
import threading
import queue
import time
import schedule
import configparser
import pyautogui
import pytesseract
import os
import sys
import datetime
import keyboard
from dataclasses import dataclass
from mouse_keyboard_controller import MouseKeyboardController

controller = MouseKeyboardController()

# 获取脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 使用相对路径读取配置文件
config_path = os.path.join(BASE_DIR, 'config.ini')

config = configparser.ConfigParser()
# 显式指定 UTF-8 编码来读取文件
with open(config_path, encoding='utf-8') as f:
    config.read_file(f)

# --- 配置参数 ---
game_name = config['window']['game_window_name']  # 游戏窗口名称
min_width = int(config['window']['min_width'])  # 最小窗口宽度
min_height = int(config['window']['min_height'])  # 最小窗口高度
expected_price_1 = int(config['limit']['expected_price_1']) # 价格下限
expected_price_2 = int(config['limit']['expected_price_2'])  # 价格上限
x = int(config['click_location']['x'])  # 收藏物品X坐标
y = int(config['click_location']['y'])  # 收藏物品Y坐标
execution_time = config['schedule']['execution_time']  # 脚本执行时间
execution_time_single = int(config['schedule']['execution_time_single'])  # 单次执行时长(秒)
duration = int(config['schedule']['duration'])  # 总运行时长(秒)

# --- 控制标志 ---
paused = False  # 控制脚本暂停/恢复
should_exit = False  # 标记主程序的运行与结束
thread_pause_click = False  # 控制连点线程的暂停
thread_running = True  # 控制主程序运行与结束时子线程的运行与结束
game_window_hwnd = None  # 游戏主窗口句柄

# --- 线程通信 ---
color_check_result = False  # 线程安全变量，存储颜色检测结果
color_check_lock = threading.Lock()  # 颜色检测结果的线程锁

# --- 统计数据 ---
start_time_single = time.time()  # 计时器初始值
consumption = initial_money = end_money = 0  # 消耗的哈夫币统计


class Tee:
    """
    同时将输出重定向到控制台和日志文件的类

    实现了标准输出的重定向，同时捕获未处理的异常并记录到日志文件
    """

    def __init__(self, filename=None):
        """
        初始化Tee对象，设置日志文件路径并重定向标准输出

        参数:
            filename: str - 日志文件名，如果为None则使用当前时间戳命名
        """
        log_dir = os.path.join(BASE_DIR, 'logs')  # 指定日志保存路径
        os.makedirs(log_dir, exist_ok=True)  # 确保目录存在

        # 如果没有提供文件名，则以当前时间命名
        if filename is None:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"log_{timestamp}.txt"

        self.file = open(os.path.join(log_dir, filename), "a", encoding="utf-8")  # 追加模式
        self.stdout = sys.stdout
        sys.stdout = self

        # 设置异常钩子，捕获未处理的异常
        self.original_excepthook = sys.excepthook
        sys.excepthook = self.exception_handler

    def write(self, message):
        """
        写入消息到标准输出和日志文件

        参数:
            message: str - 要写入的消息
        """
        # 获取当前时间戳，精确到毫秒
        timestamp = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] "
        # 在每条日志前添加时间戳
        if message.strip():  # 仅对非空行添加时间戳
            message = f"{timestamp}{message}"  # 确保时间戳格式完整
        self.stdout.write(message)  # 在 CMD 窗口打印
        self.file.write(message)  # 同时写入文件
        self.flush()  # 确保日志信息立即写入文件

    def flush(self):
        """确保日志即时写入文件和标准输出"""
        self.stdout.flush()
        self.file.flush()

    def exception_handler(self, exc_type, exc_value, exc_traceback):
        """
        处理未捕获的异常，将异常信息记录到日志文件

        参数:
            exc_type: 异常类型
            exc_value: 异常值
            exc_traceback: 异常的堆栈跟踪
        """
        # 将异常信息格式化为字符串
        import traceback
        exception_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        # 写入日志
        self.write("\n*** 捕获到未处理的异常 ***\n")
        self.write(f"{exception_str}\n")
        self.write("*** 异常信息结束 ***\n")
        self.flush()
        # 调用原始异常处理器
        self.original_excepthook(exc_type, exc_value, exc_traceback)


@dataclass(frozen=True)
class PurchaseEvent:
    kind: str              # 'six_digits' | 'no_items' | 'seven_sep'
    data: int | None = None

class PurchaseStateMonitor:
    """
    并行监测三种状态，任一命中产生事件；随后进入失效态，
    待检测到“三种状态均不命中”连续 N 次后再重武装。
    """
    def __init__(self, poll_interval: float = 0, rearm_clear_consecutive: int = 1):
        self.poll_interval = poll_interval
        self.rearm_clear_consecutive = rearm_clear_consecutive

        self._stop = threading.Event()
        self._armed = True
        self._armed_lock = threading.Lock()

        self._present = {'six': False, 'no': False, 'seven': False}
        self._present_lock = threading.Lock()

        self._q: "queue.Queue[PurchaseEvent]" = queue.Queue(maxsize=1)
        self._threads: list[threading.Thread] = []

    def start(self):
        self._threads = [
            threading.Thread(target=self._watch_six_digits, daemon=True),
            threading.Thread(target=self._watch_no_items, daemon=True),
            threading.Thread(target=self._watch_seven_sep, daemon=True),
            threading.Thread(target=self._watch_rearm_all_clear, daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)

    def get_event(self, timeout: float | None = None) -> PurchaseEvent:
        return self._q.get(timeout=timeout)


    def clear_pending(self) -> None:
        """
        清空待处理事件，避免消费到上一次循环的残留事件。
        采用与投递相同的锁以避免竞态。
        """
        with self._armed_lock:
            while True:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
    def _emit_if_armed(self, evt: PurchaseEvent) -> bool:
        """
        若当前处于武装态，投递事件并转入失效态；返回 True 表示成功投递（可打印一次性日志）。
        """
        with self._armed_lock:
            if not self._armed:
                return False
            # 清理可能残留的旧事件，确保只保留最新命中的
            while not self._q.empty():
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
            self._q.put(evt)
            self._armed = False
            return True

    def _watch_six_digits(self):
        while not self._stop.is_set():
            val = detect_money.main()
            hit = isinstance(val, int) and 100000 <= val <= 999999
            with self._present_lock:
                self._present['six'] = hit
            if hit:
                self._emit_if_armed(PurchaseEvent('six_digits', val))
            time.sleep(self.poll_interval)

    def _watch_no_items(self):
        while not self._stop.is_set():
            hit = is_color_similar(1630, 889, (75, 79, 82), 10)
            with self._present_lock:
                self._present['no'] = hit
            if hit:
                self._emit_if_armed(PurchaseEvent('no_items', None))
            time.sleep(self.poll_interval)

    def _watch_seven_sep(self):
        while not self._stop.is_set():
            hit = is_color_similar(313, 193, (179, 181, 183), 10)
            with self._present_lock:
                self._present['seven'] = hit
            if hit:
                self._emit_if_armed(PurchaseEvent('seven_sep', None))
            time.sleep(self.poll_interval)

    def _watch_rearm_all_clear(self):
        clear_cnt = 0
        while not self._stop.is_set():
            with self._armed_lock:
                armed = self._armed
            if armed:
                clear_cnt = 0
                time.sleep(self.poll_interval)
                continue

            with self._present_lock:
                any_hit = self._present['six'] or self._present['no'] or self._present['seven']

            if not any_hit:
                clear_cnt += 1
                if clear_cnt >= self.rearm_clear_consecutive:
                    with self._armed_lock:
                        self._armed = True
                    clear_cnt = 0
            else:
                clear_cnt = 0
            time.sleep(self.poll_interval)


def take_screenshot(price):
    """
    截取当前屏幕并保存，包含鼠标指针位置

    参数:
        price: int - 当前识别到的价格，将添加到文件名中

    功能:
        1. 创建包含时间戳和价格的文件名
        2. 截取全屏
        3. 在截图上标记当前鼠标位置
        4. 保存截图到指定目录
    """
    # 获取当前时间戳，精确到毫秒
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3]
    # 将价格添加到文件名中
    screenshot_path = os.path.join(BASE_DIR, 'screenshots', f"screenshot_{timestamp}_price_{price}.png")
    os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)  # 确保目录存在

    # 使用pyautogui截取全屏
    screenshot = pyautogui.screenshot()

    # 获取鼠标位置，用于在截图上标记鼠标位置
    cursor_pos = win32gui.GetCursorPos()

    # 获取当前使用的鼠标光标
    cursor_info = win32gui.GetCursorInfo()
    cursor = cursor_info[1]  # 获取光标句柄

    # 获取光标信息
    if cursor:
        try:
            # 将光标绘制到截图上
            draw = ImageDraw.Draw(screenshot)

            # 绘制一个红色圆点表示光标位置，便于后续分析问题
            draw.ellipse((cursor_pos[0] - 2, cursor_pos[1] - 2,
                          cursor_pos[0] + 2, cursor_pos[1] + 2), fill='red')

        except Exception as e:
            print(f"无法添加鼠标指针: {str(e)}")

    # 保存图片
    screenshot.save(screenshot_path)
    print(f"全屏幕截屏(含鼠标指针)已保存到 {screenshot_path}")


def get_window_normal_size(hwnd):
    """
    获取窗口的正常尺寸，即使它当前是最小化的

    参数:
        hwnd: int - 窗口句柄

    返回:
        tuple: (width, height) - 窗口的宽度和高度

    功能:
        1. 检查窗口是否最小化
        2. 如果是最小化状态，获取其正常位置信息
        3. 如果不是最小化状态，直接获取当前尺寸
        4. 返回窗口的宽度和高度
    """
    minimized = win32gui.IsIconic(hwnd)

    if minimized:
        # 获取窗口的正常位置信息（即使窗口是最小化的）
        window_placement = win32gui.GetWindowPlacement(hwnd)
        normal_rect = window_placement[4]  # normalPosition属性
        width = normal_rect[2] - normal_rect[0]
        height = normal_rect[3] - normal_rect[1]
        return width, height
    else:
        # 窗口未最小化，直接获取当前尺寸
        rect = win32gui.GetWindowRect(hwnd)
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        return width, height


def find_game_window():
    """
    查找游戏窗口，通过尺寸区分游戏本体和启动器

    返回:
        int: 游戏窗口句柄，若未找到则返回0

    功能:
        1. 枚举所有窗口，筛选出标题包含游戏名称的窗口
        2. 获取这些窗口的尺寸和进程信息
        3. 根据最小尺寸要求筛选出符合条件的窗口
        4. 选择尺寸最大的窗口作为游戏主窗口
    """
    global game_window_hwnd

    windows = []

    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if game_name.lower() in title.lower():
                # 获取窗口正常尺寸（即使最小化）
                width, height = get_window_normal_size(hwnd)
                # 获取进程信息
                try:
                    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                    process = psutil.Process(pid)
                    exe_path = process.exe()
                    proc_name = process.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    exe_path = "未知"
                    proc_name = "未知"

                windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "width": width,
                    "height": height,
                    "size": width * height,
                    "exe_path": exe_path,
                    "process": proc_name
                })

    win32gui.EnumWindows(callback, None)

    # 按窗口尺寸排序，筛选出符合最小尺寸条件的窗口
    suitable_windows = [w for w in windows if w["width"] >= min_width and w["height"] >= min_height]

    if suitable_windows:
        # 按尺寸降序排序，选择最大的窗口
        suitable_windows.sort(key=lambda w: w["size"], reverse=True)
        game_window_hwnd = suitable_windows[0]["hwnd"]
        print(f"已找到游戏窗口: '{suitable_windows[0]['title']}'")
        print(f"窗口大小: {suitable_windows[0]['width']}x{suitable_windows[0]['height']}")
        print(f"进程: {suitable_windows[0]['process']} ({suitable_windows[0]['exe_path']})")
        return game_window_hwnd
    elif windows:
        print(f"找到的窗口均小于最小尺寸要求({min_width}x{min_height})，可能为启动器窗口:")
        for w in windows:
            print(f"- '{w['title']}' ({w['width']}x{w['height']}) - {w['process']}")
        return 0
    else:
        print(f"未找到包含'{game_name}'的窗口")
        return 0


def set_window_topmost(hwnd):
    """
    设置窗口置顶，如果窗口最小化则先恢复

    参数:
        hwnd: int - 窗口句柄

    返回:
        bool: 设置成功返回True，失败返回False

    功能:
        1. 检查窗口是否最小化，如果是则先恢复
        2. 调用Win32 API设置窗口为置顶状态
    """
    try:
        # 检查窗口是否最小化
        if win32gui.IsIconic(hwnd):
            # 先恢复窗口
            print("窗口已最小化，先恢复窗口")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # 给窗口一点时间恢复
            time.sleep(0.3)

        # 设置窗口置顶
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        print("已将窗口设置为置顶")
        return True
    except Exception as e:
        print(f"设置窗口置顶失败: {e}")
        return False


def unset_window_topmost(hwnd):
    """
    取消窗口置顶

    参数:
        hwnd: int - 窗口句柄

    返回:
        bool: 设置成功返回True，失败返回False

    功能:
        调用Win32 API取消窗口的置顶状态，使其恢复普通窗口层级
    """
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        print("已取消窗口置顶")
        return True
    except Exception as e:
        print(f"取消窗口置顶失败: {e}")
        return False


def toggle_pause():
    """
    切换脚本暂停状态，同时控制窗口置顶状态

    功能:
        1. 切换全局暂停标志
        2. 根据暂停状态设置或取消窗口置顶
        3. 输出暂停/恢复状态信息
    """
    global paused, game_window_hwnd
    paused = not paused

    if paused:
        print("脚本已暂停")
        # 暂停时取消窗口置顶
        # noinspection PyUnreachableCode
        if game_window_hwnd:
            unset_window_topmost(game_window_hwnd)
    else:
        print("脚本已恢复")
        # 恢复时重新置顶窗口
        # noinspection PyUnreachableCode
        if game_window_hwnd:
            set_window_topmost(game_window_hwnd)


# 监听快捷键 Ctrl+P
keyboard.add_hotkey('ctrl+p', toggle_pause)


def view_money(location, region):
    """
    识别并返回当前账号拥有的哈夫币数量

    参数:
        location: tuple - 哈夫币图标位置坐标(x, y)
        region: tuple - 哈夫币数量区域(x, y, width, height)

    返回:
        int 或 None: 识别到的哈夫币数量，识别失败返回None
    """
    # 移动鼠标到哈夫币图标位置，触发显示哈夫币数量的悬浮窗
    pyautogui.moveTo(location)
    time.sleep(0.5)  # 等待悬浮窗完全显示

    # 截取哈夫币数量区域的图像
    screenshot = pyautogui.screenshot(region=region)

    # 使用OCR识别图像中的数字，限制识别字符集为数字和逗号
    custom_config = r'--psm 6 -c tessedit_char_whitelist=0123456789,'
    money = pytesseract.image_to_string(screenshot, config=custom_config)

    try:
        # 输出识别结果并返回处理后的整数值
        print(f"当前哈夫币数量为{money.strip()}")
        # 移除换行符、空格和逗号，转换为整数
        return int(money.strip().replace("\n", "").replace(" ", "").replace(",", ""))
    except ValueError:
        # 如果转换失败（通常是因为OCR识别不准确），返回None
        return None


def is_color_similar(a, b, target_color, threshold=30):
    """
    使用 mss 截取 1x1 区域获取像素颜色
    读取失败返回 False。
    """
    try:
        with mss.mss() as sct:
            region = {"top": b, "left": a, "width": 1, "height": 1}
            img = np.array(sct.grab(region))  # BGRA
            bgr = img[0, 0, :3]
            pixel_color = (int(bgr[2]), int(bgr[1]), int(bgr[0]))  # 转 RGB
    except Exception:
        return False

    dr = pixel_color[0] - target_color[0]
    dg = pixel_color[1] - target_color[1]
    db = pixel_color[2] - target_color[2]
    return (dr * dr + dg * dg + db * db) ** 0.5 < threshold


def check_chi(region, content):
    """
    识别指定区域内的汉字是否与预期内容匹配

    参数:
        region: tuple - 截图区域 (x, y, width, height)
        content: str - 预期匹配的中文内容

    返回:
        bool: 匹配成功返回True，否则返回False
    """
    # 截取指定区域
    screenshot = pyautogui.screenshot(region=region)

    # 使用中文简体模型进行OCR识别
    check_result = pytesseract.image_to_string(screenshot, config='--psm 6', lang='chi_sim')

    try:
        # 比较OCR结果是否与预期内容完全匹配
        if check_result.strip() == content:
            return True
        return False
    except ValueError:
        # 处理异常情况
        return False


def refresh_operation():
    """
    刷新交易行状态，防止界面卡顿

    返回:
        bool: 当且仅当本次确实执行了刷新流程时返回 True，否则 False。
    """
    global thread_pause_click, start_time_single

    # 检查是否达到刷新时间间隔(配置文件默认180秒)
    if time.time() - start_time_single > execution_time_single:
        # 暂停线程
        thread_pause_click = True

        time.sleep(0.1)

        # flag用于标记是否已经从全面战场切换回烽火地带模式
        flag = False

        print("刷新交易行状态")
        # 处理各种可能的界面状态，循环直到成功回到交易行界面
        while True:
            time.sleep(0.5)
            if check_chi((814, 477, 19, 21), '为'):
                # 识别到"禁止使用市场..."界面提示，按ESC关闭
                controller.key_press('esc')

            elif is_color_similar(1771, 362, (234, 235, 235)):
                # 识别到交易行购买子弹的二级界面，按ESC返回一级界面
                controller.key_press('esc')

            elif is_color_similar(180, 106, (191, 195, 195)) or is_color_similar(180, 106, (81, 84, 85)):
                # 识别到交易行一级界面，按ESC关闭
                controller.key_press('esc')

            elif is_color_similar(1459, 1043, (67, 70, 72)):
                # 识别到烽火地带开始游戏界面
                if flag:
                    # 如果之前已执行过切换模式操作，返回交易行
                    pyautogui.moveTo(720, 80)  # 移动到交易行按钮位置下方
                    if not is_color_similar(720, 77, (91, 197, 146)):
                        pyautogui.move(0, -20, 0.1)  # 上移选择菜单项
                        time.sleep(0.2)
                        pyautogui.click()
                        time.sleep(0.1)
                        pyautogui.move(0, 20, 0.1)  # 重置鼠标位置
                    time.sleep(0.5)

                    # 点击收藏一号位，避免界面位移问题
                    for _ in range(3):
                        controller.mouse_click(660, 240)
                        time.sleep(0.2)
                    controller.key_press('esc')
                    time.sleep(0.5)

                    break  # 成功返回交易行，退出循环
                else:
                    # 否则先离开烽火地带
                    controller.key_press('esc')

            elif is_color_similar(1415, 1053, (82, 86, 88)):
                # 识别到全面战场开始游戏界面，按ESC离开
                controller.key_press('esc')

            elif is_color_similar(104, 330, (233, 234, 234)) and is_color_similar(104, 550, (99, 100, 99)):
                # 识别切换模式界面（此时在烽火地带）
                # 通过检查左侧菜单栏的颜色状态来判断当前游戏模式
                pyautogui.moveTo(250, 380)  # 移动到模式选择菜单
                # 切换到全面战场模式
                for _ in range(3):  # 通过多次点击确保成功选择
                    pyautogui.move(0, 20, 0.1)  # 下移选择菜单项
                    time.sleep(0.2)
                    pyautogui.click()
                    time.sleep(0.1)
                    pyautogui.move(0, -20, 0.1)  # 重置鼠标位置
                time.sleep(0.5)
                controller.key_press('space') # 关闭活动广告

            elif is_color_similar(104, 330, (88, 88, 89)) and is_color_similar(104, 550, (234, 235, 235)):
                # 识别切换模式界面（此时在全面战场）
                pyautogui.moveTo(250, 380)  # 移动到模式选择菜单
                # 切换到烽火地带模式
                for _ in range(3):  # 通过多次点击确保成功选择
                    pyautogui.move(0, -20, 0.1)  # 上移选择菜单项
                    time.sleep(0.2)
                    pyautogui.click()
                    time.sleep(0.1)
                    pyautogui.move(0, 20, 0.1)  # 重置鼠标位置
                time.sleep(0.5)
                controller.key_press('space')  # 关闭活动广告
                flag = True  # 标记已经执行了从全面战场到烽火地带的切换操作

        start_time_single = time.time()
        # 恢复线程
        thread_pause_click = False
        return True

    return False


def continuous_click_worker():
    """
    连续鼠标点击线程函数
    
    功能:
        以高频率持续点击指定位置
        可通过全局变量暂停和恢复
        用于快速刷新交易行物品列表
    """
    global thread_running, thread_pause_click

    while thread_running:
        # 检查线程是否需要暂停
        if thread_pause_click:
            time.sleep(0.05)  # 暂停状态下降低CPU使用率
            continue

        controller.mouse_click(x, y)  # 点击当前目标位置
        time.sleep(0.2)


def run_for_duration(duration_time):
    """
    在指定时间内执行交易行监控与操作：
    - 采用并发状态监测 + 消抖（武装/失效/重武装）
    - 保留定期刷新交易行、暂停/恢复连点、界面状态检查、二次检查价格等逻辑
    """
    global paused, should_exit, thread_running, thread_pause_click, start_time_single, \
        consumption, initial_money, end_money

    # 置顶窗口
    hwnd = find_game_window()
    if hwnd:
        set_window_topmost(hwnd)
    else:
        print("警告: 定时执行开始时未找到游戏窗口，无法置顶")

    # 初始资金与定位
    location, region = detect_location.main()
    initial_money = view_money(location, region)

    start_time = start_time_single = time.time()

    # 点击收藏一号位，避免界面位移
    for _ in range(3):
        controller.mouse_click(660, 240)
        time.sleep(0.2)
    controller.key_press('esc')
    time.sleep(0.5)

    # 启动线程
    thread_running = True
    thread_pause_click = False

    click_thread = threading.Thread(target=continuous_click_worker, daemon=True)
    click_thread.start()

    # 启动并发状态监测（六位价/暂无/七位分隔符）
    monitor = PurchaseStateMonitor(poll_interval=0, rearm_clear_consecutive=1)
    monitor.start()

    try:
        while time.time() - start_time < duration_time:
            # 暂停控制
            if paused:
                thread_pause_click = True
                while paused:
                    time.sleep(0.1)
                thread_pause_click = False
                continue

            # 定期刷新交易行
            refreshed = refresh_operation()
            if refreshed:
                monitor.clear_pending() # 清空待处理事件，避免消费到上一次循环的残留事件

            # 取事件（带短超时，便于循环做其它工作）
            try:
                evt = monitor.get_event(timeout=0.2)
            except queue.Empty:
                continue

            # 处理事件
            if evt.kind == 'six_digits':
                price = evt.data
                if expected_price_1 <= price <= expected_price_2:
                    print(f"识别到价格{price}")
                    # 暂停连点，避免干扰购买操作
                    thread_pause_click = True
                    controller.mouse_moveTo(1746, 900)
                    controller.mouse_move(0, 10)
                    controller.mouse_click()

                    # take_screenshot(price)
                    time.sleep(0.5)
                    thread_pause_click = False

                controller.key_press('esc')

            elif evt.kind in ('no_items', 'seven_sep'):
                # 无货或七位分隔符，直接返回
                controller.key_press('esc')

    finally:
        # 停止监测与线程
        monitor.stop()
        thread_running = False
        click_thread.join(timeout=1.0)

        # 统计最终消耗
        time.sleep(1)
        location, region = detect_location.main()
        end_money = view_money(location, region)
        if end_money is not None:
            consumption_delta = initial_money - end_money if initial_money is not None else 0
            consumption_total = consumption + consumption_delta
            consumption_str = "{:,}".format(consumption_total)
        else:
            print("最终哈夫币数量无法识别")
            consumption_str = "识别失败"

        print(f"时间到，总计消耗哈夫币：{consumption_str}")
        should_exit = True


def main():
    """
    主函数，调度整个脚本的执行

    功能:
        1. 设置定时任务
        2. 等待定时任务执行
        3. 处理退出信号
    """
    global game_window_hwnd, should_exit

    # 查找游戏窗口（在定时执行时置顶）
    game_window_hwnd = find_game_window()

    # 输出脚本即将执行的时间和持续时长
    print(f"{execution_time}开始执行，执行{duration}秒")

    # 设置定时任务，在指定时间执行run_for_duration函数
    schedule.every().day.at(execution_time).do(run_for_duration, duration_time=duration)

    # 持续运行，直到收到退出信号
    try:
        while not should_exit:
            # 检查并执行到期的定时任务
            schedule.run_pending()
            # 每秒检查一次，降低CPU占用
            time.sleep(1)
    finally:
        # 脚本结束时，取消窗口置顶
        if game_window_hwnd:
            unset_window_topmost(game_window_hwnd)


if __name__ == "__main__":
    # 创建Tee实例，重定向输出到日志文件
    tee = Tee()
    sys.stdout = tee

    # 记录当前时间作为日志标题
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n====== 运行时间: {timestamp} ======\n")

    try:
        # 运行主程序
        main()
    finally:
        # 确保线程停止
        thread_running = False
        # 给线程一点时间退出
        time.sleep(0.5)

        # 关闭日志文件并恢复标准输出
        sys.excepthook = tee.original_excepthook
        sys.stdout = tee.stdout
        tee.file.close()

        print(f"日志已保存到 {tee.file.name}")
