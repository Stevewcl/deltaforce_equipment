"""
价格数字识别模块
功能：识别六位数价格的十万位和万位，剩余位数补0
"""
import mss
import cv2
import os
import numpy as np
from typing import Sequence
from concurrent.futures import ThreadPoolExecutor
import time

# 获取脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 预加载数字模板图像
templates = {
    i: cv2.imread(os.path.join(BASE_DIR, 'image', f'{i}_gray_image.png'), cv2.IMREAD_GRAYSCALE)
    for i in range(10)
}


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


def match_template(image: np.ndarray, template: np.ndarray) -> tuple[float, Sequence[int]]:
    """
    执行模板匹配，返回最佳匹配度和匹配位置

    参数:
        image: np.ndarray - 待匹配的图像
        template: np.ndarray - 模板图像

    返回:
        tuple: (匹配度, (x, y)位置) 匹配度范围0-1，值越大匹配度越高
    """
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return max_val, max_loc


def find_best_match(image_part: np.ndarray, threshold: float = 0.95) -> tuple[None, float] | tuple[int, float]:
    """
    在图像部分中找到最佳匹配的数字模板

    参数:
        image_part: np.ndarray - 待识别的图像部分
        threshold: float - 匹配度阈值，默认0.95

    返回:
        tuple: (识别的数字或None, 匹配度) 当匹配度低于阈值时返回None
    """

    def match(num_template):
        """内部函数：对单个数字模板进行匹配"""
        num, template = num_template
        return num, match_template(image_part, template)[0]  # 返回(数字,匹配度)元组

    # 使用线程池并行化模板匹配，并行处理10个数字模板的匹配
    with ThreadPoolExecutor() as executor:
        match_values = list(executor.map(match, templates.items()))

    # 找到最佳匹配（匹配度最高的数字）
    best_match = max(match_values, key=lambda item: item[1])
    if best_match[1] < threshold:  # 如果最佳匹配度小于阈值
        return None, best_match[1]  # 返回None表示无法可靠识别
    return best_match[0], best_match[1]  # 返回识别的数字和匹配度


def capture_with_mss(region):
    """
    使用mss库截图并返回灰度图像

    参数:
        region: tuple - 截图区域 (top, left, width, height)

    返回:
        np.ndarray: 灰度处理后的截图图像
    """
    with mss.mss() as sct:
        # 将简化的 region 转换为 mss 所需的字典格式
        region_dict = {"top": region[0], "left": region[1], "width": region[2], "height": region[3]}
        screenshot = sct.grab(region_dict)  # 执行截图
        img = np.array(screenshot)[:, :, :3]  # 去掉 alpha 通道，只保留RGB三个通道
        return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)  # 返回灰度图像


def match_image_templates_six_digits_hundred_thousands_and_ten_thousands() -> tuple[tuple[int | None, float], tuple[int | None, float]]:
    """
    识别六位数价格中的十万位和万位
    返回: ((十万位或None, 分数), (万位或None, 分数))
    """
    # 使用新区域并分割为左右两部分：左=十万位，右=万位
    region = (176, 299, 24, 17)
    img = capture_with_mss(region)

    left_part = img[:, :11]     # 十万位
    right_part = img[:, -11:]   # 万位

    hundred_thousands_detected = find_best_match(left_part)
    ten_thousands_detected = find_best_match(right_part)

    return hundred_thousands_detected, ten_thousands_detected


def detect_six_digits_hundred_thousands_and_ten_thousands() -> int | None:
    """
    返回价格（十万位和万位组成，剩余位数为0）。识别失败返回None。
    若界面不存在数字，返回0（沿用原颜色判断逻辑）。
    """
    ht, tt = match_image_templates_six_digits_hundred_thousands_and_ten_thousands()
    if ht[0] is None or tt[0] is None:
        return None
    return int(ht[0]) * 100000 + int(tt[0]) * 10000


def main():
    """
    识别六位数的十万位与万位
    """
    return detect_six_digits_hundred_thousands_and_ten_thousands()


if __name__ == "__main__":
    time.sleep(3)
    print(main())
