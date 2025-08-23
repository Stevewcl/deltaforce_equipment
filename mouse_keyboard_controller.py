import ctypes
from ctypes import wintypes

# 定义鼠标事件常量
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
WHEEL_DELTA = 120

# 定义键盘事件常量
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002

# 常用虚拟键代码
VIRTUAL_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "caps_lock": 0x14,
    "esc": 0x1B,
    "space": 0x20,
    "left_arrow": 0x25,
    "up_arrow": 0x26,
    "right_arrow": 0x27,
    "down_arrow": 0x28,
    "0": 0x30,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
    "5": 0x35,
    "6": 0x36,
    "7": 0x37,
    "8": 0x38,
    "9": 0x39,
    "a": 0x41,
    "b": 0x42,
    "c": 0x43,
    "d": 0x44,
    "e": 0x45,
    "f": 0x46,
    "g": 0x47,
    "h": 0x48,
    "i": 0x49,
    "j": 0x4A,
    "k": 0x4B,
    "l": 0x4C,
    "m": 0x4D,
    "n": 0x4E,
    "o": 0x4F,
    "p": 0x50,
    "q": 0x51,
    "r": 0x52,
    "s": 0x53,
    "t": 0x54,
    "u": 0x55,
    "v": 0x56,
    "w": 0x57,
    "x": 0x58,
    "y": 0x59,
    "z": 0x5A,
    "win": 0x5B,
}

# 加载 user32.dll
user32 = ctypes.WinDLL('user32', use_last_error=True)

class MouseKeyboardController:
    def __init__(self):
        self.user32 = user32

    # 鼠标操作
    def mouse_moveTo(self, x, y):
        """设置鼠标位置"""
        self.user32.SetCursorPos(wintypes.INT(x), wintypes.INT(y))

    def mouse_click(self, x=None, y=None, button="left"):
        """模拟鼠标点击，可指定位置"""
        if x is not None and y is not None:
            self.mouse_moveTo(x, y)  # 设置鼠标位置

        if button == "left":
            self.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)  # 按下左键
            self.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)    # 松开左键
        elif button == "right":
            self.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)  # 按下右键
            self.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)    # 松开右键

    def mouse_move(self, dx, dy):
        """相对移动鼠标"""
        self.user32.mouse_event(MOUSEEVENTF_MOVE, wintypes.INT(dx), wintypes.INT(dy), 0, 0)

    def mouse_scroll(self, lines, x=None, y=None):
        """垂直滚轮：正数向上，负数向下；可选先移动到 (x, y)"""
        if x is not None and y is not None:
            self.mouse_moveTo(x, y)
        delta = int(lines) * WHEEL_DELTA
        self.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, wintypes.INT(delta), 0)

    def mouse_hscroll(self, lines):
        """水平滚轮：正数向右，负数向左"""
        delta = int(lines) * WHEEL_DELTA
        self.user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, wintypes.INT(delta), 0)

    # 键盘操作
    def key_down(self, key_name):
        """通过虚拟键名称按下按键"""
        key_code = VIRTUAL_KEYS.get(key_name.lower())
        if key_code is not None:
            self.user32.keybd_event(wintypes.BYTE(key_code), 0, KEYEVENTF_KEYDOWN, 0)
        else:
            raise ValueError(f"未找到虚拟键名称: {key_name}")

    def key_up(self, key_name):
        """通过虚拟键名称释放按键"""
        key_code = VIRTUAL_KEYS.get(key_name.lower())
        if key_code is not None:
            self.user32.keybd_event(wintypes.BYTE(key_code), 0, KEYEVENTF_KEYUP, 0)
        else:
            raise ValueError(f"未找到虚拟键名称: {key_name}")

    def key_press(self, key_name):
        """通过虚拟键名称模拟按键"""
        key_code = VIRTUAL_KEYS.get(key_name.lower())
        if key_code is not None:
            self.key_down(key_name)
            self.key_up(key_name)
        else:
            raise ValueError(f"未找到虚拟键名称: {key_name}")

    def press_combo(self, key_names):
        """
        模拟组合键操作：按下所有按键，然后释放所有按键
        :param key_names: 按键名称列表，例如 ["ctrl", "alt", "del"]
        """
        try:
            # 按下所有按键
            for key_name in key_names:
                self.key_down(key_name)

            # 按相反顺序释放所有按键
            for key_name in reversed(key_names):
                self.key_up(key_name)
        except ValueError as e:
            print(f"组合键操作失败: {e}")