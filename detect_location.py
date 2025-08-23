"""
三角洲哈夫币界面位置检测模块
功能：检测游戏界面中哈夫币图标和数量的位置，用于后续截图和识别
"""
import time
import pyautogui
import cv2
import os
import numpy as np

# 获取脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 加载模板图像
template_path = os.path.join(BASE_DIR, 'image', 'coin_template.png')
template = cv2.imread(template_path)

def detect_coin_location():
    """
    检测哈夫币图标在屏幕上的位置

    实现原理：
        1. 在屏幕特定区域内截图
        2. 使用模板匹配算法找到哈夫币图标

    返回:
        tuple: (x, y) 坐标，表示哈夫币图标的中心位置
    """
    # 设置截图的区域 (屏幕坐标)
    # 该区域是通过实验确定的哈夫币图标可能出现的位置范围
    # 在游戏界面的右上角区域，宽度300像素足够包含完整的哈夫币图标
    x, y, width, height = 1450, 44, 300, 17
    region = (x, y, width, height)

    # 截取屏幕特定区域
    screenshot = pyautogui.screenshot(region=region)
    # 转换图像格式为OpenCV可处理的BGR格式
    screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    # 模板匹配 - 使用归一化互相关系数方法(TM_CCOEFF_NORMED)
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)

    # 找到最佳匹配位置
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    # max_val表示匹配度，值域为[0,1]，越接近1表示匹配度越高
    # max_loc为匹配位置在截图中的坐标

    # 计算匹配位置在屏幕中的绝对坐标
    # 需要加上区域的起始坐标(x,y)才能得到屏幕绝对坐标
    top_left_screen = (x + max_loc[0], y + max_loc[1])

    # 返回哈夫币图标位置的绝对坐标
    location = top_left_screen[0], top_left_screen[1]

    return location

def detect_money_location():
    """
    检测哈夫币数量文本在屏幕上的区域

    实现原理：
        1. 在屏幕特定区域内截图
        2. 使用模板匹配算法找到哈夫币图标
        3. 根据图标位置计算出数量文本的区域

    返回:
        tuple: (x, y, width, height) 表示哈夫币数量文本的区域
    """
    # 设置截图的区域 (屏幕坐标)
    # 与上一个函数不同，这里识别的是当鼠标移动至上一个函数所识别到的哈夫币图标时，所出现的更详细界面中的哈夫币图标
    x, y, width, height = 1400, 249, 240, 17
    region = (x, y, width, height)

    # 截取屏幕特定区域
    screenshot = pyautogui.screenshot(region=region)
    screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    # 模板匹配
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)

    # 找到最佳匹配位置
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    # 计算匹配位置在屏幕中的坐标
    top_left_screen = (x + max_loc[0], y + max_loc[1])

    # 根据图标位置确定数量文本区域
    # 偏移量+16和+19通过截图测试确定
    # +16表示向右偏移16像素(文本在图标右侧)
    # +19表示向下偏移19像素(文本在图标右下方)
    # 宽度110确保能包含完整的数字，高度17覆盖文本的垂直范围
    region_2 = top_left_screen[0] + 16, top_left_screen[1] + 19, 110, 17

    return region_2

def main():
    """
    主函数，执行位置检测并返回结果

    功能：
        1. 检测哈夫币图标位置
        2. 检测哈夫币数量区域
        3. 输出检测结果

    返回:
        tuple: (location, region) 包含图标位置和数量区域
    """
    location = detect_coin_location()
    pyautogui.moveTo(location)
    time.sleep(0.5)
    region = detect_money_location()

    pyautogui.hotkey('alt', 'tab')
    print(f'哈夫币图标位置区域：{location}  哈夫币数量位置区域：{region}')

    return location, region

if __name__ == "__main__":
    main()
